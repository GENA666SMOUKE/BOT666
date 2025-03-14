import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from aiohttp.client_exceptions import ClientConnectionError
from aiogram.types import FSInputFile
from io import BytesIO
from typing import List, Dict
from loguru import logger
from telethon import TelegramClient
from telethon.tl.types import PeerChannel, PeerUser, PeerChat, MessageMediaPhoto, MessageMediaDocument, DocumentAttributeVideo, DocumentAttributeAudio, DocumentAttributeSticker
from telethon.errors.rpcerrorlist import FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest
from aiogram import Bot
from database.models import TargetChat

# Множество для хранения обработанных сообщений
processed_messages = set()
active_parsers: Dict[int, Dict[str, asyncio.Task]] = {}
client_cache: Dict[int, TelegramClient] = {}

# Функция для извлечения имени канала из URL
def get_channel_name(target_chat: str) -> str:
    return target_chat.replace("https://t.me/", "").split("/")[0]

async def start_real_time_parsing(account, target_chat_id: str, bot: Bot, forward_chat_id: str, keywords=None, filter_enabled=False):
    # Проверяем, есть ли уже клиент для этого аккаунта в кэше
    if account.id not in client_cache:
        session_name = f"sessions/{account.phone_number}"
        client = TelegramClient(
            session=session_name,
            api_id=account.api_id,
            api_hash=account.api_hash
        )
        try:
            await client.start()
            if not await client.is_user_authorized():
                logger.warning(f"Аккаунт {account.phone_number} не авторизован. Требуется повторная авторизация.")
                raise ValueError("Аккаунт не авторизован")
            client_cache[account.id] = client
        except Exception as e:
            logger.error(f"Ошибка при запуске клиента для аккаунта ID {account.id}: {e}")
            raise
    else:
        client = client_cache[account.id]

    try:
        entity = await client.get_entity(target_chat_id)
        if isinstance(entity, PeerChannel):
            chat_id = int(f"-100{entity.id}")
        elif isinstance(entity, PeerChat):
            chat_id = -entity.id
        elif isinstance(entity, PeerUser):
            chat_id = entity.id
        else:
            chat_id = int(entity.id) if hasattr(entity, 'id') and entity.id else None
        if chat_id is None:
            raise ValueError(f"Не удалось определить chat_id для {target_chat_id}")
        logger.info(f"Чат {target_chat_id} (ID: {chat_id})")
    except ValueError as e:
        logger.info(f"Чат {target_chat_id} недоступен, пытаемся присоединиться...")
        try:
            await client(JoinChannelRequest(target_chat_id))
            entity = await client.get_entity(target_chat_id)
            if isinstance(entity, PeerChannel):
                chat_id = int(f"-100{entity.id}")
            elif isinstance(entity, PeerChat):
                chat_id = -entity.id
            elif isinstance(entity, PeerUser):
                chat_id = entity.id
            else:
                chat_id = int(entity.id) if hasattr(entity, 'id') and entity.id else None
            if chat_id is None:
                raise ValueError(f"Не удалось определить chat_id после присоединения для {target_chat_id}")
            logger.info(f"Аккаунт успешно присоединился к чату {target_chat_id}")
        except Exception as e:
            logger.error(f"Ошибка при присоединении к чату {target_chat_id}: {e}")
            raise

    # Создаём объект TargetChat для передачи в задачу
    target_chat = TargetChat(id=0, chat_id=chat_id, title=target_chat_id)

    logger.info(f"Запущено отслеживание чата {target_chat_id} в реальном времени")
    task = asyncio.create_task(real_time_parsing_task(client, account.id, target_chat, bot, forward_chat_id, keywords, filter_enabled))
    if account.id not in active_parsers:
        active_parsers[account.id] = {}
    active_parsers[account.id][target_chat_id] = task
    logger.info(f"Клиент для аккаунта ID {account.id} запущен в фоновой задаче")

async def real_time_parsing_task(client: TelegramClient, account_id: int, target_chat: TargetChat, bot: Bot, forward_chat_id: int, keywords: List[str], filter_enabled: bool):
    logger.info(f"Чат {target_chat.title} (ID: {target_chat.chat_id})")
    logger.info(f"Запущено отслеживание чата {target_chat.title} в реальном времени")

    # Кэшируем клиента
    client_cache[account_id] = client

    # Подключаемся и управляем соединением вручную
    async def ensure_connected():
        if not client.is_connected():
            logger.info(f"Переподключение клиента для аккаунта ID {account_id}")
            await client.connect()
        if not await client.is_user_authorized():
            logger.error(f"Клиент для аккаунта ID {account_id} не авторизован")
            return False
        return True

    if not await ensure_connected():
        return

    while True:  # Бесконечный цикл для постоянного мониторинга
        async for message in client.iter_messages(target_chat.chat_id, limit=10):
            if message.id in processed_messages:
                continue
            processed_messages.add(message.id)
            logger.info(f"Обработка сообщения {message.id} для пересылки в {forward_chat_id}")

            # Проверяем фильтр по ключевым словам
            message_text = message.text or ""
            if filter_enabled and keywords:
                if not any(keyword.lower() in message_text.lower() for keyword in keywords):
                    logger.info(f"Сообщение {message.id} пропущено, так как не содержит ключевые слова: {keywords}")
                    continue

            # Исходный текст оставляем без изменений
            formatted_text = message_text

            # Формируем подпись
            signature = f"👍 Скопировано из [{target_chat.title}](https://t.me/{target_chat.title.replace(' ', '_')})"

            # Экранируем только подпись для MarkdownV2
            special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for char in special_chars:
                signature = signature.replace(char, f'\\{char}')

            # Добавляем подпись в конец с переносом строки
            formatted_text = f"{formatted_text}\n\n{signature}" if formatted_text else signature

            # Функция отправки с повторными попытками
            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_photo_with_retry():
                media_file.seek(0)
                return await bot.send_photo(
                    chat_id=forward_chat_id,
                    photo=FSInputFile(media_file, filename=f"photo_{message.id}.jpg"),
                    caption=formatted_text,
                    parse_mode="MarkdownV2",
                    disable_notification=False
                )

            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_video_with_retry():
                media_file.seek(0)
                return await bot.send_video(
                    chat_id=forward_chat_id,
                    video=FSInputFile(media_file, filename=f"video_{message.id}.mp4"),
                    caption=formatted_text,
                    parse_mode="MarkdownV2",
                    disable_notification=False
                )

            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_audio_with_retry():
                media_file.seek(0)
                return await bot.send_audio(
                    chat_id=forward_chat_id,
                    audio=FSInputFile(media_file, filename=f"audio_{message.id}.mp3"),
                    caption=formatted_text,
                    parse_mode="MarkdownV2",
                    disable_notification=False
                )

            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_document_with_retry():
                media_file.seek(0)
                return await bot.send_document(
                    chat_id=forward_chat_id,
                    document=FSInputFile(media_file, filename=f"document_{message.id}"),
                    caption=formatted_text,
                    parse_mode="MarkdownV2",
                    disable_notification=False
                )

            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_sticker_with_retry():
                media_file.seek(0)
                return await bot.send_sticker(
                    chat_id=forward_chat_id,
                    sticker=FSInputFile(media_file, filename=f"sticker_{message.id}.webp")
                )

            @retry(
                stop=stop_after_attempt(10),
                wait=wait_exponential(multiplier=1, min=2, max=30),
                retry=retry_if_exception_type(ClientConnectionError),
                before_sleep=lambda retry_state: logger.info(f"Повторная попытка отправки сообщения {message.id}, попытка {retry_state.attempt_number}")
            )
            async def send_message_with_retry():
                return await bot.send_message(
                    chat_id=forward_chat_id,
                    text=formatted_text,
                    parse_mode="MarkdownV2",
                    disable_notification=False,
                    disable_web_page_preview=False
                )

            # Отправляем сообщение или медиа с подписью
            try:
                if message.media:
                    media_file = await client.download_media(message.media, file=BytesIO())
                    media_file.seek(0)
                    if not await ensure_connected():
                        continue
                    if isinstance(message.media, MessageMediaPhoto):
                        await send_photo_with_retry()
                        logger.info(f"Фото {message.id} отправлено с уведомлением")
                    elif isinstance(message.media, MessageMediaDocument):
                        # Проверяем тип документа через атрибуты
                        attributes = message.media.document.attributes if message.media.document else []
                        is_sticker = any(isinstance(attr, DocumentAttributeSticker) for attr in attributes)
                        is_video = any(isinstance(attr, DocumentAttributeVideo) for attr in attributes)
                        is_audio = any(isinstance(attr, DocumentAttributeAudio) for attr in attributes)

                        if is_sticker:
                            await send_sticker_with_retry()
                            logger.info(f"Стикер {message.id} отправлен")
                        elif is_video:
                            await send_video_with_retry()
                            logger.info(f"Видео {message.id} отправлено с уведомлением")
                        elif is_audio:
                            await send_audio_with_retry()
                            logger.info(f"Аудио {message.id} отправлено с уведомлением")
                        else:
                            await send_document_with_retry()
                            logger.info(f"Документ {message.id} отправлен с уведомлением")
                else:
                    if not await ensure_connected():
                        continue
                    await send_message_with_retry()
                logger.info(f"Сообщение {message.id} отправлено в {forward_chat_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения {message.id}: {str(e)}")

        # Задержка перед следующей итерацией
        await asyncio.sleep(5)

    logger.info(f"Клиент для аккаунта ID {account_id} запущен в фоновом режиме")

async def stop_parsing(account_id: int, target_chat_id: str):
    logger.info(f"Остановка парсинга для аккаунта ID {account_id} и чата {target_chat_id}")
    if account_id in active_parsers and target_chat_id in active_parsers[account_id]:
        task = active_parsers[account_id].pop(target_chat_id)
        task.cancel()
        logger.info(f"Парсинг для чата {target_chat_id} остановлен")
    
        # Если больше нет задач для этого аккаунта, закрываем клиент
        if not active_parsers[account_id]:
            del active_parsers[account_id]
            if account_id in client_cache:
                client = client_cache.pop(account_id)
                await client.disconnect()
                logger.info(f"Клиент для аккаунта ID {account_id} отключён")
    else:
        logger.warning(f"Нет активного парсинга для аккаунта ID {account_id} и чата {target_chat_id}")