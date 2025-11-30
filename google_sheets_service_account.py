# google_sheets_service_account.py
import logging
import os
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import gspread
from google.oauth2 import service_account

import config

logger = logging.getLogger(__name__)

# Scopes для работы с Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Файл с ключом сервисного аккаунта
SERVICE_ACCOUNT_FILE = config.GOOGLE_CREDENTIALS_FILE


def print_config_debug():
    """Выводит диагностическую информацию о конфигурации Google Sheets."""
    sa_file = config.GOOGLE_CREDENTIALS_FILE
    abs_path = os.path.abspath(sa_file)
    exists = os.path.exists(abs_path)
    print("\n=== Google Sheets Configuration Debug (Service Account) ===")
    print(f"Google Sheets ID: {config.GOOGLE_SHEETS_ID}")
    print(f"Service account file: {sa_file}")
    print(f"Absolute path: {abs_path}")
    print(f"File exists: {exists}")

    if exists:
        try:
            import json
            with open(abs_path, 'r') as f:
                data = json.load(f)
                print(f"Service account email: {data.get('client_email', 'NOT FOUND')}")
                print(f"Project ID: {data.get('project_id', 'NOT FOUND')}")
                print(f"Type: {data.get('type', 'NOT FOUND')}")
        except Exception as e:
            print(f"Error reading JSON: {e}")

    print(f"Current working directory: {os.getcwd()}")
    print(f"Directory contents: {os.listdir(os.getcwd())}")
    print("=" * 60)


def _get_gspread_client() -> gspread.Client:
    """
    Аутентификация через service account с проверкой файла.
    """
    sa_file = config.GOOGLE_CREDENTIALS_FILE

    # Проверяем существование файла
    if not os.path.exists(sa_file):
        print_config_debug()
        raise RuntimeError(
            f"❌ Файл сервисного аккаунта не найден: {os.path.abspath(sa_file)}"
            "\n📋 Для настройки Service Account:"
            "1. Обратитесь к администратору Google Workspace"
            "2. Получите JSON файл service account"
            "3. Сохраните его как credentials.json в корне проекта"
            "4. Добавьте service account email в таблицу Google Sheets с правами редактора"
        )

    try:
        # Проверяем формат файла
        import json
        with open(sa_file, 'r') as f:
            data = json.load(f)

        if data.get('type') != 'service_account':
            print_config_debug()
            raise ValueError(
                "❌ Неверный формат файла. Файл должен быть JSON service account, не OAuth."
                "\n🔍 Проверьте, что в файле есть поле 'type': 'service_account'"
            )

        # Создаем credentials из service account файла
        credentials = service_account.Credentials.from_service_account_file(
            sa_file, scopes=SCOPES
        )

        # Создаем клиент gspread
        gc = gspread.authorize(credentials)
        logger.info("✅ Успешное подключение к Google Sheets через Service Account")
        return gc

    except Exception as e:
        print_config_debug()

        # Анализируем тип ошибки
        if "permission_denied" in str(e).lower():
            error_msg = (
                "❌ Ошибка доступа к Google Sheets"
                "\n🔧 Решение:"
                "1. Добавьте email сервисного аккаунта в таблицу Google Sheets"
                "2. Предоставьте права редактора (Editor)"
                "3. Проверьте, что таблица доступна по ссылке"
            )
        elif "invalid_grant" in str(e).lower():
            error_msg = (
                "❌ Недействительные учетные данные"
                "\n🔧 Решение:"
                "1. Проверьте, что JSON файл не поврежден"
                "2. Убедитесь, что service account активен"
                "3. Проверьте права доступа"
            )
        else:
            error_msg = (
                f"❌ Ошибка подключения к Google Sheets: {e}"
                "\n🔧 Общие решения:"
                "1. Проверьте правильность пути к файлу"
                "2. Убедитесь, что Google Sheets API включен"
                "3. Проверьте сетевое соединение"
            )

        raise RuntimeError(error_msg) from e


def _open_sheet(gc: Optional[gspread.Client] = None) -> gspread.Spreadsheet:
    """Открывает таблицу Google Sheets с поддержкой разных версий gspread."""
    if gc is None:
        gc = _get_gspread_client()

    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}"

    # Пробуем разные методы открытия в зависимости от версии gspread
    methods_to_try = [
        # Метод 1: open_by_url (рекомендуемый для новых версий)
        lambda: gc.open_by_url(spreadsheet_url),

        # Метод 2: open_by с ключом (для некоторых версий)
        lambda: gc.open_by(config.GOOGLE_SHEETS_ID),

        # Метод 3: open с полным URL (для очень старых версий)
        lambda: gc.open(spreadsheet_url),

        # Метод 4: open с ID
        lambda: gc.open(config.GOOGLE_SHEETS_ID),
    ]

    for i, method in enumerate(methods_to_try, 1):
        try:
            spreadsheet = method()
            logger.info(f"✅ Таблица открыта методом {i}: {config.GOOGLE_SHEETS_ID}")
            return spreadsheet
        except Exception as e:
            logger.warning(f"⚠️ Метод {i} не сработал: {e}")
            continue

    # Если ни один метод не сработал
    raise RuntimeError(
        f"❌ Не удалось открыть таблицу ни одним из доступных методов.\n"
        f"🔍 ID таблицы: {config.GOOGLE_SHEETS_ID}\n"
        f"🔗 URL: {spreadsheet_url}\n"
        f"🔧 Возможные решения:\n"
        f"1. Проверьте правильность ID таблицы\n"
        f"2. Обновите gspread: pip install --upgrade gspread\n"
        f"3. Проверьте права доступа service account"
    )


def _sheet(gc: Optional[gspread.Client] = None) -> gspread.Worksheet:
    """Получает рабочий лист из таблицы."""
    sp = _open_sheet(gc)
    try:
        worksheet = sp.worksheet(config.SHEET_NAME)
        logger.info(f"✅ Лист найден: {config.SHEET_NAME}")
        return worksheet
    except gspread.WorksheetNotFound:
        logger.warning(f"⚠️ Лист '{config.SHEET_NAME}' не найден. Создаю новый...")
        try:
            worksheet = sp.add_worksheet(
                title=config.SHEET_NAME,
                rows="1000",
                cols="10"
            )
            logger.info(f"✅ Создан новый лист: {config.SHEET_NAME}")
            return worksheet
        except Exception as e:
            logger.error(f"❌ Ошибка создания листа: {e}")
            raise RuntimeError(f"❌ Не удалось создать лист '{config.SHEET_NAME}': {e}") from e


def _ensure_header(worksheet: gspread.Worksheet) -> List[str]:
    """Убеждается, что в листе есть необходимые заголовки."""
    expected = [
        "user_id",
        "username",
        "full_name",
        "joined_at",
        "promo_code",
        "status",
        "unsubscribed_at",
    ]

    try:
        hdr = worksheet.row_values(1)
        logger.info(f"📋 Текущие заголовки: {hdr}")
    except Exception:
        hdr = []
        logger.warning("⚠️ Не удалось получить заголовки")

    if not hdr:
        try:
            worksheet.append_row(expected)
            logger.info(f"✅ Создан заголовок: {expected}")
            return expected
        except Exception as e:
            logger.error(f"❌ Ошибка создания заголовка: {e}")
            raise RuntimeError(f"❌ Не удалось создать заголовок: {e}") from e

    # Проверяем наличие всех необходимых колонок
    missing_cols = []
    for col in expected:
        if col not in hdr:
            missing_cols.append(col)

    # Дополняем заголовок недостающими колонками
    if missing_cols:
        try:
            worksheet.append_row(missing_cols)
            logger.info(f"✅ Добавлены колонки: {missing_cols}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось добавить колонки: {e}")

    # Возвращаем обновленные заголовки
    try:
        updated_headers = worksheet.row_values(1)
        logger.info(f"📋 Обновленные заголовки: {updated_headers}")
        return updated_headers
    except Exception as e:
        logger.error(f"❌ Ошибка получения заголовков: {e}")
        return hdr


def _dataframe_from_rows(rows: List[List], header: List[str]) -> pd.DataFrame:
    """Конвертирует данные из таблицы в DataFrame."""
    # Убираем полностью пустые строки
    cleaned_rows = [r for r in rows if any(str(v).strip() for v in r)]

    if not cleaned_rows:
        logger.info("📭 Таблица пуста")
        return pd.DataFrame(columns=header)

    df = pd.DataFrame(cleaned_rows, columns=header)

    if not df.empty:
        # Преобразуем user_id в числовой формат
        df["user_id"] = pd.to_numeric(df["user_id"], errors="coerce").astype("Int64")
        # Обрабатываем промокод
        df["promo_code"] = df["promo_code"].apply(lambda x: x if str(x).strip() else None)

    logger.info(f"📊 Загружено записей: {len(df)}")
    return df


def _rows_from_dataframe(df: pd.DataFrame, header: List[str]) -> List[List]:
    """Конвертирует DataFrame в формат для записи в таблицу."""
    # Дополняем недостающие колонки пустыми значениями
    for col in header:
        if col not in df.columns:
            df[col] = ""

    # Упорядочиваем колонки
    df = df[header]

    # Приводим user_id к строковому формату для записи
    if "user_id" in df.columns:
        df["user_id"] = (
            df["user_id"]
            .astype("Int64")
            .astype(str)
            .replace("<NA>", "")
        )

    return df.values.tolist()


def load_subscribers_df() -> pd.DataFrame:
    """Загружает данные подписчиков из Google Sheets."""
    try:
        gc = _get_gspread_client()
        ws = _sheet(gc)
        header = _ensure_header(ws)

        all_values = ws.get_all_values()

        if not all_values:
            logger.info("📭 Таблица пуста (нет данных)")
            return pd.DataFrame(columns=header)

        # Первая строка — заголовок, данные начинаются со второй
        data_rows = all_values[1:] if len(all_values) > 1 else []
        df = _dataframe_from_rows(data_rows, header)

        return df

    except Exception as e:
        logger.error(f"❌ Ошибка чтения Google Sheets: {e}")
        # Возвращаем пустой DataFrame с правильными колонками
        return pd.DataFrame(columns=[
            "user_id", "username", "full_name", "joined_at",
            "promo_code", "status", "unsubscribed_at"
        ])


def save_subscribers_df(df: pd.DataFrame):
    """Сохраняет данные подписчиков в Google Sheets."""
    try:
        gc = _get_gspread_client()
        ws = _sheet(gc)
        header = _ensure_header(ws)

        rows = _rows_from_dataframe(df, header)

        # Очищаем лист и записываем данные заново
        ws.clear()
        ws.append_row(header)

        if rows:  # Записываем данные только если они есть
            ws.append_rows(rows)
            logger.info(f"✅ Записано строк в Google Sheets: {len(rows)}")
        else:
            logger.info("📭 Нет данных для записи")

    except Exception as e:
        logger.error(f"❌ Ошибка записи в Google Sheets: {e}")
        raise RuntimeError(f"❌ Не удалось сохранить данные: {e}") from e


def user_row(user_id: int) -> Optional[pd.Series]:
    """Находит запись пользователя по ID."""
    df = load_subscribers_df()
    if df.empty:
        logger.info(f"🔍 Пользователь {user_id}: таблица пуста")
        return None

    mask = df["user_id"] == user_id
    if mask.any():
        user_data = df[mask].iloc[0]
        logger.info(f"✅ Пользователь {user_id} найден в таблице")
        return user_data
    else:
        logger.info(f"🔍 Пользователь {user_id} не найден в таблице")
        return None


def user_has_promo(user_id: int) -> Tuple[bool, Optional[str]]:
    """Проверяет, есть ли у пользователя промокод."""
    row = user_row(user_id)
    if row is None:
        return False, None
    promo = row.get("promo_code") or None
    has_promo = bool(promo)

    if has_promo:
        logger.info(f"🎁 У пользователя {user_id} есть промокод: {promo}")
    else:
        logger.info(f"❌ У пользователя {user_id} нет промокода")

    return has_promo, promo


def save_subscriber_to_sheet(
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    promo_code: str,
) -> bool:
    """
    Сохраняет подписчика в таблицу (upsert).
    Возвращает True, если это новая запись.
    """
    try:
        df = load_subscribers_df()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        idx = df.index[df["user_id"] == user_id]

        if len(idx) == 0:
            # Новая запись
            new_row = pd.Series({
                "user_id": user_id,
                "username": username or "",
                "full_name": full_name or "",
                "joined_at": now_str,
                "promo_code": promo_code,
                "status": "подписан",
                "unsubscribed_at": "",
            })
            df = pd.concat([df, new_row.to_frame().T], ignore_index=True)
            save_subscribers_df(df)
            logger.info(f"🆕 Новый подписчик добавлен: {user_id} (@{username})")
            return True
        else:
            # Обновление существующей записи
            i = idx[0]

            if pd.isna(df.at[i, "username"]) or df.at[i, "username"] == "":
                df.at[i, "username"] = username or ""
            if pd.isna(df.at[i, "full_name"]) or df.at[i, "full_name"] == "":
                df.at[i, "full_name"] = full_name or ""
            if pd.isna(df.at[i, "promo_code"]) or df.at[i, "promo_code"] == "":
                df.at[i, "promo_code"] = promo_code
            df.at[i, "status"] = "подписан"
            if pd.isna(df.at[i, "joined_at"]) or df.at[i, "joined_at"] == "":
                df.at[i, "joined_at"] = now_str
            df.at[i, "unsubscribed_at"] = ""

            save_subscribers_df(df)
            logger.info(f"🔄 Обновлена запись пользователя: {user_id}")
            return False

    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")
        raise RuntimeError(f"❌ Не удалось сохранить пользователя: {e}") from e


def mark_unsubscribed(user_id: int) -> bool:
    """Отмечает пользователя как отписавшегося."""
    try:
        df = load_subscribers_df()
        if df.empty:
            logger.warning(f"⚠️ Попытка отписать несуществующего пользователя: {user_id}")
            return False

        idx = df.index[df["user_id"] == user_id]

        if len(idx) == 0:
            logger.warning(f"⚠️ Пользователь {user_id} не найден для отписки")
            return False

        i = idx[0]
        prev_status = df.at[i, "status"]
        if prev_status == "отписан":
            logger.info(f"ℹ️ Пользователь {user_id} уже отписан")
            return False

        df.at[i, "status"] = "отписан"
        df.at[i, "unsubscribed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_subscribers_df(df)
        logger.info(f"👋 Пользователь отписан: {user_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка отписки пользователя {user_id}: {e}")
        return False


def mark_subscribed_if_exists(user_id: int) -> None:
    """Обновляет статус пользователя на 'подписан'."""
    try:
        df = load_subscribers_df()
        if df.empty:
            logger.info(f"ℹ️ Нет данных для обновления статуса пользователя {user_id}")
            return

        idx = df.index[df["user_id"] == user_id]

        if len(idx) == 0:
            logger.info(f"ℹ️ Пользователь {user_id} не найден для обновления статуса")
            return

        i = idx[0]
        if df.at[i, "status"] != "подписан":
            df.at[i, "status"] = "подписан"
            save_subscribers_df(df)
            logger.info(f"✅ Статус обновлен на 'подписан': {user_id}")
        else:
            logger.info(f"ℹ️ Пользователь {user_id} уже имеет статус 'подписан'")

    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса пользователя {user_id}: {e}")
