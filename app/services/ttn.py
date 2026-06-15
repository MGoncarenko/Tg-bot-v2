"""Логіка ролей та буфер Складу (порт із попередньої версії, потоки -> asyncio).

Роль "Склад": ТТН -> буфер; через BUFFER_DELAY_SECONDS пакет переноситься в
warehouse, пушиться в Google, оновлюється office, і користувачу шлеться
перелік "Додано / Не додано".
Роль "Офіс": миттєвий пошук ТТН у локальному office-кеші.
"""
import asyncio
import logging
import re

from .. import settings
from ..storage import local_cache as lc
from ..storage.sheets import Sheets
from ..storage.users import AdminNotifier

log = logging.getLogger(__name__)


def extract_ttn(raw: str) -> str | None:
    """Дістає ТТН-номер зі сканованого/введеного тексту або повертає None.

    Приймає два формати, зберігаючи лише цифри:
      - 10–18 цифр — ТТН Нової Пошти (напр. 20451362097883);
      - код маркетплейсу з префіксом PRM (напр. PRM-404287373) -> 404287373.
    Префікс PRM однозначно вирізняє «короткий» код, тож для нього довжина м'якша.
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if 10 <= len(digits) <= 18:
        return digits
    if re.search(r"PRM", raw, re.IGNORECASE) and 6 <= len(digits) <= 18:
        return digits
    return None


class TTNService:
    def __init__(self, bot, sheets: Sheets, notifier: AdminNotifier) -> None:
        self.bot = bot
        self.sheets = sheets
        self.notifier = notifier
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task | None = None

    async def handle_ttn(self, chat_id: str, ttn: str, username: str, role: str) -> None:
        if role == "Склад":
            await asyncio.to_thread(lc.add_ttn_to_buffer, ttn, username)
            self._start_buffer_timer(chat_id)
        elif role == "Офіс":
            await self._check_office(chat_id, ttn)
        else:
            await self.bot.send_message(
                chat_id, "Спочатку встановіть роль за допомогою /Office або /Cklad"
            )

    # ── Офіс ──
    async def _check_office(self, chat_id: str, ttn: str) -> None:
        row = await asyncio.to_thread(lc.find_office_row, ttn)
        if row is not None:
            await self.bot.send_message(chat_id, f"✅TTН {ttn} на рядку {row}.")
        else:
            await self.bot.send_message(chat_id, f"❌TTН {ttn} не знайдено.")

    # ── Склад: буфер ──
    def _start_buffer_timer(self, chat_id: str) -> None:
        """Один активний таймер (як у попередній версії)."""
        if self._timer_task is None or self._timer_task.done():
            self._timer_task = asyncio.create_task(self._buffer_timer(chat_id))

    async def _buffer_timer(self, chat_id: str) -> None:
        await asyncio.sleep(settings.BUFFER_DELAY_SECONDS)
        try:
            await self._process_buffer(chat_id)
        except Exception as e:
            log.exception("Buffer processing failed: %s", e)
            await self.notifier.notify(f"Buffer processing failed: {e}")

    async def _process_buffer(self, chat_id: str) -> None:
        async with self._lock:
            try:
                await asyncio.to_thread(self._sync_buffer_to_google)
            except Exception as e:
                log.warning("Google Sheets query failed, comparing local files: %s", e)
                await self._offline_diff()

            added, not_added = await asyncio.to_thread(lc.compare_buffer_with_office)
            msg = "Оновлення:\n"
            if added:
                msg += "Додано:\n" + "\n".join(added) + "\n"
            if not_added:
                msg += "Не додано:\n" + "\n".join(not_added)
            await self.bot.send_message(chat_id, msg)
            await asyncio.to_thread(lc.clear_buffer)
            log.info("Buffer cleared.")

    def _sync_buffer_to_google(self) -> None:
        """Блокуючий ланцюжок: buffer -> warehouse -> Google -> office."""
        lc.merge_buffer_into_warehouse()
        self.sheets.push_warehouse_to_google()
        self.sheets.pull_office_to_local()

    async def _offline_diff(self) -> None:
        missing = await asyncio.to_thread(lc.warehouse_office_diff)
        if missing:
            await asyncio.to_thread(lc.write_diff_file, missing)
            await self.notifier.notify(
                f"Failed to update from Google Sheets. Missing TTНs: {missing}. "
                f"See attached file {lc.DIFF_FILE}."
            )
