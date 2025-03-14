import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.config import BOT_TOKEN
from bot.handlers import admin, parsing
# from bot.middlewares import SomeMiddleware  # Уже убрали ранее
from database.db import init_db
from proxy.manager import ProxyManager
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Регистрация middleware (убрали ранее)
# dp.message.middleware(SomeMiddleware())

# Регистрация обработчиков
dp.include_router(admin.router)
# dp.include_router(parsing.router)  # Закомментировано, пока нет router в parsing.py

# Инициализация ресурсов
async def init_resources():
    await init_db()
    await ProxyManager.load_proxies()  # Оставил await, как ты добавил

# Функция запуска
async def on_startup(_):
    """
    Функция вызывается при запуске бота.
    Аргумент _ нужен для совместимости с aiogram.
    """
    await init_resources()
    logger.info("Бот запущен")

# Регистрация startup
dp.startup.register(on_startup)

# Главная функция
async def main():
    logger.info(f"Токен бота: {BOT_TOKEN[:4]}... (скрыт для безопасности)")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
        raise

# Запуск бота
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("Бот завершил работу")