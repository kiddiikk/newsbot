from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from typing import Dict, Callable, List
import asyncio
import logging
from database.crud import *
from database.models import SessionLocal, Post, User
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

    def _moderation_keyboard(self, post_id: int):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve_{post_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{post_id}")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

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

        self.scheduler.add_job(
            self.check_expired_access,
            IntervalTrigger(seconds=3600),
            id='access_checker',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Задача check_expired_access добавлена в планировщик")

        # 👇 НОВОЕ: синхронизация подписок из gramkit каждые 5 минут
        self.scheduler.add_job(
            self.sync_subscriptions_from_gramkit,
            IntervalTrigger(seconds=300),
            id='subscription_sync',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Задача sync_subscriptions_from_gramkit добавлена в планировщик")

        self.scheduler.start()
        logger.info("Планировщик запущен")

    async def check_rss_sources(self):
        logger.info("=== НАЧАЛО ПРОВЕРКИ RSS-ИСТОЧНИКОВ ===")
        start_time = datetime.utcnow()

        from config.settings import ADMIN_IDS
        from database.crud import has_access

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
                        # 👇 ПРОВЕРКА ДОСТУПА
                        if not has_access(db, source.channel_id, ADMIN_IDS):
                            logger.info(f"Канал {source.channel.channel_name}: доступ закрыт, пропускаем")
                            continue

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

                # 👇 ГЕНЕРАЦИЯ КАРТИНКИ, ЕСЛИ ЕЁ НЕТ
                media = entry.get('media', [])
                if not media:
                    logger.info("Картинки нет, генерирую...")
                    image_prompt = await self.ai_processor.generate_image_prompt(entry.get('title', ''))
                    logger.info(f"Промпт для картинки: {image_prompt}")

                    from core.image_generator import generate_image
                    generated_path = generate_image(image_prompt)
                    if generated_path:
                        media = [generated_path]
                        logger.info(f"Картинка сгенерирована: {generated_path}")

                # проверка на дубликаты
                # === ДЕДУП ===
                # 1. По GUID от RSS (самый надёжный)
                guid = entry.get('guid') or entry.get('link') or entry.get('id')
                if guid:
                    existing_by_guid = db.query(Post).filter(
                        Post.channel_id == channel.id,
                        Post.source_url == guid
                    ).first()
                    if existing_by_guid:
                        logger.info(f"Дубликат по GUID пропущен: {entry.get('title', '')}")
                        continue

                # 2. По нормализованному title
                import re
                def normalize_title(t: str) -> str:
                    return re.sub(r'\W+', '', t.lower())[:80]

                norm_title = normalize_title(entry.get('title', ''))
                if norm_title:
                    existing_by_title = db.query(Post).filter(
                        Post.channel_id == channel.id,
                        Post.original_title.like(f'%{norm_title[:40]}%')
                    ).first()
                    if existing_by_title:
                        logger.info(f"Дубликат по title пропущен: {entry.get('title', '')}")
                        continue

                # 3. По hash (страховка)
                post_hash = generate_post_hash(entry['title'] + " " + entry['content'])
                existing_post = db.query(Post).filter(
                    Post.channel_id == channel.id,
                    Post.hash == post_hash
                ).first()
                if existing_post:
                    logger.info(f"Дубликат по hash пропущен: {entry.get('title', '')}")
                    continue
                # === КОНЕЦ ДЕДУПА ===

                last_post = db.query(Post).filter(
                    Post.channel_id == channel.id
                ).order_by(Post.scheduled_time.desc()).first()

                if last_post and last_post.scheduled_time > datetime.utcnow():
                    next_time = last_post.scheduled_time + timedelta(seconds=channel.post_interval)
                else:
                    next_time = datetime.utcnow() + timedelta(minutes=5)

                new_post = create_post(
                    db, channel.id, entry.get('guid', entry.get('link', '')),
                    entry['title'], entry['content'],
                    processed_content, media,
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

        from config.settings import ADMIN_IDS
        from database.crud import has_access

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

                    # 👇 ПРОВЕРКА ДОСТУПА
                    if not has_access(db, channel.id, ADMIN_IDS):
                        logger.info(f"Канал {channel.channel_name}: доступ закрыт, пост {post.id} пропущен")
                        continue

                    logger.info(f"Публикация поста ID {post.id} в канал {channel.channel_name}")

                    if channel.moderation_mode:
                        logger.info(f"Канал {channel.channel_name} в режиме модерации, отправляю пост {post.id} владельцу")
                        update_post_status(db, post.id, "moderation")

                        # 👇 ОТПРАВЛЯЕМ ПОСТ ВЛАДЕЛЬЦУ НА ПРОВЕРКУ
                        try:
                            await self.bot.send_message(
                                channel.owner.telegram_id,
                                f"📝 <b>Пост на модерацию</b>\n\n"
                                f"Канал: <b>{channel.channel_name}</b>\n\n"
                                f"{post.processed_content}",
                                parse_mode="HTML",
                                reply_markup=self._moderation_keyboard(post.id)
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить пост на модерацию: {e}")
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

    async def check_expired_access(self):
        """Уведомляет клиентов об окончании пробного периода"""
        from config.settings import ADMIN_IDS
        from database.models import Channel

        logger.info("=== ПРОВЕРКА ИСТЁКШИХ ПРОБНЫХ ПЕРИОДОВ ===")
        db = SessionLocal()
        try:
            now = datetime.utcnow()

            expired_trials = db.query(Channel).filter(
                Channel.trial_until < now,
                Channel.trial_until > now - timedelta(hours=2),
                Channel.trial_notified == False
            ).all()

            logger.info(f"Найдено истёкших пробных: {len(expired_trials)}")

            for channel in expired_trials:
                try:
                    owner = channel.owner
                    if owner.telegram_id in ADMIN_IDS:
                        continue

                    await self.bot.send_message(
                        owner.telegram_id,
                        f"⏰ Пробный период для канала «{channel.channel_name}» закончился.\n\n"
                        f"Чтобы публикации продолжились, оформите подписку.\n"
                        f"Нажмите /start → 💎 Подписка"
                    )
                    channel.trial_notified = True
                    db.commit()
                    logger.info(f"Уведомление отправлено: {owner.telegram_id}")
                except Exception as e:
                    logger.error(f"Не удалось уведомить {channel.owner.telegram_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в check_expired_access: {e}", exc_info=True)
        finally:
            db.close()

    # ============================================================
    # 👇 НОВЫЙ МЕТОД: Синхронизация подписок из gramkit
    # ============================================================
    async def sync_subscriptions_from_gramkit(self):
        """Синхронизировать подписки из gramkit (subscriptions) → newsbot (users.subscription_until)."""
        from sqlalchemy import text

        logger.info("=== СИНХРОНИЗАЦИЯ ПОДПИСОК ИЗ GRAMKIT ===")
        db = SessionLocal()
        try:
            # Получить активные подписки из gramkit
            rows = db.execute(text("""
                SELECT u.telegram_id, s.product_id, s.end_date
                FROM subscriptions s
                JOIN users u ON s.user_id = u.id
                WHERE s.status IN ('ACTIVE', 'CANCELED')
                  AND s.end_date > NOW()
            """)).fetchall()

            logger.info(f"Найдено активных подписок в gramkit: {len(rows)}")

            plan_mapping = {
                "FEELIT_START": "start",
                "FEELIT_PRO": "pro",
                "FEELIT_BUSINESS": "business",
                # legacy — на случай старых подписок
                "WEEK_SUB_V3": "start",
                "MONTH_SUB_V3": "pro",
                "YEAR_SUB_V3": "business",
                "WEEK_SUB_V2": "start",
                "MONTH_SUB_V2": "pro",
                "YEAR_SUB_V2": "business",
                "WEEK_SUB": "start",
                "MONTH_SUB": "pro",
                "YEAR_SUB": "business",
            }

            updated = 0
            for telegram_id, product_id, end_date in rows:
                plan_key = plan_mapping.get(product_id)
                if not plan_key:
                    logger.debug(f"Неизвестный product_id: {product_id}")
                    continue

                user = db.query(User).filter(User.telegram_id == telegram_id).first()
                if not user:
                    logger.warning(f"Юзер с tg={telegram_id} не найден в newsbot")
                    continue

                current_until = user.subscription_until
                current_plan = user.subscription_plan

                need_update = (
                    current_until is None
                    or end_date > current_until
                    or current_plan != plan_key
                )

                if need_update:
                    user.subscription_until = end_date
                    user.subscription_plan = plan_key
                    updated += 1
                    logger.info(
                        f"Обновлена подписка: tg={telegram_id}, plan={plan_key}, until={end_date}"
                    )

            if updated > 0:
                db.commit()
                logger.info(f"✅ Обновлено подписок: {updated}")
            else:
                logger.info("Подписки не требуют обновления")

        except Exception as e:
            logger.error(f"Ошибка синхронизации подписок: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
            logger.info("=== СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА ===")

    def stop(self):
        logger.info("Остановка планировщика задач")
        self.scheduler.shutdown()
        logger.info("Планировщик остановлен")
