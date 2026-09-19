import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config.settings import BOT_TOKEN, GROQ_API_KEY
from bot.handlers import router
from admin.panel import admin_router
from core.scheduler import Scheduler
from database.models import engine, Base
from sqlalchemy import text

# Настройка логирования с поддержкой UTF-8
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger(__name__)


async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command='/start', description='🚀 Запустить/перезапустить бота'),
        BotCommand(command='/my_channels', description='📊 Мои каналы'),
        BotCommand(command='/add_channel', description='➕ Добавить новый канал'),
        BotCommand(command='/admin', description='👑 Панель администратора')
    ]
    await bot.set_my_commands(main_menu_commands)


def migrate_db():
    """Безопасная миграция базы данных (работает и с SQLite, и с PostgreSQL)"""
    logger.info("🔍 Проверка необходимости миграции базы данных...")

    from config.settings import DATABASE_URL

    with engine.connect() as conn:
        try:
            # 👇 Определяем тип базы
            is_postgres = DATABASE_URL.startswith("postgresql")

            if is_postgres:
                # PostgreSQL: проверяем через information_schema
                result = conn.execute(text("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'posts' AND column_name = 'hash'
                """))
            else:
                # SQLite: проверяем через pragma_table_info
                result = conn.execute(text("""
                    SELECT name FROM pragma_table_info('posts') WHERE name = 'hash'
                """))

            if not result.fetchone():
                logger.info("🔧 Столбец 'hash' отсутствует в таблице posts. Выполняем миграцию...")
                conn.execute(text("ALTER TABLE posts ADD COLUMN hash TEXT"))
                conn.commit()
                logger.info("✅ Миграция успешна: добавлен столбец hash в таблицу posts")
            else:
                logger.info("✅ Столбец 'hash' уже существует в таблице posts, миграция не требуется")

        except Exception as e:
            logger.error(f"❌ Ошибка при миграции базы данных: {str(e)}", exc_info=True)
            logger.info("🔧 Попытка восстановления структуры базы данных...")
            Base.metadata.create_all(engine)
            logger.info("✅ Структура базы данных восстановлена")


async def main():
    if not BOT_TOKEN:
        logger.critical("❌ BOT_TOKEN не найден! Проверьте ваш .env файл.")
        return

    if not GROQ_API_KEY:
        logger.critical("❌ GROQ_API_KEY не найден! Проверьте ваш .env файл.")
        return

    migrate_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(router)
    dp.include_router(admin_router)

    await set_main_menu(bot)

    scheduler = Scheduler(bot)
    scheduler.start()

    try:
        logger.info("✅ Бот запущен и готов к работе")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.stop()
        await bot.session.close()
        logger.info("🛑 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Остановка по команде пользователя")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при запуске бота: {str(e)}", exc_info=True)
