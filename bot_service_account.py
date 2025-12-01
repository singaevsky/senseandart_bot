# bot_service_account.py
import logging
from datetime import datetime
from typing import Optional, cast

from telegram import (
    Update,
    User,
    Message,
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
    CallbackQueryHandler,
    filters,
)
from telegram.error import BadRequest

from localization import detect_lang, t
import config

# Работаем с Google Sheets через Service Account
import google_sheets_service_account as gs
import json
from pathlib import Path
import os


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- Типы ----------
UserType = User


# ---------- Локальный кэш уведомлённых пользователей ----------
# Файл, в котором храним список user_id, о которых уже уведомляли администратора.
NOTIFIED_USERS_FILE = Path(getattr(config, 'NOTIFIED_USERS_FILE', Path(__file__).with_name('notified_users.json')))


def _load_notified_users() -> set:
    try:
        if NOTIFIED_USERS_FILE.exists():
            with NOTIFIED_USERS_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(int(x) for x in data)
        return set()
    except Exception as e:
        logger.warning("Не удалось загрузить кэш уведомлённых пользователей: %s", e)
        return set()


def _save_notified_users(users: set) -> None:
    try:
        tmp = NOTIFIED_USERS_FILE.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(sorted(list(users)), f, ensure_ascii=False)
        tmp.replace(NOTIFIED_USERS_FILE)
    except Exception as e:
        logger.warning("Не удалось сохранить кэш уведомлённых пользователей: %s", e)


def _mark_user_notified(user_id: int) -> None:
    users = _load_notified_users()
    if user_id in users:
        return
    users.add(int(user_id))
    _save_notified_users(users)


# ---------- State persistence for dynamic settings (CHANNEL_POST) ----------
def _load_state() -> None:
    """Loads dynamic state (CHANNEL_POST) from the configured state file, if present."""
    try:
        state_file = getattr(config, 'STATE_FILE', 'bot_state.json')
        p = Path(state_file)
        if p.exists():
            with p.open('r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'CHANNEL_POST' in data:
                    try:
                        config.CHANNEL_POST = int(data['CHANNEL_POST'])
                    except Exception:
                        logger.debug('Invalid CHANNEL_POST in state file')
                    # Update PINNED_POST_URL to reflect new value
                    config.PINNED_POST_URL = f"https://t.me/{config.CHANNEL_USERNAME.lstrip('@')}/{config.CHANNEL_POST}"
    except Exception as e:
        logger.debug("Не удалось загрузить состояние: %s", e)


def _save_state(channel_post: int) -> None:
    """Saves dynamic state (CHANNEL_POST) to the configured state file."""
    try:
        state_file = getattr(config, 'STATE_FILE', 'bot_state.json')
        p = Path(state_file)
        data = {
            'CHANNEL_POST': int(channel_post)
        }
        tmp = p.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(p)
        # Update runtime config values
        config.CHANNEL_POST = int(channel_post)
        config.PINNED_POST_URL = f"https://t.me/{config.CHANNEL_USERNAME.lstrip('@')}/{config.CHANNEL_POST}"
    except Exception as e:
        logger.warning("Не удалось сохранить состояние: %s", e)


# ---------- Клавиатуры ----------
def menu_for_not_subscribed(lang: str) -> ReplyKeyboardMarkup:
    """Меню для неподписанных пользователей."""
    keyboard = [
        [t(lang, "btn_start"), t(lang, "btn_check")],
        [t(lang, "btn_promo")],
        [t(lang, "btn_go_to_channel")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def menu_for_subscribed(lang: str) -> ReplyKeyboardMarkup:
    """Меню для подписанных пользователей."""
    keyboard = [
        [t(lang, "btn_start"), t(lang, "btn_check")],
        [t(lang, "btn_promo")],
        [t(lang, "btn_go_to_channel")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def inline_menu_for_not_subscribed(lang: str) -> InlineKeyboardMarkup:
    """Inline-меню для неподписанных пользователей."""
    buttons = [
        [InlineKeyboardButton(text=t(lang, "btn_start"), callback_data="start") , InlineKeyboardButton(text=t(lang, "btn_check"), callback_data="check")],
        [InlineKeyboardButton(text=t(lang, "btn_promo"), callback_data="promo")],
        [InlineKeyboardButton(text=t(lang, "btn_go_to_channel"), callback_data="go_channel")],
    ]
    return InlineKeyboardMarkup(buttons)


def inline_menu_for_subscribed(lang: str) -> InlineKeyboardMarkup:
    """Inline-меню для подписанных пользователей."""
    buttons = [
        [InlineKeyboardButton(text=t(lang, "btn_start"), callback_data="start") , InlineKeyboardButton(text=t(lang, "btn_check"), callback_data="check")],
        [InlineKeyboardButton(text=t(lang, "btn_promo"), callback_data="promo")],
    ]
    return InlineKeyboardMarkup(buttons)


# ---------- Клавиатура с кнопкой перехода в канал ----------
def inline_channel_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура для перехода к 3-му посту канала."""
    label = t(lang, "go_to_channel") if lang else "📢 Перейти в канал"
    # Build URL to the 3rd post of the configured channel. Support values like
    # '@channelname' or 'channelname' in config.CHANNEL_USERNAME.
    channel = getattr(config, 'CHANNEL_USERNAME', None)
    if channel:
        ch = str(channel).lstrip('@')
        post = getattr(config, 'CHANNEL_POST', 1)
        try:
            post = int(post)
        except Exception:
            post = 1
        url = f"https://t.me/{ch}/{post}"
    else:
        # Fallback to previous hardcoded path if config not provided
        url = getattr(config, 'PINNED_POST_URL', "https://t.me/uezdcake/1")

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=label, url=url)]]
    )


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


# ---------- Уведомления администратору ----------
async def notify_admin_new_user(context: ContextTypes.DEFAULT_TYPE, user: UserType, lang: str):
    """Уведомляет администратора о новом пользователе бота."""
    if not config.ADMIN_ID:
        return

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        username = f"@{user.username}" if getattr(user, 'username', None) else 'нет'
        text = t(
            lang,
            "admin_new_user",
            id=user.id,
            username=username,
            full_name=user.full_name,
            time=now,
        )

        await context.bot.send_message(chat_id=config.ADMIN_ID, text=text)
    except Exception as e:
        logger.warning("Не удалось уведомить о новом пользователе: %s", e)


async def notify_admin_new_subscriber(context: ContextTypes.DEFAULT_TYPE, user: UserType, lang: str):
    """Уведомляет администратора о новом подписчике канала."""
    if not config.ADMIN_ID:
        return

    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        username = f"@{user.username}" if getattr(user, 'username', None) else 'нет'
        text = t(
            lang,
            "admin_new_subscriber",
            id=user.id,
            username=username,
            full_name=user.full_name,
            time=now,
            channel=config.CHANNEL_USERNAME,
        )

        await context.bot.send_message(chat_id=config.ADMIN_ID, text=text)
    except Exception as e:
        logger.warning("Не удалось уведомить о новом подписчике: %s", e)


async def notify_admin_promo_received(
    context: ContextTypes.DEFAULT_TYPE,
    user: UserType,
    promo: str,
    source: Optional[str] = None,
    lang: Optional[str] = None,
):
    """Уведомляет администратора о получении промокода. Принимает необязательный источник выдачи и язык для локализации."""
    if not config.ADMIN_ID:
        return

    try:
        # Determine language if not provided
        if not lang:
            lang = detect_lang(getattr(user, 'language_code', None))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        username = f"@{user.username}" if getattr(user, 'username', None) else 'нет'
        text = t(
            lang,
            "admin_promo_received",
            id=user.id,
            username=username,
            full_name=user.full_name,
            promo=promo,
            time=now,
            source=(source or "-"),
        )

        await context.bot.send_message(chat_id=config.ADMIN_ID, text=text)
    except Exception as e:
        logger.warning("Не удалось уведомить о получении промокода: %s", e)


async def notify_admin_unsubscribed(context: ContextTypes.DEFAULT_TYPE, user: UserType, lang: Optional[str] = None):
    """Уведомляет администратора об отписке пользователя."""
    if not config.ADMIN_ID:
        return

    try:
        if not lang:
            lang = detect_lang(getattr(user, 'language_code', None))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        username = f"@{user.username}" if getattr(user, 'username', None) else 'нет'
        text = t(
            lang,
            "admin_unsubscribed",
            id=user.id,
            username=username,
            full_name=user.full_name,
            time=now,
            channel=config.CHANNEL_USERNAME,
        )

        await context.bot.send_message(chat_id=config.ADMIN_ID, text=text)
    except Exception as e:
        logger.warning("Не удалось уведомить об отписке: %s", e)


async def send_reply(update: Update, text: str, reply_markup=None):
    """Helper: send reply to message or to callback_query.message."""
    # Try to reply to a normal message if present
    if getattr(update, 'message', None) is not None and update.message is not None:
        msg = cast(Message, update.message)
        await msg.reply_text(text, reply_markup=reply_markup)

    # Otherwise, try to reply to the message attached to a callback_query
    elif getattr(update, 'callback_query', None) is not None:
        cq = update.callback_query
        if cq is not None and getattr(cq, 'message', None) is not None and cq.message is not None:
            msg = cast(Message, cq.message)
            await msg.reply_text(text, reply_markup=reply_markup)


# ---------- Приветствие при первом запуске ----------
async def welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает приветственное сообщение при первом запуске бота."""
    user = update.effective_user
    if user is None:
        return

    user_id = user.id
    lang = detect_lang(user.language_code)

    logger.info("Новый пользователь %s (%s)", user_id, user.username)

    # Уведомляем администратора о новом пользователе только при первом взаимодействии
    try:
        notified = _load_notified_users()
        if user_id not in notified:
            try:
                existing = gs.user_row(user_id)
            except Exception as e:
                logger.warning("Ошибка проверки записи пользователя в Google Sheets: %s", e)
                # При ошибке доступа к Google Sheets — не уведомляем админа сейчас,
                # но добавляем в локальный кэш, чтобы не повторять попытки.
                _mark_user_notified(user_id)
                existing = True

            if existing is None:
                await notify_admin_new_user(context, user, lang)
                _mark_user_notified(user_id)
            else:
                _mark_user_notified(user_id)
    except Exception as e:
        logger.warning("Ошибка при работе с локальным кэшем уведомлений: %s", e)

    # Проверяем подписку сразу при приветствии
    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        # Не подписан - показываем приветствие с просьбой подписаться (reply keyboard для совместимости)
        await send_reply(update, t(lang, "welcome_not_subscribed"), reply_markup=menu_for_not_subscribed(lang))
    else:
        # Подписан - показываем приветствие и меню (reply keyboard для совместимости)
        await send_reply(update, t(lang, "welcome_subscribed"), reply_markup=menu_for_subscribed(lang))


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

    # Уведомляем администратора о новом пользователе только при первом взаимодействии
    try:
        notified = _load_notified_users()
        if user_id not in notified:
            try:
                existing = gs.user_row(user_id)
            except Exception as e:
                logger.warning("Ошибка проверки записи пользователя в Google Sheets: %s", e)
                _mark_user_notified(user_id)
                existing = True

            if existing is None:
                await notify_admin_new_user(context, user, lang)
                _mark_user_notified(user_id)
            else:
                _mark_user_notified(user_id)
    except Exception as e:
        logger.warning("Ошибка при работе с локальным кэшем уведомлений: %s", e)

    logger.info("Пользователь %s (%s) нажал /start", user_id, username)

    subscribed = await is_user_subscribed(context, user_id)

    if not subscribed:
        # Не подписан - предлагаем перейти к 3-му посту
        prompt = t(lang, "start_subscribe")
        inline_kb = inline_channel_keyboard(lang)
        await send_reply(update, prompt, reply_markup=inline_kb)
        return

    # Подписан - выдаем промокод
    menu = menu_for_subscribed(lang)

    row = gs.user_row(user_id)
    is_new_in_sheet = row is None

    has_promo, existing_promo = gs.user_has_promo(user_id)

    if has_promo and existing_promo:
        # Пользователь уже имеет промокод — показываем сообщение с промокодом и приглашением
        text = t(lang, "subscribed_thanks_with_promo", promo=existing_promo)
        await send_reply(update, text, reply_markup=menu_for_subscribed(lang))
    else:
        # Пользователь не имеет промокода — выдаём и поздравляем
        promo_assigned_text = t(lang, "congrats_promo_assigned", promo=config.PROMO_CODE)
        await send_reply(update, promo_assigned_text, reply_markup=menu_for_subscribed(lang))

        # Уведомляем о получении промокода
        await notify_admin_promo_received(context, user, config.PROMO_CODE, source="start")

        # Upsert в Google Sheets
        created_now = gs.save_subscriber_to_sheet(
            user_id, username, full_name, config.PROMO_CODE, issued_by="start"
        )
        is_new_in_sheet = is_new_in_sheet or created_now
        try:
            # Логируем выдачу промокода в отдельный лист promo_log
            gs.log_promo_issue(user_id, config.PROMO_CODE, source="start")
        except Exception as e:
            logger.warning("Не удалось залогировать выдачу промокода: %s", e)

        # Отправляем пользователю ссылку на пост со скидкой
        try:
            await send_reply(update, t(lang, "go_to_channel_prompt"), reply_markup=inline_channel_keyboard(lang))
        except Exception:
            logger.debug("Не удалось отправить пользователю ссылку на пост после выдачи промо")

        # Попытка опубликовать поздравление в канале (если бот имеет права)
        try:
            channel_text = t(lang, "channel_congrats", username=(username or full_name or str(user_id)), promo=config.PROMO_CODE)
            await context.bot.send_message(chat_id=config.CHANNEL_USERNAME, text=channel_text)
        except Exception as e:
            logger.debug("Не удалось опубликовать сообщение в канале: %s", e)

    # Если запись уже была, но статус мог быть «отписан» — возвращаем её к «подписан»
    if not is_new_in_sheet:
        gs.mark_subscribed_if_exists(user_id)

    # Уведомляем администратора при первой записи (новый подписчик)
    if is_new_in_sheet:
        await notify_admin_new_subscriber(context, user, lang)


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
        text = t(lang, "welcome_subscribed")
        await send_reply(update, text, reply_markup=menu_for_subscribed(lang))

        if prev_status != "подписан" and row is not None:
            gs.mark_subscribed_if_exists(user_id)

        # Если пользователь только что стал подписанным и не имеет промокода — выдаём
        has_promo, existing_promo = gs.user_has_promo(user_id)
        if not has_promo:
            promo_assigned_text = t(lang, "congrats_promo_assigned", promo=config.PROMO_CODE)
            await send_reply(update, promo_assigned_text, reply_markup=menu_for_subscribed(lang))
            await notify_admin_promo_received(context, user, config.PROMO_CODE, source="check_subscription")
            try:
                gs.save_subscriber_to_sheet(user_id, user.username, user.full_name, config.PROMO_CODE, issued_by="check_subscription")
            except Exception:
                logger.warning("Не удалось сохранить подписчика после выдачи промо при проверке подписки")
            try:
                gs.log_promo_issue(user_id, config.PROMO_CODE, source="check_subscription")
            except Exception:
                logger.debug("Не удалось залогировать промо при проверке подписки")
            try:
                channel_text = t(lang, "channel_congrats", username=(user.username or user.full_name or str(user_id)), promo=config.PROMO_CODE)
                await context.bot.send_message(chat_id=config.CHANNEL_USERNAME, text=channel_text)
            except Exception as e:
                logger.debug("Не удалось опубликовать сообщение в канале (check_subscription): %s", e)
    else:
        text = t(lang, "start_subscribe")
        # НЕ показываем меню, а сразу предлагаем перейти к 3-му посту
        inline_kb = inline_channel_keyboard(lang)
        await send_reply(update, text, reply_markup=inline_kb)

        if prev_status == "подписан":
            changed = gs.mark_unsubscribed(user_id)
            if changed:
                await notify_admin_unsubscribed(context, user)


# ---------- /promo ----------
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

    lang = detect_lang(user.language_code)

    has_promo, existing_promo = gs.user_has_promo(user.id)
    if has_promo and existing_promo:
        text = t(lang, "already_has_promo", promo=existing_promo)
        is_sub = await is_user_subscribed(context, user.id)
        menu = menu_for_subscribed(lang) if is_sub else menu_for_not_subscribed(lang)
        await send_reply(update, text, reply_markup=menu)
    else:
        text = t(lang, "start_subscribe")
        inline_kb = inline_channel_keyboard(lang)
        await send_reply(update, text, reply_markup=inline_kb)


# ---------- Обработчик текстовых кнопок ----------
async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return

    lang = detect_lang(update.effective_user.language_code)
    text = (update.message.text or "").strip().lower()

    # Получаем локализованные варианты кнопок и сравниваем в lower()
    try:
        btn_start = t(lang, "btn_start").strip().lower()
    except Exception:
        btn_start = "старт"
    try:
        btn_check = t(lang, "btn_check").strip().lower()
    except Exception:
        btn_check = "проверка подписки"
    try:
        btn_promo = t(lang, "btn_promo").strip().lower()
    except Exception:
        btn_promo = "действующий промокод"
    try:
        btn_go = t(lang, "btn_go_to_channel").strip().lower()
    except Exception:
        btn_go = "перейти в канал"

    if text == btn_start:
        await handle_start_command(update, context)
    elif text == btn_check:
        await check_subscription(update, context)
    elif text == btn_promo:
        await promo(update, context)
    elif text == btn_go:
        # Просто показываем кнопку для перехода к 3-му посту
        msg = cast(Message, update.message)
        await msg.reply_text(
            t(lang, "go_to_channel_prompt"),
            reply_markup=inline_channel_keyboard(lang),
        )
    else:
        return


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline buttons."""
    cq = update.callback_query
    if cq is None:
        return
    data = cq.data
    # Acknowledge the callback to remove 'loading'
    try:
        await cq.answer()
    except Exception:
        pass

    if data == "start":
        await handle_start_command(update, context)
    elif data == "check":
        await check_subscription(update, context)
    elif data == "promo":
        await promo(update, context)
    elif data == "go_channel":
        # Safely obtain language_code from callback_query.from_user (may be None)
        from_user = getattr(cq, 'from_user', None)
        user_lang_code = getattr(from_user, 'language_code', None) if from_user is not None else None
        lang = detect_lang(user_lang_code)
        await send_reply(update, t(lang, "go_to_channel_prompt"), reply_markup=inline_channel_keyboard(lang))


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
            BotCommand("setpost", "🔧 Установить номер поста канала (админ)")
        ]
    )


# ---------- /setpost command (admin-only) ----------
async def setpost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or update.message is None:
        return

        # Allow group administrators to change the post when command is run in a group
        chat = update.effective_chat
        is_allowed = False
        try:
            if chat is not None and chat.type in ("group", "supergroup"):
                # Проверяем, является ли пользователь администратором в чате
                try:
                    member = await context.bot.get_chat_member(chat.id, user.id)
                    if member.status in ("administrator", "creator"):
                        is_allowed = True
                except Exception:
                    is_allowed = False
            else:
                # В приватном чате — только явный ADMIN_ID
                if getattr(config, 'ADMIN_ID', None) is not None and user.id == config.ADMIN_ID:
                    is_allowed = True
        except Exception:
            is_allowed = False

        if not is_allowed:
            await send_reply(update, "У вас нет прав для выполнения этой команды.")
            return

    args = context.args or []
    if not args:
        await send_reply(update, "Использование: /setpost <номер поста> (например: /setpost 3)")
        return

    try:
        post_num = int(args[0])
        if post_num <= 0:
            raise ValueError("must be positive")
    except Exception:
        await send_reply(update, "Неверный номер поста. Укажите положительное целое число.")
        return

    # Save and apply state
    prev = getattr(config, 'CHANNEL_POST', None)
    _save_state(post_num)
    # Determine context where change applied
    chat = update.effective_chat
    where = "в группе" if (chat is not None and chat.type in ("group", "supergroup")) else "в личных сообщениях"
    await send_reply(update, f"Номер поста канала изменён {where}: {prev} → {post_num}. Сохранено в {getattr(config,'STATE_FILE','bot_state.json')}")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("❌ TELEGRAM_BOT_TOKEN не задан (проверь .env)")

    logger.info("🤖 Инициализация бота...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Новые обработчики
    app.add_handler(CommandHandler("start", handle_start_command))  # Приветствие /start -> обработка старта
    app.add_handler(CommandHandler("check", check_subscription))
    app.add_handler(CommandHandler("setpost", setpost_command))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), menu_text_handler))
    app.add_handler(CallbackQueryHandler(lambda u, c: callback_query_handler(u, c)))

    app.post_init = set_commands
    app.add_error_handler(error_handler)

    # Load persistent state (CHANNEL_POST) if present
    try:
        _load_state()
    except Exception as e:
        logger.debug("Не удалось загрузить сохранённое состояние при запуске: %s", e)

    logger.info("✅ Бот для канала запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
