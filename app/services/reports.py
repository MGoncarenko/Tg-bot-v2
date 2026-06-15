"""Щоденні звіти підписникам, добова очистка таблиці ТТН та reconnect Sheets.

Викликається планувальником (APScheduler). Порт із попередньої версії, але:
  - читаємо підписників із кешу users (а не щохвилини з мережі);
  - очистку о 00:00 робить cron-розклад, тут лише саме очищення.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import settings
from ..storage import local_cache as lc
from ..storage.sheets import Sheets
from ..storage.users import AdminNotifier, UserRepository

log = logging.getLogger(__name__)
_KIEV = ZoneInfo(settings.TIMEZONE)


class ReportService:
    def __init__(self, bot, sheets: Sheets, users: UserRepository, notifier: AdminNotifier) -> None:
        self.bot = bot
        self.sheets = sheets
        self.users = users
        self.notifier = notifier

    async def send_subscriptions(self) -> None:
        """Щохвилини: кому настав час підписки — шлемо звіт раз на день."""
        now = datetime.now(_KIEV)
        current_time = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        for chat_id, info in list(self.users.cache.items()):
            if not info.time or info.time != current_time or info.last_sent == today:
                continue
            try:
                count = await asyncio.to_thread(lc.count_office_ttn)
            except Exception as e:
                count = "Невідомо (помилка)"
                await self.notifier.notify(f"Error counting TTН for chat {chat_id}: {e}")
            await self.bot.send_message(chat_id, f"За сьогодні оброблено TTН: {count}")
            await self.users.update(chat_id, info.role, info.username, info.time, today)

    async def clear_ttn(self) -> None:
        """Cron 00:00 (Київ): очистити таблицю ТТН і локальні файли."""
        try:
            await asyncio.to_thread(self.sheets.clear_ttn)
        except Exception as e:
            log.error("Error clearing Google Sheet TTN: %s", e)
            await self.notifier.notify(f"Error clearing Google Sheet TTN: {e}")
        await asyncio.to_thread(lc.clear_ttn_locals)

    async def reconnect(self) -> None:
        """Щогодини: переконект до Sheets + перезавантаження кешів."""
        try:
            await asyncio.to_thread(self.sheets.connect)
            await self.users.load()
            await asyncio.to_thread(self.sheets.pull_office_to_local)
            await asyncio.to_thread(self.sheets.pull_warehouse_to_local)
            log.info("Google Sheets reconnected.")
        except Exception as e:
            log.error("Error reconnecting Google Sheets: %s", e)
            await self.notifier.notify(f"Error reconnecting Google Sheets: {e}")
