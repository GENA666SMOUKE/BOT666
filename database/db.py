from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from contextlib import asynccontextmanager
import logging
from sqlalchemy.sql import text

logger = logging.getLogger(__name__)

# Используем переменную окружения из config.py
from bot.config import DATABASE_URL
logger.info(f"Сырая строка подключения: {repr(DATABASE_URL)}")

# Проверяем, содержит ли строка подключения некорректные байты
try:
    encoded = DATABASE_URL.encode('utf-8')
    decoded = encoded.decode('utf-8')
    logger.info(f"Строка подключения декодируется как UTF-8: {decoded}")
except UnicodeEncodeError as e:
    logger.error(f"Ошибка кодировки в DATABASE_URL: {e}")
    logger.error(f"Сырые байты: {repr(DATABASE_URL.encode('utf-8', errors='replace'))}")
    raise
except UnicodeDecodeError as e:
    logger.error(f"Ошибка декодировки в DATABASE_URL: {e}")
    logger.error(f"Сырые байты: {repr(DATABASE_URL.encode('utf-8', errors='replace'))}")
    raise

# Создаём Base здесь
Base = declarative_base()

# Создаём асинхронный движок
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession
)

# Асинхронный контекстный менеджер для сессий
@asynccontextmanager
async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

# Асинхронная инициализация базы данных
async def init_db():
    # Импортируем модели здесь, чтобы избежать циклического импорта
    from .models import Settings, KeywordList, KeywordFilter, Account, Proxy, TargetChat
    async with engine.begin() as conn:
        # Проверяем, существуют ли таблицы, и создаём только если их нет
        for table in Base.metadata.tables.values():
            exists = await conn.run_sync(lambda conn_sync: conn_sync.dialect.has_table(conn_sync, table.name))
            if not exists:
                await conn.run_sync(lambda conn_sync: table.create(conn_sync))
                logger.info(f"Таблица {table.name} создана")
        logger.info("Проверка и создание таблиц завершены")
    
    # Проверяем и добавляем начальные настройки
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(text("SELECT 1 FROM settings LIMIT 1"))
            if not result.scalar():
                db.add(Settings(forward_chat_id="-1002391590780"))
                await db.commit()
                logger.info("Начальные настройки добавлены в базу данных")
        except Exception as e:
            logger.error(f"Ошибка при инициализации настроек: {e}")
            raise