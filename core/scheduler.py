from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from typing import Dict, Callable
import asyncio
import logging
from database.crud import *
from database.models import SessionLocal, Post
from core.rss_parser import RSSParser
from core.ai_processor import AIProcessor
from core.publisher import Publisher
from config.settings import GROQ_API_KEY

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, bot):
        self.scheduler = AsyncIOScheduler()
        self.bot = bot
        self.publisher = Publisher(bot)
        self.ai_processor = AIProcessor()
        logger.info("Scheduler инициализирован")

    def start(self):

        logger.info("Запуск планировщика задач")

        self.scheduler.add_job(
            self.check_rss_sources,
            IntervalTrigger(seconds=1800),
            id='rss_checker',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Задача check_rss_sources добавлена в планировщик")

        self.scheduler.add_job(
            self.publish_scheduled_posts,
            IntervalTrigger(seconds=60),
            id='post_publisher',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Задача publish_scheduled_posts добавлена в планировщик")

        self.scheduler.start()
        logger.info("Планировщик запущен")

    async def check_rss_sources(self):

        logger.info("=== НАЧАЛО ПРОВЕРКИ RSS-ИСТОЧНИКОВ ===")
        start_time = datetime.utcnow()

        db = SessionLocal()
        try:
            sources = get_active_sources(db)
            logger.info(f"Найдено активных RSS-источников: {len(sources)}")

            if not sources:
                logger.info("Нет активных RSS-источников для проверки")
                return

            parser = RSSParser()
            async with parser:
                processed_count = 0
                for source in sources:
                    try:
                        logger.info(f"Проверка источника: {source.name} ({source.url})")
                        entries = await parser.parse_feed(source.url, source.last_guid)

                        if entries:
                            logger.info(f"Найдено новых записей в {source.name}: {len(entries)}")
                            await self._process_new_entries(entries, source, db)
                            processed_count += len(entries)
                        else:
                            logger.debug(f"В источнике {source.name} нет новых записей")


                        update_source_check(db, source.id, error=False)

                    except Exception as e:
                        logger.error(f"Ошибка при обработке источника {source.name}: {str(e)}", exc_info=True)
                        update_source_check(db, source.id, error=True)

                logger.info(f"Обработано новых записей всего: {processed_count}")

        except Exception as e:
            logger.critical(f"Критическая ошибка в check_rss_sources: {str(e)}", exc_info=True)
        finally:
            db.close()
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"=== ПРОВЕРКА RSS-ИСТОЧНИКОВ ЗАВЕРШЕНА (время выполнения: {execution_time:.2f} сек) ===")

    async def _process_new_entries(self, entries: List[Dict], source, db):

        channel = source.channel
        if not channel.is_active:
            logger.info(f"Канал {channel.channel_name} неактивен, пропускаем обработку")
            return

        for entry in entries[:2]:
            try:
                logger.info(f"Обработка записи: {entry.get('title', '')}")

                # обработка контента с помощью AI
                processed_content = await self.ai_processor.process_content(
                    entry,
                    {
                        'ai_model': channel.ai_model,
                        'ai_prompt': channel.ai_prompt,
                        'topic': channel.topic
                    }
                )

                logger.debug(f"Обработанный контент: {processed_content[:100]}...")

                # проверка на дубликаты
                post_hash = generate_post_hash(entry['title'] + " " + entry['content'])
                existing_post = db.query(Post).filter(
                    Post.channel_id == channel.id,
                    Post.hash == post_hash
                ).first()

                if existing_post:
                    logger.info(f"Дубликат поста обнаружен и пропущен: {entry.get('title', '')}")
                    continue


                last_post = db.query(Post).filter(
                    Post.channel_id == channel.id
                ).order_by(Post.scheduled_time.desc()).first()

                if last_post and last_post.scheduled_time > datetime.utcnow():
                    next_time = last_post.scheduled_time + timedelta(seconds=channel.post_interval)
                else:
                    next_time = datetime.utcnow() + timedelta(minutes=5)


                new_post = create_post(
                    db, channel.id, source.url,
                    entry['title'], entry['content'],
                    processed_content, entry.get('media', []),
                    next_time
                )

                if new_post:
                    logger.info(
                        f"Создан пост ID {new_post.id} для канала {channel.channel_name}, запланирован на {next_time}")
                else:
                    logger.warning("Не удалось создать пост (возможно, дубликат)")

            except Exception as e:
                logger.error(f"Ошибка при обработке записи '{entry.get('title', '')}': {str(e)}", exc_info=True)
                continue

    async def publish_scheduled_posts(self):

        logger.info("=== НАЧАЛО ПУБЛИКАЦИИ ЗАПЛАНИРОВАННЫХ ПОСТОВ ===")
        start_time = datetime.utcnow()

        db = SessionLocal()
        try:
            posts = get_pending_posts(db)
            logger.info(f"Найдено постов для публикации: {len(posts)}")

            published_count = 0
            failed_count = 0

            for post in posts:
                try:
                    channel = post.channel
                    if not channel.is_active:
                        logger.info(f"Канал {channel.channel_name} неактивен, пост {post.id} пропущен")
                        continue

                    logger.info(f"Публикация поста ID {post.id} в канал {channel.channel_name}")

                    if channel.moderation_mode:
                        logger.info(
                            f"Канал {channel.channel_name} в режиме модерации, пост {post.id} отправлен на модерацию")
                        update_post_status(db, post.id, "moderation")
                        continue


                    message_id = await self.publisher.publish_post(
                        channel.channel_id,
                        post.processed_content,
                        post.media_urls
                    )

                    if message_id:
                        update_post_status(db, post.id, "published", message_id)
                        published_count += 1
                        logger.info(f"Пост {post.id} успешно опубликован с message_id={message_id}")
                    else:
                        update_post_status(db, post.id, "failed")
                        failed_count += 1
                        logger.error(f"Не удалось опубликовать пост {post.id}")


                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Ошибка при публикации поста {post.id}: {str(e)}", exc_info=True)
                    update_post_status(db, post.id, "failed")
                    failed_count += 1

            logger.info(f"Публикация завершена: успешно {published_count}, неудачно {failed_count}")

        except Exception as e:
            logger.critical(f"Критическая ошибка в publish_scheduled_posts: {str(e)}", exc_info=True)
        finally:
            db.close()
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                f"=== ПУБЛИКАЦИЯ ЗАПЛАНИРОВАННЫХ ПОСТОВ ЗАВЕРШЕНА (время выполнения: {execution_time:.2f} сек) ===")

    def stop(self):

        logger.info("Остановка планировщика задач")
        self.scheduler.shutdown()
        logger.info("Планировщик остановлен")
