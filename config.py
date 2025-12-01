import os
from dotenv import load_dotenv

load_dotenv()

# ---------- Telegram (move sensitive values into .env) ----------
# Set these in your `.env` file. Defaults are empty to force explicit configuration.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# CHANNEL_USERNAME should include leading @ for API calls (we strip it when building t.me links)
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@uezdcake")
# Bot username (for mentioning), optional
BOT_USERNAME = os.getenv("BOT_USERNAME", "@uezdcake_bot")
# Admin user id (integer). Leave empty if you prefer group-admin control.
_admin_env = os.getenv("ADMIN_ID")
ADMIN_ID = int(_admin_env) if (_admin_env and _admin_env.strip() != "") else None
PROMO_CODE = os.getenv("PROMO_CODE", "ART10")

# Which post number to link to when sending users to the channel (can be updated with /setpost)
CHANNEL_POST = int(os.getenv("CHANNEL_POST", "1"))

# ---------- Google Sheets (move sheet id and credentials to .env) ----------
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")

# ---------- Локализация ----------
# Build pinned post URL (derived from channel and post number)
PINNED_POST_URL = os.getenv("PINNED_POST_URL", f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}/{CHANNEL_POST}")

# Файл состояния для динамических настроек (например, номер поста в канале)
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

# ---------- Яндекс.Диск (больше не используется, можно оставить для совместимости) ----------
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
YADISK_PATH = os.getenv("YADISK_PATH", "/bot/subscribers.xlsx")
EXCEL_FILE = "subscribers.xlsx"
