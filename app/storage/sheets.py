"""Обгортка над двома Google-таблицями (gspread + google-auth).

Усі методи синхронні/блокуючі — викликати з async-коду через
asyncio.to_thread(...). Містить також мости Google <-> локальний CSV-кеш.
"""
import json
import logging
import os

import gspread
from google.oauth2.service_account import Credentials

from .. import settings
from . import local_cache as lc

log = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _load_credentials() -> Credentials:
    """Креди з env-змінної (вміст JSON) або з файлу за шляхом."""
    raw = settings.GOOGLE_SHEETS_CREDENTIALS_JSON
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)
    path = settings.GOOGLE_SHEETS_CREDENTIALS
    if path:
        # Render монтує Secret Files у /etc/secrets/ — пробуємо і там за іменем файлу.
        for candidate in (path, os.path.join(settings.SECRETS_DIR, os.path.basename(path))):
            if os.path.exists(candidate):
                return Credentials.from_service_account_file(candidate, scopes=_SCOPES)
    raise RuntimeError(
        "Не задано облікові дані Google. Вкажіть GOOGLE_SHEETS_CREDENTIALS_JSON "
        "(вміст JSON-ключа, зручно для Render) або GOOGLE_SHEETS_CREDENTIALS (шлях до файлу)."
    )


class Sheets:
    def __init__(self) -> None:
        self.client = None
        self.ttn = None      # worksheet таблиці ТТН
        self.users = None    # worksheet таблиці користувачів

    def connect(self) -> None:
        creds = _load_credentials()
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
