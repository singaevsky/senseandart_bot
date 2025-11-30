import os
from dotenv import load_dotenv

load_dotenv()
# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@senseandart")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) if os.getenv("ADMIN_ID") else None
PROMO_CODE = os.getenv("PROMO_CODE", "ART10")

# ---------- Google Sheets ----------
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1V4RGuU-nf3iQeelmqCQG8LvvK9ZKozh5Asq1oQUInE0")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")

# ---------- Локализация ----------
PINNED_POST_URL = os.getenv("PINNED_POST_URL", "https://t.me/senseandart/1")

# ---------- Яндекс.Диск (больше не используется, можно оставить для совместимости) ----------
YADISK_TOKEN = os.getenv("YADISK_TOKEN")
YADISK_PATH = os.getenv("YADISK_PATH", "/bot/subscribers.xlsx")
EXCEL_FILE = "subscribers.xlsx"

