import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.config import BOT_TOKEN
from bot.handlers.admin import router as admin_router
from database.db import init_db
from parser.parser import active_parsers, stop_parsing

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, request_timeout=30)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(admin_router)

# Функция запуска
async def on_startup(_):
    """Функция, выполняемая при старте бота."""
    try:
        await init_db()
        logger.info("База данных инициализирована и таблицы созданы")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise
    logger.info("Бот запущен...")

# Функция остановки
async def on_shutdown(_):
    """Функция, выполняемая при остановке бота."""
    logger.info("Начало завершения работы бота...")
    for account_id in list(active_parsers.keys()):
        for chat_id in list(active_parsers[account_id].keys()):
            try:
                await stop_parsing(account_id, chat_id)
                logger.info(f"Остановлен парсинг для аккаунта {account_id} и чата {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка при остановке парсинга для аккаунта {account_id} и чата {chat_id}: {e}")
    await bot.session.close()
    logger.info("Сессия бота закрыта")

# Регистрация startup и shutdown
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

# Главная функция
async def main():
    logger.info(f"Токен бота: {BOT_TOKEN[:4]}... (скрыт для безопасности)")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
        raise
    finally:
        logger.info("Бот завершил работу")

if __name__ == "__main__":
    asyncio.run(main())