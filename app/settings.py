"""Налаштування застосунку.

Сумісне з попереднім проєктом: значення беруться з `config.py` (якщо є),
інакше — зі змінних оточення. Файл config.py лишається у .gitignore.
"""
import os

try:  # локально/на проді часто є config.py поруч
    import config as _cfg  # type: ignore
except ImportError:  # на Render можна задати все через env
    _cfg = None


def _get(name: str, default=None):
    if _cfg is not None and hasattr(_cfg, name):
        return getattr(_cfg, name)
    return os.environ.get(name, default)


# ── Telegram ──
TOKEN = _get("TOKEN")

# ── Google Sheets ──
GOOGLE_SHEETS_CREDENTIALS = _get("GOOGLE_SHEETS_CREDENTIALS")  # шлях до service-account .json
# Альтернатива для хмари (Render): сам вміст JSON-ключа у змінній оточення.
GOOGLE_SHEETS_CREDENTIALS_JSON = _get("GOOGLE_SHEETS_CREDENTIALS_JSON")
GOOGLE_SHEET_URL = _get("GOOGLE_SHEET_URL")                    # таблиця ТТН
GOOGLE_SHEET_URL_USERS = _get("GOOGLE_SHEET_URL_USERS")        # таблиця користувачів

# ── Інфраструктура ──
PORT = int(_get("PORT", 8080))           # keep-alive порт для Render
TIMEZONE = "Europe/Kiev"
BUFFER_DELAY_SECONDS = 5                  # затримка акумуляції буфера (Склад)
ADMIN_NOTIFY_INTERVAL_MINUTES = 10       # дедуплікація однакових алертів

# ── Debug ──
# Тимчасово зберігати вхідні фото на диск для офлайн-налаштування сканера.
DEBUG_SAVE_IMAGES = str(_get("DEBUG_SAVE_IMAGES", "0")).lower() in ("1", "true", "yes")
DEBUG_IMAGE_DIR = "debug_images"
