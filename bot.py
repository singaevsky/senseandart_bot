import logging
import os
from datetime import datetime

import pandas as pd
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from localization import detect_lang, t
import config


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Меню-клавиатуры ----------
def menu_for_not_subscribed(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        ["Старт", "Проверка подписки"],
        ["Действующий промокод"],
        ["Подписаться на канал"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def menu_for_subscribed(lang: str) -> ReplyKeyboardMarkup:
    keyboard = [
        ["Старт", "Проверка подписки"],
        ["Действующий промокод"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ---------- Работа с Excel ----------
def load_subscribers_df() -> pd.DataFrame:
    if os.path.exists(config.EXCEL_FILE):
        return pd.read_excel(config.EXCEL_FILE)
    return pd.DataFrame(
        columns=[
            "user_id",
            "username",
            "full_name",
            "joined_at",
            "promo_code",
            "status",
        ]
    )


def save_subscribers_df(df: pd.DataFrame):
    df.to_excel(config.EXCEL_FILE, index=False)


def user_has_promo(user_id: int) -> tuple[bool, str | None]:
    df = load_subscribers_df()
    row = df[df["user_id"] == user_id]
    if row.empty:
        return False, None
    promo = row.iloc[0].get("promo_code") or None
    return bool(promo), promo


def save_subscriber_to_excel(
    user_id: int,
    username: str | None,
    full_name: str | None,
    promo_code: str,
):
    df = load_subscribers_df()

    existing = df[df["user_id"] == user_id]
    if not existing.empty and existing.iloc[0].get("promo_code"):
        logger.info("User %s already has promo, not adding duplicate row", user_id)
        return

    row = {
        "user_id": user_id,
        "username": username or "",
        "full_name": full_name or "",
        "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "promo_code": promo_code,
        "status": "подписан",
    }

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_subscribers_df(df)
    logger.info("Saved subscriber to Excel: %s (@%s)", user_id, username)

    upload_excel_to_yadisk()


# ---------- Яндекс.Диск (опционально) ----------
def upload_excel_to_yadisk():
    if not config.YADISK_TOKEN:
        return
    try:
        import yadisk

        disk = yadisk.YaDisk(token=config.YADISK_TOKEN)
        with open(config.EXCEL_FILE, "rb") as f:
            disk.upload_file(f, path=config.YADISK_PATH, overwrite=True)
        logger.info("Excel uploaded to Yandex.Disk: %s", config.YADISK_PATH)
    except Exception as e:
        logger.warning("Failed to upload Excel to Yandex.Disk: %s", e)


# ---------- Проверка подписки ----------
async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=config.CHANNEL_USERNAME, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("Check subscription failed for %s: %s", user_id, e)
        return False


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return

    user_id = user.id
    username = user.username
    full_name = user.full_name
    lang = detect_lang(user.language_code)

    logger.info("User %s (%s) sent /start lang=%s", user_id, username, lang)

    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        # ТОЛЬКО одно сообщение с текстом + меню.
        # Никаких дополнительных inline-кнопок, чтобы не дублировать.
        menu = menu_for_not_subscribed(lang)
        if update.message is not None:
            await update.message.reply_text(
                t(lang, "start_subscribe"),
                reply_markup=menu,
            )
        return

    # подписан — меню без кнопки "Подписаться"
    menu = menu_for_subscribed(lang)

    has_promo, existing_promo = user_has_promo(user_id)

    pinned_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "pinned_button"),
                    url=config.PINNED_POST_URL,
                )
            ]
        ]
    )

    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
        if update.message is not None:
            await update.message.reply_text(text, reply_markup=menu)
            await update.message.reply_text(t(lang, "pinned_button"), reply_markup=pinned_keyboard)
    else:
        promo_text = t(lang, "start_promo", promo=config.PROMO_CODE)
        if update.message is not None:
            await update.message.reply_text(promo_text, reply_markup=menu)
            await update.message.reply_text(t(lang, "pinned_button"), reply_markup=pinned_keyboard)
        save_subscriber_to_excel(user_id, username, full_name, config.PROMO_CODE)

    if config.ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"Новый подписчик: {user_id} (@{username}) язык={lang}",
            )
        except Exception as e:
            logger.warning("Failed to notify admin: %s", e)


# ---------- /check ----------
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)
    is_sub = await is_user_subscribed(context, user.id)
    text = "Вы подписаны на канал ✅" if is_sub else "Вы не подписаны на канал ❌"
    menu = menu_for_subscribed(lang) if is_sub else menu_for_not_subscribed(lang)

    await update.message.reply_text(text, reply_markup=menu)


# ---------- /promo ----------
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)

    has_promo, existing_promo = user_has_promo(user.id)
    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
    else:
        text = "Для получения промокода сначала нажмите «Старт» и подпишитесь на канал."

    is_sub = await is_user_subscribed(context, user.id)
    menu = menu_for_subscribed(lang) if is_sub else menu_for_not_subscribed(lang)

    await update.message.reply_text(text, reply_markup=menu)


# ---------- Обработка текстовых кнопок меню ----------
async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return

    text = (update.message.text or "").strip().lower()

    if text == "старт":
        await start(update, context)
    elif text == "проверка подписки":
        await check_subscription(update, context)
    elif text == "действующий промокод":
        await promo(update, context)
    elif text == "подписаться на канал":
        # ТОЛЬКО здесь даём кнопку-ссылку "Перейти в канал"
        channel_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Перейти в канал",
                        url=f"https://t.me/{config.CHANNEL_USERNAME.lstrip('@')}",
                    )
                ],
            ]
        )
        await update.message.reply_text(
            "Нажмите кнопку, чтобы перейти в канал:",
            reply_markup=channel_keyboard,
        )
    else:
        return


# ---------- Команды для кнопки «/» ----------
async def set_commands(app: Application):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Старт"),
            BotCommand("check", "Проверка подписки"),
            BotCommand("promo", "Действующий промокод"),
        ]
    )


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан (проверь .env)")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_subscription))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), menu_text_handler))

    app.post_init = set_commands

    logger.info("Bot для канала @senseandart запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
