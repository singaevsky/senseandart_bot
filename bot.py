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
from telegram.error import BadRequest

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


# ---------- Работа с "базой данных" (Excel) ----------
def load_subscribers_df() -> pd.DataFrame:
    if os.path.exists(config.EXCEL_FILE):
        return pd.read_excel(config.EXCEL_FILE)
    return pd.DataFrame(
        columns=[
            "user_id",
            "username",
            "full_name",
            "joined_at",        # время первой подписки
            "promo_code",
            "status",
            "unsubscribed_at",  # время первой отписки
        ]
    )


def save_subscribers_df(df: pd.DataFrame):
    df.to_excel(config.EXCEL_FILE, index=False)


def user_row(user_id: int) -> pd.Series | None:
    df = load_subscribers_df()
    row = df[df["user_id"] == user_id]
    if row.empty:
        return None
    return row.iloc[0]


def user_has_promo(user_id: int) -> tuple[bool, str | None]:
    row = user_row(user_id)
    if row is None:
        return False, None
    promo = row.get("promo_code") or None
    return bool(promo), promo


def save_subscriber_to_excel(
    user_id: int,
    username: str | None,
    full_name: str | None,
    promo_code: str,
) -> bool:
    """
    Сохраняет подписчика в таблицу.
    Возвращает True, если это первая запись для этого user_id (новый подписчик).
    """
    df = load_subscribers_df()

    existing = df[df["user_id"] == user_id]
    if not existing.empty and existing.iloc[0].get("promo_code"):
        logger.info("User %s already has promo, not adding duplicate row", user_id)
        return False  # не новый

    row = {
        "user_id": user_id,
        "username": username or "",
        "full_name": full_name or "",
        "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # логируем время подписки
        "promo_code": promo_code,
        "status": "подписан",
        "unsubscribed_at": "",
    }

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_subscribers_df(df)
    logger.info("Saved subscriber to Excel: %s (@%s)", user_id, username)

    upload_excel_to_yadisk()
    return True  # новый подписчик


def mark_unsubscribed(user_id: int) -> bool:
    """
    Отмечает пользователя как отписавшегося и логирует время отписки.
    Возвращает True, если статус реально изменился с другого на 'отписан'.
    """
    df = load_subscribers_df()
    idx = df.index[df["user_id"] == user_id]

    if len(idx) == 0:
        return False

    i = idx[0]
    prev_status = df.at[i, "status"]
    if prev_status == "отписан":
        return False

    df.at[i, "status"] = "отписан"
    df.at[i, "unsubscribed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_subscribers_df(df)
    logger.info("Marked user %s as unsubscribed", user_id)
    return True


def mark_subscribed_if_exists(user_id: int) -> None:
    """
    Если пользователь уже есть в таблице, обновляет статус на 'подписан'.
    joined_at и unsubscribed_at не трогаем.
    """
    df = load_subscribers_df()
    idx = df.index[df["user_id"] == user_id]
    if len(idx) == 0:
        return
    i = idx[0]
    if df.at[i, "status"] != "подписан":
        df.at[i, "status"] = "подписан"
        save_subscribers_df(df)
        logger.info("Updated user %s status back to 'подписан'", user_id)


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

    # НЕ подписан
    if not subscribed:
        menu = menu_for_not_subscribed(lang)
        if update.message is not None:
            await update.message.reply_text(
                t(lang, "start_subscribe"),
                reply_markup=menu,
            )
        return

    # Подписан
    menu = menu_for_subscribed(lang)

    row = user_row(user_id)
    is_new_in_excel = row is None

    has_promo, existing_promo = user_has_promo(user_id)

    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
        if update.message is not None:
            await update.message.reply_text(text, reply_markup=menu)
    else:
        promo_text = t(lang, "start_promo", promo=config.PROMO_CODE)
        if update.message is not None:
            await update.message.reply_text(promo_text, reply_markup=menu)
        # Сохраняем в таблицу, логируем время подписки
        created_now = save_subscriber_to_excel(user_id, username, full_name, config.PROMO_CODE)
        is_new_in_excel = is_new_in_excel or created_now

    # Если запись уже была, но статус мог быть "отписан" — вернём в "подписан"
    if not is_new_in_excel:
        mark_subscribed_if_exists(user_id)

    # Уведомляем администратора ТОЛЬКО при первой записи (новой подписке)
    if is_new_in_excel and config.ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"Новый подписчик канала: {user_id} (@{username}) язык={lang}",
            )
        except Exception as e:
            logger.warning("Failed to notify admin: %s", e)


# ---------- /check ----------
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)
    user_id = user.id

    is_sub = await is_user_subscribed(context, user_id)

    row = user_row(user_id)
    prev_status = row.get("status") if row is not None else None

    if is_sub:
        text = "Вы подписаны на канал ✅"
        menu = menu_for_subscribed(lang)
        if prev_status != "подписан" and row is not None:
            mark_subscribed_if_exists(user_id)
    else:
        text = "Вы не подписаны на канал ❌"
        menu = menu_for_not_subscribed(lang)

        # если раньше был "подписан" — считаем, что это первая отписка
        if prev_status == "подписан":
            changed = mark_unsubscribed(user_id)  # логируем время отписки
            if changed and config.ADMIN_ID:
                try:
                    await context.bot.send_message(
                        chat_id=config.ADMIN_ID,
                        text=(
                            "Пользователь ОТПИСАЛСЯ от канала:\n"
                            f"id: {user_id}\n"
                            f"username: @{user.username if user.username else 'нет'}\n"
                            f"имя: {user.full_name}"
                        ),
                    )
                except Exception as e:
                    logger.warning("Failed to notify admin about unsubscribe: %s", e)

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


# ---------- Обработчик ошибок (опционально) ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(context.error, BadRequest):
        logger.error("BadRequest message: %s", context.error.message)


# ---------- Команды для кнопки «/» ----------
async def set_commands(app: Application):
    await app.bot
