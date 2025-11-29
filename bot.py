# bot.py — полностью исправленная версия под aiogram ≥ 3.7
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import pandas as pd
from datetime import datetime
import os
import logging

from config import TOKEN, CHANNEL_ID, ADMIN_ID, PROMO_CODE, PINNED_POST_LINK

# ------------------- Google Sheets (опционально) -------------------
try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import pickle
    GOOGLE_SHEETS_ENABLED = True
except ImportError:
    GOOGLE_SHEETS_ENABLED = False

logging.basicConfig(level=logging.INFO)

# ВОТ ГЛАВНОЕ ИСПРАВЛЕНИЕ:
default_properties = DefaultBotProperties(parse_mode=ParseMode.HTML)
bot = Bot(token=TOKEN, default=default_properties)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

EXCEL_FILE = "subscribers.xlsx"

# =================== Google Sheets ===================
def get_google_sheet_service():
    if not GOOGLE_SHEETS_ENABLED:
        return None
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('sheets', 'v4', credentials=creds)

def append_to_google_sheets(row):
    if not GOOGLE_SHEETS_ENABLED:
        return
    try:
        service = get_google_sheet_service()
        body = {'values': [row]}
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="subscribers!A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
    except Exception as e:
        logging.error(f"Google Sheets error: {e}")

# =================== Excel ===================
def load_subscribers():
    if os.path.exists(EXCEL_FILE):
        return pd.read_excel(EXCEL_FILE)
    else:
        df = pd.DataFrame(columns=[
            'user_id', 'username', 'first_name', 'subscribe_date', 'promo_code', 'status'
        ])
        df.to_excel(EXCEL_FILE, index=False)
        return df

def save_subscriber(user_id, username, first_name):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = {
        'user_id': user_id,
        'username': f"@{username}" if username else "нет",
        'first_name': first_name or "нет",
        'subscribe_date': now,
        'promo_code': PROMO_CODE,
        'status': 'подписан'
    }

    # Excel
    df = load_subscribers()
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_excel(EXCEL_FILE, index=False)

    # Google Sheets
    row_for_gs = [user_id, f"@{username}" if username else "", first_name or "", now, PROMO_CODE, "подписан"]
    append_to_google_sheets(row_for_gs)

# =================== Клавиатуры и язык ===================
def get_start_keyboard(lang: str):
    text = "Перейти к важному посту" if lang == "ru" else "Go to the important post"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=PINNED_POST_LINK)]])

def get_subscribe_keyboard(lang: str):
    btn1 = "Подписаться на канал" if lang == "ru" else "Subscribe to the channel"
    btn2 = "Я подписался" if lang == "ru" else "I subscribed"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn1, url="https://t.me/senseandart")],
        [InlineKeyboardButton(text=btn2, callback_data="check_subscription")]
    ])

def detect_language(user: types.User) -> str:
    return "ru" if user.language_code and user.language_code.startswith('ru') else "en"

# =================== Хендлеры ===================
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    lang = detect_language(user)

    # Проверяем, получал ли уже промокод
    df = load_subscribers()
    if user.id in df['user_id'].values:
        text = (
            f"Привет снова, {user.first_name}! 😊\n\n"
            f"Твой промокод: <b>{PROMO_CODE}</b>\n"
            "Он всё ещё действителен (скидка 10%)."
        ) if lang == "ru" else (
            f"Hi again, {user.first_name}! 😊\n\n"
            f"Your promo code: <b>{PROMO_CODE}</b>\n"
            "Still valid (10% discount)."
        )
        await message.answer(text, reply_markup=get_start_keyboard(lang))
        return

    # Проверка подписки
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user.id)
        if member.status in ['member', 'administrator', 'creator']:
            # Подписан → выдаём промокод
            save_subscriber(user.id, user.username, user.full_name)

            # Уведомление админу
            await bot.send_message(
                ADMIN_ID,
                f"Новый подписчик!\n\n"
                f"Имя: {user.full_name}\n"
                f"Username: @{user.username or 'нет'}\n"
                f"ID: {user.id}\n"
                f"Промокод: {PROMO_CODE}"
            )

            text = (
                f"Спасибо за подписку, {user.first_name}! 🎨\n\n"
                f"Ваш промокод на <b>10% скидку</b>:\n"
                f"<code>{PROMO_CODE}</code>\n\n"
                "Используйте его при оформлении заказа.\n"
                "А теперь самое важное:"
            ) if lang == "ru" else (
                f"Thank you for subscribing, {user.first_name}! 🎨\n\n"
                f"Your <b>10% discount</b> promo code:\n"
                f"<code>{PROMO_CODE}</code>\n\n"
                "Use it at checkout.\n"
                "And now the most important:"
            )
            await message.answer(text, reply_markup=get_start_keyboard(lang))
        else:
            # Не подписан
            text = (
                "Чтобы получить скидку 10%, подпишись на канал «Искусство и смыслы» 👇"
            ) if lang == "ru" else (
                "To get a 10% discount, subscribe to the channel «Art & Meanings» 👇"
            )
            await message.answer(text, reply_markup=get_subscribe_keyboard(lang))
    except Exception as e:
        logging.error(e)
        await message.answer("Ошибка. Попробуйте позже / Try again later.")

@router.callback_query(F.data == "check_subscription")
async def check_after_subscribe(callback: types.CallbackQuery):
    await callback.message.delete()  # убираем кнопки
    await cmd_start(callback.message)  # повторяем проверку
    await callback.answer()

# =================== Запуск ===================
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
