import logging
import os
import asyncio
from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_db
from parser.client import create_client, authorize_client, complete_authorization
from parser.parser import start_real_time_parsing, stop_parsing, active_parsers
from sqlalchemy import select, text
from database.models import Account, Proxy, TargetChat, Settings, KeywordFilter, KeywordList
from loguru import logger

router = Router()
logger = logging.getLogger(__name__)

# Определение состояний для FSM
class AddAccountForm(StatesGroup):
    phone_number = State()
    api_id = State()
    api_hash = State()
    code = State()
    password = State()

class AddProxyForm(StatesGroup):
    proxy_data = State()

class AddTargetChatForm(StatesGroup):
    chat_id = State()
    title = State()

class SetForwardChatForm(StatesGroup):
    chat_id = State()

class AddKeywordListForm(StatesGroup):
    name = State()
    keywords = State()

class EditKeywordListForm(StatesGroup):
    list_id = State()
    name = State()
    keywords = State()

# Кнопки для выбора аккаунта или прокси
def get_account_keyboard(accounts, action: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for account in accounts:
        if isinstance(account, dict) and "id" in account:
            text = f"ID: {account['id']}"
            if action.startswith("delete"):
                text = f"ID: {account['id']} [Удалить]"
        else:
            text = f"ID: {account.id}"
            if action.startswith("delete"):
                text = f"ID: {account.id} [Удалить]"
        button = InlineKeyboardButton(
            text=text,
            callback_data=f"{action}:{account.id}"
        )
        keyboard.inline_keyboard.append([button])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return keyboard

# Кнопки для выбора целевых чатов
def get_target_chat_keyboard(chats, action: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for chat in chats:
        if isinstance(chat, dict) and "id" in chat:
            text = f"{chat.get('title', chat.get('chat_id'))} (ID: {chat['id']})"
            if action.startswith("delete"):
                text = f"{chat.get('title', chat.get('chat_id'))} (ID: {chat['id']}) [Удалить]"
        else:
            text = f"{chat.title or chat.chat_id} (ID: {chat.id})"
            if action.startswith("delete"):
                text = f"{chat.title or chat.chat_id} (ID: {chat.id}) [Удалить]"
        button = InlineKeyboardButton(
            text=text,
            callback_data=f"{action}:{chat.id}"
        )
        keyboard.inline_keyboard.append([button])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return keyboard

# Кнопки для выбора активных парсеров
def get_active_parsers_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for account_id in active_parsers.keys():
        for target_chat_id in active_parsers[account_id].keys():
            text = f"Аккаунт ID: {account_id}, Чат: {target_chat_id}"
            button = InlineKeyboardButton(
                text=text,
                callback_data=f"stop_parsing:{account_id}:{target_chat_id}"
            )
            keyboard.inline_keyboard.append([button])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return keyboard

# Кнопки для выбора списка ключевых слов
async def get_keyword_list_keyboard(lists, action: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for keyword_list in lists:
        # Явно получаем значение enabled через запрос
        async with get_db() as db:
            result = await db.execute(select(KeywordList.enabled).where(KeywordList.id == keyword_list.id))
            enabled = result.scalar() or False
        status_icon = "🟢" if enabled else "🔴"
        text = f"{status_icon} {keyword_list.name} (ID: {keyword_list.id})"
        if action.startswith("delete"):
            text = f"{status_icon} {keyword_list.name} (ID: {keyword_list.id}) [Удалить]"
        elif action.startswith("toggle"):
            text = f"{status_icon} {keyword_list.name} (ID: {keyword_list.id}) [{'Вкл' if enabled else 'Выкл'}]"
        elif action.startswith("edit"):
            text = f"{status_icon} {keyword_list.name} (ID: {keyword_list.id}) [Редактировать]"
        button = InlineKeyboardButton(
            text=text,
            callback_data=f"{action}:{keyword_list.id}"
        )
        keyboard.inline_keyboard.append([button])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_keyword_menu")])
    return keyboard

# Подменю управления аккаунтами
def get_accounts_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Добавить аккаунт", callback_data="add_account")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="list_accounts")],
        [InlineKeyboardButton(text="❌ Удалить аккаунт", callback_data="delete_account")],
        [InlineKeyboardButton(text="✅ Проверить аккаунт", callback_data="check_account")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    return keyboard

# Подменю управления прокси
def get_proxy_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Добавить прокси", callback_data="add_proxy")],
        [InlineKeyboardButton(text="📋 Список прокси", callback_data="list_proxies")],
        [InlineKeyboardButton(text="❌ Удалить прокси", callback_data="delete_proxy")],
        [InlineKeyboardButton(text="🔗 Привязать прокси к аккаунту", callback_data="bind_proxy")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    return keyboard

# Подменю управления чатами
def get_chat_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Добавить целевой чат", callback_data="add_target_chat")],
        [InlineKeyboardButton(text="📋 Список целевых чатов", callback_data="list_target_chats")],
        [InlineKeyboardButton(text="❌ Удалить целевой чат", callback_data="delete_target_chat")],
        [InlineKeyboardButton(text="📥 Установить чат для пересылки", callback_data="set_forward_chat")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    return keyboard

# Подменю управления списками ключевых слов
def get_keyword_list_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Создать список", callback_data="add_keyword_list")],
        [InlineKeyboardButton(text="📋 Список списков", callback_data="list_keyword_lists")],
        [InlineKeyboardButton(text="✏️ Редактировать список", callback_data="edit_keyword_list")],
        [InlineKeyboardButton(text="❌ Удалить список", callback_data="delete_keyword_list")],
        [InlineKeyboardButton(text="🔄 Вкл/Выкл список", callback_data="toggle_keyword_list")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_parsing")]
    ])
    return keyboard

# Подменю управления парсингом
def get_parsing_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    # Показываем статус активных парсингов
    active_status = []
    if active_parsers:
        for account_id in active_parsers.keys():
            for target_chat_id in active_parsers[account_id].keys():
                active_status.append(f"Аккаунт ID: {account_id}, Чат: {target_chat_id}")
        if active_status:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🟢 Активные парсинги: {', '.join(active_status)}", callback_data="noop")])
        else:
            keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔴 Нет активных парсингов", callback_data="noop")])
    else:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔴 Нет активных парсингов", callback_data="noop")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="▶️ Запустить парсинг", callback_data="start_parsing")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⏹️ Остановить парсинг", callback_data="stop_parsing")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="📋 Управление списками слов", callback_data="keyword_list_menu")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔄 Вкл/Выкл фильтрацию", callback_data="toggle_filter")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return keyboard

# Главное меню
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Управление аккаунтами", callback_data="menu_accounts")],
        [InlineKeyboardButton(text="🌐 Управление прокси", callback_data="menu_proxy")],
        [InlineKeyboardButton(text="💬 Управление чатами", callback_data="menu_chats")],
        [InlineKeyboardButton(text="🔄 Управление парсингом", callback_data="menu_parsing")]
    ])
    return keyboard

# Стартовая команда /start
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info("Получено сообщение от пользователя")
    logger.info(f"Текст сообщения: {message.text}")
    async with get_db() as db:
        logger.info("Команда /start получена")
        await message.answer("Добро пожаловать! Выберите категорию:", reply_markup=get_main_keyboard())

# Обработчик нажатий на кнопки
@router.callback_query()
async def process_callback(callback: types.CallbackQuery, state: FSMContext, bot: Bot = None):
    async with get_db() as db:
        data = callback.data
        current_text = callback.message.text or ""
        current_markup = callback.message.reply_markup

        logger.info(f"Обрабатываем callback_data: {data} (начало обработки)")

        # Возврат к главному меню
        if data == "back_to_main":
            new_text = "Добро пожаловать! Выберите категорию:"
            new_markup = get_main_keyboard()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.clear()
            await callback.answer()
            return

        # Открытие подменю управления аккаунтами
        if data == "menu_accounts":
            new_text = "Управление аккаунтами:"
            new_markup = get_accounts_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Открытие подменю управления прокси
        if data == "menu_proxy":
            new_text = "Управление прокси:"
            new_markup = get_proxy_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Открытие подменю управления чатами
        if data == "menu_chats":
            new_text = "Управление чатами:"
            new_markup = get_chat_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Открытие подменю управления парсингом
        if data == "menu_parsing":
            new_text = "Управление парсингом:"
            new_markup = get_parsing_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Открытие подменю управления списками ключевых слов
        if data == "keyword_list_menu":
            new_text = "Управление списками ключевых слов:"
            new_markup = get_keyword_list_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Возврат к меню парсинга из меню ключевых слов
        if data == "back_to_keyword_menu":
            new_text = "Управление парсингом:"
            new_markup = get_parsing_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.clear()
            await callback.answer()
            return

        # Добавление списка ключевых слов
        if data == "add_keyword_list":
            new_text = "Введите название списка ключевых слов:"
            new_markup = get_keyword_list_menu()
            # Проверяем, отличается ли новое сообщение от текущего
            if callback.message.text != new_text or callback.message.reply_markup != new_markup:
                await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.set_state(AddKeywordListForm.name)
            await callback.answer()
            return

        # Список списков ключевых слов
        if data == "list_keyword_lists":
            async with get_db() as db:
                result = await db.execute(select(KeywordList))
                keyword_lists = result.scalars().all()
                if not keyword_lists:
                    new_text = "Список списков ключевых слов пуст."
                    new_markup = get_keyword_list_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    response = "Списки ключевых слов:\n"
                    for keyword_list in keyword_lists:
                        # Явно получаем enabled через запрос
                        result = await db.execute(select(KeywordList.enabled).where(KeywordList.id == keyword_list.id))
                        enabled = result.scalar() or False
                        result = await db.execute(select(KeywordFilter).where(KeywordFilter.keyword_list_id == keyword_list.id))
                        keywords = result.scalars().all()
                        keyword_str = ", ".join([kw.keyword for kw in keywords]) if keywords else "Пусто"
                        response += f"🟢 ID: {keyword_list.id}, Название: {keyword_list.name}, Статус: {'Вкл' if enabled else 'Выкл'}, Слова: {keyword_str}\n"
                    new_text = response
                    new_markup = get_keyword_list_menu()
                    # Проверяем, изменился ли текст или разметка
                    if callback.message.text != new_text or callback.message.reply_markup != new_markup:
                        await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Редактирование списка ключевых слов
        if data == "edit_keyword_list":
            async with get_db() as db:
                result = await db.execute(select(KeywordList))
                keyword_lists = result.scalars().all()
                if not keyword_lists:
                    new_text = "Список списков ключевых слов пуст."
                    new_markup = get_keyword_list_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = await get_keyword_list_keyboard(keyword_lists, "edit_keyword_list")
                    new_text = "Выберите список для редактирования:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Удаление списка ключевых слов
        if data == "delete_keyword_list":
            async with get_db() as db:
                result = await db.execute(select(KeywordList))
                keyword_lists = result.scalars().all()
                if not keyword_lists:
                    new_text = "Список списков ключевых слов пуст."
                    new_markup = get_keyword_list_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = await get_keyword_list_keyboard(keyword_lists, "delete_keyword_list")
                    new_text = "Выберите список для удаления:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Включение/выключение списка ключевых слов
        if data == "toggle_keyword_list":
            async with get_db() as db:
                result = await db.execute(select(KeywordList))
                keyword_lists = result.scalars().all()
                if not keyword_lists:
                    new_text = "Список списков ключевых слов пуст."
                    new_markup = get_keyword_list_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = await get_keyword_list_keyboard(keyword_lists, "toggle_keyword_list")
                    new_text = "Выберите список для включения/выключения:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Обработка редактирования списка
        if data.startswith("edit_keyword_list:"):
            list_id = int(data.split(":")[1])
            async with get_db() as db:
                result = await db.execute(select(KeywordList).where(KeywordList.id == list_id))
                keyword_list = result.scalars().first()
                if not keyword_list:
                    new_text = "Список не найден."
                    new_markup = get_keyword_list_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return
                await state.update_data({"list_id": list_id})
                new_text = f"Текущее название: {keyword_list.name}\nВведите новое название списка (или оставьте пустым для сохранения текущего):"
                new_markup = get_keyword_list_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await state.set_state(EditKeywordListForm.name)
                await callback.answer()
                return

        # Обработка удаления списка
        if data.startswith("delete_keyword_list:"):
            list_id = int(data.split(":")[1])
            async with get_db() as db:
                result = await db.execute(select(KeywordList).where(KeywordList.id == list_id))
                keyword_list = result.scalars().first()
                if keyword_list:
                    # Удаляем все ключевые слова, связанные с этим списком
                    await db.execute(text("DELETE FROM keyword_filters WHERE keyword_list_id = :list_id"), {"list_id": list_id})
                    await db.delete(keyword_list)
                    await db.commit()
                    new_text = f"Список с ID {list_id} удалён."
                else:
                    new_text = "Список не найден."
                new_markup = get_keyword_list_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Обработка включения/выключения списка
        if data.startswith("toggle_keyword_list:"):
            list_id = int(data.split(":")[1])
            async with get_db() as db:
                result = await db.execute(select(KeywordList).where(KeywordList.id == list_id))
                keyword_list = result.scalars().first()
                if keyword_list:
                    # Явно получаем значение enabled и name
                    enabled_result = await db.execute(select(KeywordList.enabled).where(KeywordList.id == list_id))
                    current_enabled = enabled_result.scalar() or False
                    name_result = await db.execute(select(KeywordList.name).where(KeywordList.id == list_id))
                    name = name_result.scalar() or "Unnamed"
                    # Обновляем значение через SQL-запрос
                    await db.execute(
                        text("UPDATE keyword_lists SET enabled = :value WHERE id = :id"),
                        {"value": not current_enabled, "id": list_id}
                    )
                    await db.commit()
                    new_text = f"Список '{name}' {'включён' if not current_enabled else 'выключен'}."
                else:
                    new_text = "Список не найден."
                new_markup = get_keyword_list_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Добавление аккаунта
        if data == "add_account":
            new_text = "Введите номер телефона (например, +1234567890):"
            new_markup = get_accounts_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.set_state(AddAccountForm.phone_number)
            await callback.answer()
            return

        # Список аккаунтов
        if data == "list_accounts":
            async with get_db() as db:
                result = await db.execute(select(Account))
                accounts = result.scalars().all()
                if not accounts:
                    new_text = "Список аккаунтов пуст."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    response = "Список аккаунтов:\n"
                    for account in accounts:
                        proxy_info = "Без прокси" if not account.proxy_id else f"Привязан прокси (ID: {account.proxy_id})"
                        response += f"ID: {account.id}, {proxy_info}\n"
                    new_text = response
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Удаление аккаунта
        if data == "delete_account":
            async with get_db() as db:
                result = await db.execute(select(Account))
                accounts = result.scalars().all()
                if not accounts:
                    new_text = "Список аккаунтов пуст."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = get_account_keyboard(accounts, "delete")
                    new_text = "Выберите аккаунт для удаления:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Удаление аккаунта по ID
        if data.startswith("delete:"):
            async with get_db() as db:
                account_id = int(data.split(":")[1])
                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                if account:
                    session_file = f"sessions/{account.phone_number}"
                    if os.path.exists(session_file):
                        os.remove(session_file)
                        logger.info(f"Файл сессии для аккаунта ID {account_id} удалён")
                    await db.delete(account)
                    await db.commit()
                    new_text = f"Аккаунт с ID {account_id} удалён."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    new_text = "Аккаунт не найден."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Проверка аккаунта
        if data == "check_account":
            async with get_db() as db:
                result = await db.execute(select(Account))
                accounts = result.scalars().all()
                if not accounts:
                    new_text = "Список аккаунтов пуст."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = get_account_keyboard(accounts, "check")
                    new_text = "Выберите аккаунт для проверки:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        if data.startswith("check:"):
            async with get_db() as db:
                account_id = int(data.split(":")[1])
                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                if account:
                    logger.info(f"Начало проверки аккаунта ID {account_id}")
                    client = await create_client(account, db)
                    try:
                        logger.info(f"Попытка подключения для аккаунта ID {account_id}")
                        await asyncio.wait_for(client.connect(), timeout=20)
                        logger.info(f"Подключение успешно для аккаунта ID {account_id}")
                        is_authorized = await client.is_user_authorized()
                        logger.info(f"Результат проверки авторизации: {is_authorized}")
                        if is_authorized:
                            new_text = f"✅ Аккаунт (ID: {account_id}) авторизован."
                        else:
                            new_text = f"❌ Аккаунт (ID: {account_id}) не авторизован."
                        new_markup = get_accounts_menu()
                        await callback.message.edit_text(new_text, reply_markup=new_markup)
                    except asyncio.TimeoutError:
                        logger.error(f"Тайм-аут при подключении для аккаунта ID {account_id}")
                        new_text = f"⏰ Тайм-аут при проверке аккаунта (ID: {account_id}). Проверьте подключение."
                        new_markup = get_accounts_menu()
                        await callback.message.edit_text(new_text, reply_markup=new_markup)
                    except Exception as e:
                        logger.error(f"Ошибка при проверке аккаунта ID {account_id}: {e}")
                        new_text = f"❌ Ошибка при проверке аккаунта (ID: {account_id}): {str(e)}"
                        new_markup = get_accounts_menu()
                        await callback.message.edit_text(new_text, reply_markup=new_markup)
                    finally:
                        logger.info(f"Закрытие соединения для аккаунта ID {account_id}")
                        await client.disconnect()
                else:
                    new_text = "Аккаунт не найден."
                    new_markup = get_accounts_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Добавление прокси
        if data == "add_proxy":
            new_text = "Введите данные прокси в формате:\nайпи порт пользователь пароль\nПример: geo.iproyal.com 32325 oeUMpx50aOQ3DvpU l2DS1ucvbAabA974_country-ru"
            new_markup = get_proxy_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.set_state(AddProxyForm.proxy_data)
            await callback.answer()
            return

        # Список прокси
        if data == "list_proxies":
            async with get_db() as db:
                result = await db.execute(select(Proxy))
                proxies = result.scalars().all()
                if not proxies:
                    new_text = "Список прокси пуст."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    response = "Список прокси:\n"
                    for proxy in proxies:
                        response += f"ID: {proxy.id}, Тип: {proxy.type}\n"
                    new_text = response
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Удаление прокси
        if data == "delete_proxy":
            async with get_db() as db:
                result = await db.execute(select(Proxy))
                proxies = result.scalars().all()
                if not proxies:
                    new_text = "Список прокси пуст."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = get_account_keyboard(proxies, "delete_proxy")
                    new_text = "Выберите прокси для удаления:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Удаление прокси по ID
        if data.startswith("delete_proxy:"):
            async with get_db() as db:
                proxy_id = int(data.split(":")[1])
                result = await db.execute(select(Proxy).where(Proxy.id == proxy_id))
                proxy = result.scalars().first()
                if proxy:
                    await db.delete(proxy)
                    await db.commit()
                    new_text = f"Прокси с ID {proxy_id} удалён."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    new_text = "Прокси не найден."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Привязка прокси к аккаунту — выбор аккаунта
        if data == "bind_proxy":
            async with get_db() as db:
                result = await db.execute(select(Account))
                accounts = result.scalars().all()
                if not accounts:
                    new_text = "Список аккаунтов пуст. Сначала добавьте аккаунт."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                    for account in accounts:
                        button = InlineKeyboardButton(
                            text=f"ID: {account.id}",
                            callback_data=f"bind_proxy_account:{account.id}"
                        )
                        keyboard.inline_keyboard.append([button])
                    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
                    new_text = "Выберите аккаунт для привязки прокси:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Выбор прокси для привязки
        if data.startswith("bind_proxy_account:"):
            async with get_db() as db:
                account_id = int(data.split(":")[1])
                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                if not account:
                    new_text = "Аккаунт не найден."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                result = await db.execute(select(Proxy))
                proxies = result.scalars().all()
                if not proxies:
                    new_text = "Список прокси пуст. Сначала добавьте прокси."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                for proxy in proxies:
                    button = InlineKeyboardButton(
                        text=f"ID: {proxy.id}, Хост: {proxy.host}, Порт: {proxy.port}",
                        callback_data=f"bind_proxy_to_account:{account_id}:{proxy.id}"
                    )
                    keyboard.inline_keyboard.append([button])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
                new_text = f"Выберите прокси для аккаунта ID {account_id}:"
                await callback.message.edit_text(new_text, reply_markup=keyboard)
                await state.update_data({"account_id": account_id})
                await callback.answer()
                return

        # Привязка прокси к аккаунту
        if data.startswith("bind_proxy_to_account:"):
            async with get_db() as db:
                parts = data.split(":")
                account_id = int(parts[1])
                proxy_id = int(parts[2])

                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                result = await db.execute(select(Proxy).where(Proxy.id == proxy_id))
                proxy = result.scalars().first()

                if not account or not proxy:
                    new_text = "Аккаунт или прокси не найдены."
                    new_markup = get_proxy_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                # Явно получаем proxy.id до commit
                proxy_id_value = proxy.id
                account.proxy_id = proxy_id
                await db.commit()
                new_text = f"Прокси (ID: {proxy_id_value}) успешно привязан к аккаунту ID {account_id}!"
                new_markup = get_proxy_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Добавление целевого чата
        if data == "add_target_chat":
            new_text = "Введите ID или ссылку на целевой чат/канал:"
            new_markup = get_chat_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.set_state(AddTargetChatForm.chat_id)
            await callback.answer()
            return

        # Список целевых чатов
        if data == "list_target_chats":
            async with get_db() as db:
                result = await db.execute(select(TargetChat))
                target_chats = result.scalars().all()
                if not target_chats:
                    new_text = "Список целевых чатов пуст."
                    new_markup = get_chat_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    response = "Список целевых чатов:\n"
                    for chat in target_chats:
                        response += f"ID: {chat.id}, Чат: {chat.chat_id}, Название: {chat.title or 'Не указано'}\n"
                    new_text = response
                    new_markup = get_chat_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Удаление целевого чата
        if data == "delete_target_chat":
            async with get_db() as db:
                result = await db.execute(select(TargetChat))
                target_chats = result.scalars().all()
                if not target_chats:
                    new_text = "Список целевых чатов пуст."
                    new_markup = get_chat_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = get_target_chat_keyboard(target_chats, "delete_target")
                    new_text = "Выберите чат для удаления:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Удаление целевого чата по ID
        if data.startswith("delete_target:"):
            async with get_db() as db:
                chat_id = int(data.split(":")[1])
                result = await db.execute(select(TargetChat).where(TargetChat.id == chat_id))
                chat = result.scalars().first()
                if chat:
                    await db.delete(chat)
                    await db.commit()
                    new_text = f"Чат с ID {chat_id} удалён."
                    new_markup = get_chat_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    new_text = "Чат не найден."
                    new_markup = get_chat_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Установка чата для пересылки
        if data == "set_forward_chat":
            new_text = "Введите ID чата, куда будут пересылаться сообщения (бот должен быть администратором):"
            new_markup = get_chat_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            await state.set_state(SetForwardChatForm.chat_id)
            await callback.answer()
            return

        # Включение/выключение фильтрации по ключевым словам
        if data == "toggle_filter":
            async with get_db() as db:
                result = await db.execute(select(Settings))
                settings = result.scalars().first()
                if settings:
                    # Явно получаем текущее значение filter_enabled
                    result = await db.execute(select(Settings.filter_enabled).where(Settings.id == settings.id))
                    current_filter_enabled = result.scalar() or False
                    # Обновляем значение через SQL-запрос, избегая автозагрузки
                    await db.execute(
                        text("UPDATE settings SET filter_enabled = :value WHERE id = :id"),
                        {"value": not current_filter_enabled, "id": settings.id}
                    )
                    await db.commit()
                    new_text = f"Фильтрация по ключевым словам {'включена' if not current_filter_enabled else 'выключена'}."
                else:
                    new_text = "Настройки не найдены. Установите чат для пересылки."
                new_markup = get_parsing_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Остановка парсинга
        if data == "stop_parsing":
            new_text = "Остановка парсинга..."
            new_markup = get_parsing_menu()
            await callback.message.edit_text(new_text, reply_markup=new_markup)
            async with get_db() as db:
                if active_parsers:
                    new_text = "Выберите парсинг для остановки:"
                    keyboard = get_active_parsers_keyboard()
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                else:
                    new_text = "Нет активных процессов парсинга."
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
            await callback.answer()
            return

        # Остановка конкретного парсинга
        if data.startswith("stop_parsing:"):
            async with get_db() as db:
                parts = data.split(":")
                account_id = int(parts[1])
                target_chat_id = ":".join(parts[2:])  # Восстанавливаем полный target_chat_id
                success = await stop_parsing(account_id, target_chat_id)
                if success:
                    new_text = f"Парсинг для аккаунта ID {account_id} и чата {target_chat_id} остановлен."
                else:
                    new_text = f"Парсинг для аккаунта ID {account_id} и чата {target_chat_id} не найден."
                new_markup = get_parsing_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer()
                return

        # Запуск парсинга
        if data == "start_parsing":
            async with get_db() as db:
                logger.info("Получение списка аккаунтов для парсинга...")
                result = await db.execute(select(Account))
                accounts = result.scalars().all()
                logger.info(f"Найдено аккаунтов: {len(accounts)}")

                logger.info("Получение списка целевых чатов...")
                result = await db.execute(select(TargetChat))
                target_chats = result.scalars().all()
                logger.info(f"Найдено целевых чатов: {len(target_chats)}")

                logger.info("Получение настроек...")
                result = await db.execute(select(Settings))
                settings = result.scalars().first()
                logger.info(f"Настройки: {settings.forward_chat_id if settings else 'Не установлены'}")

                if not settings or not settings.forward_chat_id:
                    new_text = "Сначала установите чат для пересылки."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                elif not accounts:
                    new_text = "Список аккаунтов пуст. Сначала добавьте аккаунт."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                elif not target_chats:
                    new_text = "Список целевых чатов пуст. Сначала добавьте чат."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                else:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                    for account in accounts:
                        button = InlineKeyboardButton(
                            text=f"ID: {account.id}",
                            callback_data=f"parse_account:{account.id}"
                        )
                        keyboard.inline_keyboard.append([button])
                    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
                    new_text = "Выберите аккаунт для парсинга:"
                    await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Выбор чата для парсинга
        if data.startswith("parse_account:"):
            async with get_db() as db:
                account_id = int(data.split(":")[1])
                logger.info(f"Выбран аккаунт ID: {account_id}")
                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                if not account:
                    new_text = "Аккаунт не найден."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                result = await db.execute(select(TargetChat))
                target_chats = result.scalars().all()
                logger.info(f"Найдено целевых чатов для парсинга: {len(target_chats)}")
                if not target_chats:
                    new_text = "Список целевых чатов пуст. Сначала добавьте чат."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                # Храним выбранные чаты в состоянии
                await state.update_data({"account_id": account_id, "selected_chats": []})
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                for chat in target_chats:
                    callback_data = f"toggle_chat:{account_id}:{chat.id}"
                    data_state = await state.get_data()
                    selected_chats = data_state.get("selected_chats", [])
                    button_text = f"{'✅' if chat.id in selected_chats else '⬜'} {chat.title or chat.chat_id} (ID: {chat.id})"
                    keyboard.inline_keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_chats:{account_id}")])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
                new_text = f"Выберите чаты для парсинга аккаунтом (ID: {account_id}):"
                await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Переключение выбора чата
        if data.startswith("toggle_chat:"):
            async with get_db() as db:
                parts = data.split(":")
                account_id = int(parts[1])
                chat_id = int(parts[2])
                logger.info(f"Переключение выбора чата ID: {chat_id} для аккаунта ID: {account_id}")
                data_state = await state.get_data()
                selected_chats = data_state.get("selected_chats", [])
                if chat_id in selected_chats:
                    selected_chats.remove(chat_id)
                else:
                    selected_chats.append(chat_id)
                await state.update_data({"selected_chats": selected_chats})

                result = await db.execute(select(TargetChat))
                target_chats = result.scalars().all()
                keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                for chat in target_chats:
                    callback_data = f"toggle_chat:{account_id}:{chat.id}"
                    button_text = f"{'✅' if chat.id in selected_chats else '⬜'} {chat.title or chat.chat_id} (ID: {chat.id})"
                    keyboard.inline_keyboard.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_chats:{account_id}")])
                keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
                new_text = f"Выберите чаты для парсинга аккаунтом (ID: {account_id}):"
                await callback.message.edit_text(new_text, reply_markup=keyboard)
                await callback.answer()
                return

        # Подтверждение выбора чатов
        if data.startswith("confirm_chats:"):
            async with get_db() as db:
                account_id = int(data.split(":")[1])
                logger.info(f"Подтверждение выбора чатов для аккаунта ID: {account_id}")
                result = await db.execute(select(Account).where(Account.id == account_id))
                account = result.scalars().first()
                data_state = await state.get_data()
                selected_chats = data_state.get("selected_chats", [])
                logger.info(f"Выбрано чатов: {len(selected_chats)}")
                result = await db.execute(select(Settings))
                settings = result.scalars().first()
                logger.info(f"Настройки для пересылки: {settings.forward_chat_id if settings else 'Не установлены'}")

                if not account or not settings or not settings.forward_chat_id:
                    new_text = "Аккаунт или настройки не найдены."
                    new_markup = get_parsing_menu()
                    await callback.message.edit_text(new_text, reply_markup=new_markup)
                    await callback.answer()
                    return

                # Показываем промежуточное сообщение
                await callback.message.edit_text("⏳ Запуск парсинга... Пожалуйста, подождите.")
                await callback.answer("Запуск парсинга начат!")

                # Получаем ключевые слова только из активных списков
                result = await db.execute(
                    select(KeywordFilter.keyword).join(KeywordList).where(
                        KeywordList.account_id == account_id,
                        KeywordList.enabled == True,
                        KeywordFilter.enabled == True
                    )
                )
                keywords = [row[0] for row in result.fetchall()]
                result = await db.execute(select(Settings.filter_enabled).where(Settings.id == settings.id))
                filter_enabled = result.scalar() or False

                success_chats = []
                failed_chats = []
                for chat_id in selected_chats:
                    result = await db.execute(select(TargetChat).where(TargetChat.id == chat_id))
                    target_chat = result.scalars().first()
                    if target_chat:
                        try:
                            logger.info(f"Запуск парсинга для чата {target_chat.chat_id} с аккаунтом {account.id}")
                            await start_real_time_parsing(
                                account,
                                target_chat.chat_id,
                                bot=bot,
                                forward_chat_id=settings.forward_chat_id,
                                keywords=keywords,
                                filter_enabled=filter_enabled
                            )
                            success_chats.append(target_chat.chat_id)
                            logger.info(f"Парсинг для {target_chat.chat_id} успешно запущен")
                        except Exception as e:
                            failed_chats.append(f"{target_chat.chat_id}: {str(e)}")
                            logger.error(f"Ошибка при запуске парсинга для {target_chat.chat_id}: {e}")
                    else:
                        failed_chats.append(f"Чат ID {chat_id}: не найден")

                # Формируем сообщение с результатами
                new_text = "✅ Парсинг успешно запущен!\n"
                if success_chats:
                    new_text += "Запущены чаты:\n" + "\n".join([f"✅ {chat}" for chat in success_chats]) + "\n"
                if failed_chats:
                    new_text += "Не удалось запустить чаты:\n" + "\n".join([f"❌ {chat}" for chat in failed_chats]) + "\n"
                new_text += "Перейдите в 'Управление парсингом' для статуса."

                new_markup = get_parsing_menu()
                await callback.message.edit_text(new_text, reply_markup=new_markup)
                await callback.answer("Парсинг запущен!")
                await state.clear()
                return

# Получение ID целевого чата
@router.message(AddTargetChatForm.chat_id)
async def process_target_chat_id(message: types.Message, state: FSMContext):
    async with get_db() as db:
        chat_id = message.text.strip()
        await state.update_data({"chat_id": chat_id})
        await message.answer("Введите название чата (опционально, можно оставить пустым):", reply_markup=get_chat_menu())
        await state.set_state(AddTargetChatForm.title)

# Получение названия целевого чата
@router.message(AddTargetChatForm.title)
async def process_target_chat_title(message: types.Message, state: FSMContext):
    async with get_db() as db:
        title = message.text.strip() or None
        data = await state.get_data()
        chat_id = data.get("chat_id")

        result = await db.execute(select(TargetChat).where(TargetChat.chat_id == chat_id))
        existing_chat = result.scalars().first()
        if existing_chat:
            await message.answer("Этот чат уже добавлен!", reply_markup=get_chat_menu())
            await state.clear()
            return

        target_chat = TargetChat(chat_id=chat_id, title=title)
        db.add(target_chat)
        await db.commit()
        await db.refresh(target_chat)

        await message.answer(f"Целевой чат добавлен! ID: {target_chat.id}, Чат: {chat_id}", reply_markup=get_chat_menu())
        await state.clear()

# Получение данных прокси
@router.message(AddProxyForm.proxy_data)
async def process_proxy_data(message: types.Message, state: FSMContext):
    async with get_db() as db:
        try:
            parts = message.text.strip().split()
            if len(parts) != 4:
                raise ValueError("Неверный формат. Введите данные в формате: айпи порт пользователь пароль")

            host, port, user, password = parts
            port = int(port)
            if port < 0 or port > 65535:
                raise ValueError("Порт должен быть в диапазоне от 0 до 65535")

            proxy = Proxy(host=host, port=port, user=user, password=password, type="SOCKS5")
            db.add(proxy)
            await db.commit()
            await db.refresh(proxy)

            await message.answer(f"Прокси успешно добавлен! ID: {proxy.id}", reply_markup=get_proxy_menu())
        except ValueError as e:
            await message.answer(f"Ошибка: {str(e)}. Попробуйте снова:", reply_markup=get_proxy_menu())
            await state.set_state(AddProxyForm.proxy_data)
        except Exception as e:
            await message.answer(f"Произошла ошибка: {str(e)}. Попробуйте снова:", reply_markup=get_proxy_menu())
            await state.set_state(AddProxyForm.proxy_data)
        else:
            await state.clear()

# Команда /add_account
@router.message(Command("add_account"))
async def add_account_start(message: types.Message, state: FSMContext):
    async with get_db() as db:
        await message.answer("Введите номер телефона (например, +1234567890):", reply_markup=get_accounts_menu())
        await state.set_state(AddAccountForm.phone_number)

# Получение номера телефона
@router.message(AddAccountForm.phone_number)
async def process_phone_number(message: types.Message, state: FSMContext):
    async with get_db() as db:
        phone_number = message.text.strip()
        if not phone_number.startswith("+"):
            await message.answer("Номер должен начинаться с '+'. Попробуйте снова.", reply_markup=get_accounts_menu())
            return

        result = await db.execute(select(Account).where(Account.phone_number == phone_number))
        existing_account = result.scalars().first()
        if existing_account:
            await message.answer("Этот номер уже добавлен!", reply_markup=get_accounts_menu())
            await state.clear()
            return

        await state.update_data({"phone_number": phone_number})
        await message.answer("Введите API ID:", reply_markup=get_accounts_menu())
        await state.set_state(AddAccountForm.api_id)

# Получение API ID
@router.message(AddAccountForm.api_id)
async def process_api_id(message: types.Message, state: FSMContext):
    async with get_db() as db:
        try:
            api_id = int(message.text.strip())
        except ValueError:
            await message.answer("API ID должен быть числом. Попробуйте снова.", reply_markup=get_accounts_menu())
            return

        await state.update_data({"api_id": api_id})
        await message.answer("Введите API Hash:", reply_markup=get_accounts_menu())
        await state.set_state(AddAccountForm.api_hash)

# Получение API Hash
@router.message(AddAccountForm.api_hash)
async def process_api_hash(message: types.Message, state: FSMContext):
    async with get_db() as db:
        api_hash = message.text.strip()
        data = await state.get_data()
        phone_number = data.get("phone_number")
        api_id = data.get("api_id")

        account = Account(phone_number=phone_number, api_id=api_id, api_hash=api_hash)
        db.add(account)
        await db.commit()
        await db.refresh(account)

        client = await create_client(account, db)
        result = await authorize_client(client, phone_number, db)

        if result["status"] == "code_required":
            await state.update_data({"client": client, "phone_code_hash": result["phone_code_hash"]})
            await message.answer("Введите код авторизации, отправленный в Telegram:", reply_markup=get_accounts_menu())
            await state.set_state(AddAccountForm.code)
        else:
            await message.answer(f"Ошибка: {result.get('message', 'Неизвестная ошибка')}", reply_markup=get_accounts_menu())
            await state.clear()

# Получение кода авторизации
@router.message(AddAccountForm.code)
async def process_code(message: types.Message, state: FSMContext):
    async with get_db() as db:
        code = message.text.strip()
        data = await state.get_data()
        client = data.get("client")
        phone_number = data.get("phone_number")
        phone_code_hash = data.get("phone_code_hash")

        result = await complete_authorization(client, phone_number, code, phone_code_hash)
        logger.info(f"Result from complete_authorization: {result}")
        if result["status"] == "authorized":
            await message.answer("Аккаунт успешно добавлен и авторизован!", reply_markup=get_accounts_menu())
            await state.clear()
        elif result["status"] == "password_required":
            await state.update_data({"client": client, "phone_code_hash": phone_code_hash})
            await message.answer("Требуется пароль 2FA. Введите пароль:", reply_markup=get_accounts_menu())
            await state.set_state(AddAccountForm.password)
        else:
            await message.answer(f"Ошибка: {result.get('message', 'Неизвестная ошибка')}", reply_markup=get_accounts_menu())
            await state.clear()

# Получение пароля 2FA
@router.message(AddAccountForm.password)
async def process_password(message: types.Message, state: FSMContext):
    async with get_db() as db:
        password = message.text.strip()
        data = await state.get_data()
        client = data.get("client")
        phone_number = data.get("phone_number")
        phone_code_hash = data.get("phone_code_hash")

        result = await complete_authorization(client, phone_number, code=None, phone_code_hash=phone_code_hash, password=password)
        if result["status"] == "authorized":
            await message.answer("Аккаунт успешно авторизован с 2FA!", reply_markup=get_accounts_menu())
            await state.clear()
        else:
            await message.answer(f"Ошибка: {result.get('message', 'Неизвестная ошибка')}. Введите пароль снова:", reply_markup=get_accounts_menu())
            await state.set_state(AddAccountForm.password)

# Команда /list_accounts
@router.message(Command("list_accounts"))
async def list_accounts(message: types.Message):
    async with get_db() as db:
        result = await db.execute(select(Account))
        accounts = result.scalars().all()
        if not accounts:
            await message.answer("Список аккаунтов пуст.", reply_markup=get_accounts_menu())
            return

        response = "Список аккаунтов:\n"
        for account in accounts:
            proxy_info = "Без прокси" if not account.proxy_id else f"Привязан прокси (ID: {account.proxy_id})"
            response += f"ID: {account.id}, {proxy_info}\n"
        await message.answer(response, reply_markup=get_accounts_menu())