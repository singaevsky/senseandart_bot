import json
import os
from typing import Dict

LOCALES_DIR = "locales"
DEFAULT_LANG = "ru"
_LOCALES_CACHE: Dict[str, Dict] = {}


def load_locale(lang: str) -> Dict:
    if lang in _LOCALES_CACHE:
        return _LOCALES_CACHE[lang]
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    if not os.path.exists(path):
        lang = DEFAULT_LANG
        path = os.path.join(LOCALES_DIR, f"{DEFAULT_LANG}.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _LOCALES_CACHE[lang] = data
    return data


def detect_lang(telegram_lang_code: str | None) -> str:
    code = telegram_lang_code or "ru"
    if code.startswith("ru"):
        return "ru"
    if code.startswith("en"):
        return "en"
    return DEFAULT_LANG


def t(lang: str, key: str, **kwargs) -> str:
    data = load_locale(lang)
    template = data.get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template
