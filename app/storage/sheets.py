"""Обгортка над двома Google-таблицями (gspread + google-auth).

Усі методи синхронні/блокуючі — викликати з async-коду через
asyncio.to_thread(...). Містить також мости Google <-> локальний CSV-кеш.
"""
import logging

import gspread
from google.oauth2.service_account import Credentials

from .. import settings
from . import local_cache as lc

log = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class Sheets:
    def __init__(self) -> None:
        self.client = None
        self.ttn = None      # worksheet таблиці ТТН
        self.users = None    # worksheet таблиці користувачів

    def connect(self) -> None:
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_SHEETS_CREDENTIALS, scopes=_SCOPES
        )
        self.client = gspread.authorize(creds)
        self.ttn = self.client.open_by_url(settings.GOOGLE_SHEET_URL).sheet1
        self.users = self.client.open_by_url(settings.GOOGLE_SHEET_URL_USERS).sheet1
        log.info("Google Sheets connected.")

    # ── таблиця ТТН ──
    def push_warehouse_to_google(self) -> None:
        """Пушить локальні warehouse-рядки з індексом більшим за останній у Google."""
        records = self.ttn.get_all_values()
        last_google_row = len(records)  # враховуючи заголовок
        _, warehouse_rows = lc.read_csv_file(lc.LOCAL_WAREHOUSE_FILE)
        for entry in warehouse_rows:
            try:
                row_num = int(entry["row"])
            except (KeyError, ValueError):
                continue
            if row_num > last_google_row:
                self.ttn.append_row([entry["TTN"], entry["Date"], entry["Username"]])
                log.info("Pushed TTN %s (row %s) to Google Sheet.", entry["TTN"], row_num)

    def pull_office_to_local(self) -> None:
        lc.write_csv_file(lc.LOCAL_OFFICE_FILE, lc.OFFICE_HEADERS, self._ttn_rows())

    def pull_warehouse_to_local(self) -> None:
        lc.write_csv_file(lc.LOCAL_WAREHOUSE_FILE, lc.WAREHOUSE_HEADERS, self._ttn_rows())

    def _ttn_rows(self):
        records = self.ttn.get_all_values()  # включно із заголовком
        rows = []
        for i, row in enumerate(records, start=1):
            if i == 1:
                continue  # пропускаємо заголовок
            rows.append({
                "row": str(i),
                "TTN": row[0] if len(row) > 0 else "",
                "Date": row[1] if len(row) > 1 else "",
                "Username": row[2] if len(row) > 2 else "",
            })
        return rows

    def clear_ttn(self) -> None:
        """Очищає таблицю ТТН, лишаючи заголовок (форматування не чіпаємо)."""
        header = self.ttn.row_values(1)
        self.ttn.clear()
        self.ttn.append_row(header)
        log.info("Google Sheet TTN cleared.")

    # ── таблиця користувачів ──
    def get_users_values(self):
        return self.users.get_all_values()

    def find_user_row(self, tg_id: str):
        rows = self.users.get_all_values()
        for i, row in enumerate(rows, start=1):
            if row and row[0] == tg_id:
                return i
        return None

    def upsert_user(self, tg_id, role, username, report_time, last_sent) -> None:
        row_index = self.find_user_row(tg_id)
        if row_index is None:
            next_row = len(self.users.get_all_values()) + 1
            self.users.update(
                f"A{next_row}:F{next_row}",
                [[tg_id, role, username, report_time, last_sent, ""]],
            )
        else:
            current = self.users.row_values(row_index)
            admin_value = current[5] if len(current) >= 6 else ""
            self.users.update(
                f"A{row_index}:F{row_index}",
                [[tg_id, role, username, report_time, last_sent, admin_value]],
            )
