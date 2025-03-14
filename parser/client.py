import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import SQLiteSession
from sqlalchemy import select
from database.models import Account, Proxy
from loguru import logger

async def create_client(account: Account, db=None) -> TelegramClient:
    session_path = f"sessions/{account.phone_number}"
    os.makedirs(os.path.dirname(session_path), exist_ok=True)

    # Создаём сессию
    session = SQLiteSession(session_path)

    # Получаем прокси, если он привязан
    proxy = None
    if account.proxy_id and db:
        result = await db.execute(select(Proxy).where(Proxy.id == account.proxy_id))
        proxy_data = result.scalars().first()
        if proxy_data:
            proxy = (proxy_data.type, proxy_data.host, proxy_data.port, proxy_data.user, proxy_data.password)

    # Создаём клиента Telegram с настройкой тайм-аута
    client = TelegramClient(
        session=session,
        api_id=account.api_id,
        api_hash=account.api_hash,
        proxy=proxy,
        timeout=30,  # Устанавливаем тайм-аут через параметр timeout (в секундах)
        connection_retries=3  # Количество попыток повторного подключения
    )
    
    # Подключаемся
    await client.connect()
    return client

async def authorize_client(client: TelegramClient, phone_number: str, db) -> dict:
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result = await client.send_code_request(phone_number)
            return {"status": "code_required", "phone_code_hash": result.phone_code_hash}
        return {"status": "authorized"}
    except Exception as e:
        logger.error(f"Ошибка авторизации клиента: {e}")
        return {"status": "error", "message": str(e)}

async def complete_authorization(client: TelegramClient, phone_number: str, code: str = None, phone_code_hash: str = None, password: str = None) -> dict:
    try:
        if code:
            await client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
        elif password:
            await client.sign_in(password=password)
        return {"status": "authorized"}
    except Exception as e:
        if "Two" in str(e):
            return {"status": "password_required"}
        logger.error(f"Ошибка завершения авторизации: {e}")
        return {"status": "error", "message": str(e)}