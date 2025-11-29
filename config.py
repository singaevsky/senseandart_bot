import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота @saleofart_bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Админ (ты)
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Канал и закреплённый пост
CHANNEL_USERNAME = "@senseandart"
PINNED_POST_URL = "https://t.me/senseandart/123"  # замени на реальный ID поста

# Промокод и файл Excel
PROMO_CODE = "ART10"
EXCEL_FILE = "subscribers.xlsx"

# Яндекс.Диск (если нужно облако; можно оставить пустым)
YADISK_TOKEN = os.getenv("YADISK_TOKEN", "")
YADISK_PATH = "app:/subscribers.xlsx"
