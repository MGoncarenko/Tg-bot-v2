"""Entrypoint: ініціалізація залежностей, старт web + scheduler + polling."""
import asyncio
import logging

from . import settings
from .bot import create_bot, create_dispatcher
from .scheduler import setup_scheduler
from .services.reports import ReportService
from .services.ttn import TTNService
from .storage import local_cache as lc
from .storage.sheets import Sheets
from .storage.users import AdminNotifier, UserRepository
from .web import start_web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    if not settings.TOKEN:
        raise SystemExit(
            "TOKEN не задано. Задайте змінну оточення TOKEN (Render) "
            "або створіть config.py із config.example.py."
        )
    lc.ensure_local_files()
    bot = create_bot()

    # ── Google Sheets ──
    sheets = Sheets()
    try:
        await asyncio.to_thread(sheets.connect)
    except Exception as e:
        log.exception("Initial Google Sheets connect failed: %s", e)

    users = UserRepository(sheets)
    await users.load()  # _read_all сам гасить помилки -> порожній кеш при збої

    notifier = AdminNotifier(bot, users)
    ttn = TTNService(bot, sheets, notifier)
    reports = ReportService(bot, sheets, users, notifier)

    # початкове наповнення локальних файлів із Google
    try:
        await asyncio.to_thread(sheets.pull_office_to_local)
        await asyncio.to_thread(sheets.pull_warehouse_to_local)
    except Exception as e:
        log.exception("Init data load failed: %s", e)
        await notifier.notify(f"Init data load failed: {e}")

    admins = users.admin_ids()
    log.info("Loaded admin IDs: %s", admins or "none")

    # ── діспетчер + ін'єкція залежностей у хендлери ──
    dp = create_dispatcher()
    dp["users"] = users
    dp["ttn"] = ttn
    dp["notifier"] = notifier

    # ── фонові сервіси ──
    scheduler = setup_scheduler(reports)
    scheduler.start()
    runner = await start_web(settings.PORT)
    log.info("Keep-alive web server started on port %s", settings.PORT)

    try:
        log.info("Starting Telegram polling...")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
