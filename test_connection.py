# test_connection.py
import google_sheets_service_account as gs
import logging

logging.basicConfig(level=logging.INFO)

try:
    # Пробуем загрузить данные
    df = gs.load_subscribers_df()
    print(f"✅ Успешное подключение! Загружено записей: {len(df)}")

    # Пробуем сохранить тестовые данные (исправлено имя функции)
    gs.save_subscribers_df(df)  # просто сохраняем как есть
    print("✅ Сохранение работает!")

    # Тестируем создание тестового пользователя
    test_user_id = 123456789
    created = gs.save_subscriber_to_sheet(
        user_id=test_user_id,
        username="test_user",
        full_name="Test User",
        promo_code="TEST123",
        issued_by="test"
    )
    print(f"✅ Тестовый пользователь создан: {created}")

    # Удаляем тестового пользователя
    df = gs.load_subscribers_df()
    df = df[df["user_id"] != test_user_id]
    gs.save_subscribers_df(df)
    print("✅ Тестовый пользователь удален")

except Exception as e:
    print(f"❌ Ошибка подключения: {e}")
    import traceback
    traceback.print_exc()
