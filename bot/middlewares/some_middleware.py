from aiogram import BaseMiddleware
from aiogram.types import Message
import logging

logger = logging.getLogger(__name__)

class SomeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        logger.info(f"Получено сообщение: {event.text}")
        return await handler(event, data)