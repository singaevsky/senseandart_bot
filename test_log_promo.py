# test_log_promo.py
import logging
import traceback
import google_sheets_service_account as gs

logging.basicConfig(level=logging.INFO)

TEST_USER_ID = 999999999
TEST_PROMO = "TEST-LOG-001"

print("Запускается тест log_promo_issue()...")
try:
    gs.log_promo_issue(TEST_USER_ID, TEST_PROMO)
    print("✅ Вызов log_promo_issue завершён (проверьте Google Sheets на наличие листа 'promo_log').")
except Exception as e:
    print(f"❌ Исключение при вызове log_promo_issue: {e}")
    traceback.print_exc()
