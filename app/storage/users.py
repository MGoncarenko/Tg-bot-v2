"""Репозиторій користувачів (кеш у пам'яті + Google Sheets) та адмін-сповіщення.

Схема таблиці користувачів (як у попередній версії):
  A tg_id | B role | C username | D report_time | E last_sent | F admin
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import settings
from .sheets import Sheets

log = logging.getLogger(__name__)


@dataclass
class User:
    role: str = ""
    username: str = ""
    time: str = ""        # report_time HH:MM, "" якщо не підписаний
    last_sent: str = ""   # YYYY-MM-DD останнього звіту
    admin: bool = False


class UserRepository:
    def __init__(self, sheets: Sheets) -> None:
        self.sheets = sheets
        self.cache: dict[str, User] = {}

    async def load(self) -> None:
        self.cache = await asyncio.to_thread(self._read_all)
        log.info("Users cache loaded. Total users: %d", len(self.cache))

    def _read_all(self) -> dict[str, User]:
        data: dict[str, User] = {}
        try:
            rows = self.sheets.get_users_values()
        except Exception as e:
            log.error("Error reading users data: %s", e)
            return data
        for row in rows[1:]:  # пропускаємо заголовок
            if not row or not row[0]:
                continue
            # gspread обрізає порожні хвостові клітинки -> доповнюємо до 6 колонок
            row = list(row) + [""] * (6 - len(row))
            data[row[0]] = User(
                role=row[1],
                username=row[2],
                time=row[3],
                last_sent=row[4],
                admin=(row[5].strip().lower() == "admin"),
            )
        return data

    def get(self, tg_id: str) -> User:
        return self.cache.get(tg_id, User())

    def admin_ids(self) -> list[str]:
        return [tg_id for tg_id, u in self.cache.items() if u.admin]

    async def update(self, tg_id, role, username, report_time, last_sent="") -> None:
        await asyncio.to_thread(
            self.sheets.upsert_user, tg_id, role, username, report_time, last_sent
        )
        existing = self.cache.get(tg_id)
        self.cache[tg_id] = User(
            role=role,
            username=username,
            time=report_time,
            last_sent=last_sent,
            admin=existing.admin if existing else False,
        )


class AdminNotifier:
    """Шле адмінам алерти з дедуплікацією однакових повідомлень."""

    def __init__(self, bot, users: UserRepository) -> None:
        self.bot = bot
        self.users = users
        self._last: dict[str, datetime] = {}

    async def notify(self, message: str) -> None:
        now = datetime.now()
        interval = timedelta(minutes=settings.ADMIN_NOTIFY_INTERVAL_MINUTES)
        last = self._last.get(message)
        if last and now - last < interval:
            return
        self._last[message] = now
        admin_ids = self.users.admin_ids()
        if not admin_ids:
            log.warning("No admin IDs available to notify: %s", message)
            return
        for admin_id in admin_ids:
            try:
                await self.bot.send_message(admin_id, f"[ALERT] {message}")
            except Exception as e:
                log.error("Failed to notify admin %s: %s", admin_id, e)
