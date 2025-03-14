import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from database.db import init_db, get_db
from bot.handlers.admin import router as admin_router
from parser.parser import active_parsers, stop_parsing

# Установка кодировки UTF-8
import locale
locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')  # Устанавливаем локаль с поддержкой UTF-8

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from bot.config import BOT_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота с увеличенным тайм-аутом и поддержкой прокси (если настроен)
bot = Bot(token=BOT_TOKEN, request_timeout=30)  # Тайм-аут увеличен до 30 секунд
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(admin_router)

async def on_startup(_):
    """Функция, выполняемая при старте бота."""
    try:
        await init_db()  # Инициализация базы данных
        logger.info("База данных инициализирована и таблицы созданы")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise
    logger.info("Бот запущен...")

async def on_shutdown(_):
    """Функция, выполняемая при остановке бота."""
    logger.info("Начало завершения работы бота...")
    # Остановка всех активных парсеров
    for account_id in list(active_parsers.keys()):
        for chat_id in list(active_parsers[account_id].keys()):
            try:
                await stop_parsing(account_id, chat_id)
                logger.info(f"Остановлен парсинг для аккаунта {account_id} и чата {chat_id}")
            except Exception as e:
                logger.error(f"Ошибка при остановке парсинга для аккаунта {account_id} и чата {chat_id}: {e}")
    await bot.session.close()  # Закрытие сессии бота
    logger.info("Сессия бота закрыта")

async def main():
    """Основная функция запуска бота."""
    logger.info(f"Токен бота: {BOT_TOKEN[:4]}... (скрыт для безопасности)")
    try:
        # Регистрация обработчиков старта и остановки
        dp.startup.register(on_startup)
        dp.shutdown.register(on_shutdown)

        # Запуск бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
        raise
    finally:
        logger.info("Бот завершил работу")

if __name__ == "__main__":
    asyncio.run(main())