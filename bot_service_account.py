# bot_service_account.py
import logging
from datetime import datetime

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

# Работаем с Google Sheets через Service Account
import google_sheets_service_account as gs


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Клавиатуры ----------
def menu_for_not_subscribed(lang: str) -> ReplyKeyboardMarkup:
    """Меню для неподписанных пользователей."""
    keyboard = [
        ["Старт", "Проверка подписки"],
        ["Действующий промокод"],
        ["Перейти в канал"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def menu_for_subscribed(lang: str) -> ReplyKeyboardMarkup:
    """Меню для подписанных пользователей."""
    keyboard = [
        ["Старт", "Проверка подписки"],
        ["Действующий промокод"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ---------- Проверка подписки ----------
async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=config.CHANNEL_USERNAME, user_id=user_id
        )
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("Проверка подписки не удалась для %s: %s", user_id, e)
        return False


# ---------- Приветствие при первом запуске ----------
async def welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает приветственное сообщение при первом запуске бота."""
    user = update.effective_user
    if user is None:
        return

    user_id = user.id
    lang = detect_lang(user.language_code)

    logger.info("Новый пользователь %s (%s)", user_id, user.username)

    # Проверяем подписку сразу при приветствии
    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        # Не подписан - показываем приветствие с просьбой подписаться
        if update.message is not None:
            await update.message.reply_text(
                t(lang, "welcome_not_subscribed"),
                reply_markup=menu_for_not_subscribed(lang),
            )
    else:
        # Подписан - показываем приветствие и меню
        if update.message is not None:
            await update.message.reply_text(
                t(lang, "welcome_subscribed"),
                reply_markup=menu_for_subscribed(lang),
            )


# ---------- Обработчик команды /start ----------
async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start (аналогично кнопке Старт в меню)."""
    user = update.effective_user
    if user is None:
        return

    user_id = user.id
    username = user.username
    full_name = user.full_name
    lang = detect_lang(user.language_code)

    logger.info("Пользователь %s (%s) нажал /start", user_id, username)

    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        # Не подписан
        text = "❌ Вы не подписаны на канал. Подпишитесь и попробуйте снова."
        if update.message is not None:
            await update.message.reply_text(
                text,
                reply_markup=menu_for_not_subscribed(lang),
            )
        return

    # Подписан - выдаем промокод
    menu = menu_for_subscribed(lang)

    row = gs.user_row(user_id)
    is_new_in_sheet = row is None

    has_promo, existing_promo = gs.user_has_promo(user_id)

    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
        if update.message is not None:
            await update.message.reply_text(text, reply_markup=menu)
    else:
        promo_text = t(lang, "start_promo", promo=config.PROMO_CODE)
        if update.message is not None:
            await update.message.reply_text(promo_text, reply_markup=menu)

        # Upsert в Google Sheets
        created_now = gs.save_subscriber_to_sheet(
            user_id, username, full_name, config.PROMO_CODE
        )
        is_new_in_sheet = is_new_in_sheet or created_now

    # Если запись уже была, но статус мог быть «отписан» — возвращаем её к «подписан»
    if not is_new_in_sheet:
        gs.mark_subscribed_if_exists(user_id)

    # Уведомляем администратора при первой записи (новый подписчик)
    if is_new_in_sheet and config.ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=config.ADMIN_ID,
                text=f"🆕 Новый подписчик канала: {user_id} (@{username}) язык={lang}",
            )
        except Exception as e:
            logger.warning("Не удалось уведомить администратора: %s", e)


# ---------- /check ----------
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)
    user_id = user.id

    is_sub = await is_user_subscribed(context, user_id)

    row = gs.user_row(user_id)
    prev_status = row.get("status") if row is not None else None

    if is_sub:
        text = "✅ Вы подписаны на канал"
        menu = menu_for_subscribed(lang)
        if prev_status != "подписан" and row is not None:
            gs.mark_subscribed_if_exists(user_id)
    else:
        text = "❌ Вы не подписаны на канал"
        menu = menu_for_not_subscribed(lang)

        if prev_status == "подписан":
            changed = gs.mark_unsubscribed(user_id)
            if changed and config.ADMIN_ID:
                try:
                    await context.bot.send_message(
                        chat_id=config.ADMIN_ID,
                        text=(
                            "👋 Пользователь ОТПИСАЛСЯ от канала:\n"
                            f"🆔 id: {user_id}\n"
                            f"👤 username: @{user.username if user.username else 'нет'}\n"
                            f"📝 имя: {user.full_name}"
                        ),
                    )
                except Exception as e:
                    logger.warning("Не удалось уведомить об отписке: %s", e)

    await update.message.reply_text(text, reply_markup=menu)


# ---------- /promo ----------
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)

    has_promo, existing_promo = gs.user_has_promo(user.id)
    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
    else:
        text = "Для получения промокода сначала нажмите «Старт» и подпишитесь на канал."

    is_sub = await is_user_subscribed(context, user.id)
    menu = menu_for_subscribed(lang) if is_sub else menu_for_not_subscribed(lang)

    await update.message.reply_text(text, reply_markup=menu)


# ---------- Обработчик текстовых кнопок ----------
async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return

    text = (update.message.text or "").strip().lower()

    if text == "старт":
        await handle_start_command(update, context)
    elif text == "проверка подписки":
        await check_subscription(update, context)
    elif text == "действующий промокод":
        await promo(update, context)
    elif text == "перейти в канал":
        # Показываем inline‑клавиатуру со ссылкой на второй пост канала
        inline_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="📢 Перейти в канал",
                        url="https://t.me/senseandart/3"  # ← Тредтий ПОСТ
                    )
                ]
            ]
        )
        await update.message.reply_text(
            "Нажмите кнопку ниже, чтобы перейти в канал и подписаться:",
            reply_markup=inline_kb,
        )
    else:
        return


# ---------- Обработчик ошибок ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Исключение при обработке обновления:", exc_info=context.error)
    if isinstance(context.error, BadRequest):
        logger.error("BadRequest сообщение: %s", context.error.message)


# ---------- Команды в меню «/» ----------
async def set_commands(app: Application):
    await app.bot.set_my_commands(
        [
            BotCommand("start", "🚀 Получить промокод"),
            BotCommand("check", "🔍 Проверка подписки"),
            BotCommand("promo", "🎁 Промокод"),
        ]
    )


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("❌ TELEGRAM_BOT_TOKEN не задан (проверь .env)")

    logger.info("🤖 Инициализация бота...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Новые обработчики
    app.add_handler(CommandHandler("start", welcome_message))  # Приветствие при /start
    app.add_handler(CommandHandler("check", check_subscription))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), menu_text_handler))

    app.post_init = set_commands
    app.add_error_handler(error_handler)

    logger.info("✅ Бот для канала запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
