"""Локальний CSV-кеш — офлайн-фолбек на випадок нестабільності Render/Sheets.

Три файли (як у попередній версії):
  - local_office.csv     дзеркало таблиці ТТН для швидкого пошуку (роль Офіс)
  - local_warehouse.csv  стейджинг із індексацією row перед пушем у Google (роль Склад)
  - local_buffer.csv     ТТН, що чекають 5-секундної пакетної обробки

Усі функції тут — синхронний файловий IO. З async-коду викликати через
asyncio.to_thread(...).
"""
import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import settings

LOCAL_OFFICE_FILE = "local_office.csv"
LOCAL_WAREHOUSE_FILE = "local_warehouse.csv"
LOCAL_BUFFER_FILE = "local_buffer.csv"
DIFF_FILE = "diff_missing.csv"

OFFICE_HEADERS = ["row", "TTN", "Date", "Username"]
WAREHOUSE_HEADERS = ["row", "TTN", "Date", "Username"]
BUFFER_HEADERS = ["TTN", "Username"]

_KIEV = ZoneInfo(settings.TIMEZONE)


# ── базові операції ──
def ensure_local_files() -> None:
    for fname, hdr in (
        (LOCAL_OFFICE_FILE, OFFICE_HEADERS),
        (LOCAL_WAREHOUSE_FILE, WAREHOUSE_HEADERS),
        (LOCAL_BUFFER_FILE, BUFFER_HEADERS),
    ):
        if not os.path.exists(fname):
            with open(fname, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(hdr)


def read_csv_file(filename: str):
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames, list(reader)
    except Exception:
        return None, []


def write_csv_file(filename: str, headers, rows) -> None:
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def append_csv_row(filename: str, row, headers) -> None:
    with open(filename, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=headers).writerow(row)


# ── буфер (Склад) ──
def add_ttn_to_buffer(ttn: str, username: str) -> None:
    """Додає ТТН+Username до буфера, якщо ще немає."""
    _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
    existing = {r["TTN"] for r in buffer_rows}
    if ttn not in existing:
        append_csv_row(LOCAL_BUFFER_FILE, {"TTN": ttn, "Username": username}, BUFFER_HEADERS)


def clear_buffer() -> None:
    write_csv_file(LOCAL_BUFFER_FILE, BUFFER_HEADERS, [])


def merge_buffer_into_warehouse() -> None:
    """Переносить нові ТТН з буфера у warehouse із продовженням індексації row."""
    _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
    _, warehouse_rows = read_csv_file(LOCAL_WAREHOUSE_FILE)
    existing = {r["TTN"] for r in warehouse_rows}
    next_row = max((int(r["row"]) for r in warehouse_rows), default=1) + 1
    for entry in buffer_rows:
        ttn = entry["TTN"]
        if ttn not in existing:
            now = datetime.now(_KIEV).strftime("%H:%M:%S")
            append_csv_row(
                LOCAL_WAREHOUSE_FILE,
                {"row": str(next_row), "TTN": ttn, "Date": now, "Username": entry.get("Username", "")},
                WAREHOUSE_HEADERS,
            )
            existing.add(ttn)
            next_row += 1


# ── пошук/порівняння (Офіс) ──
def find_office_row(ttn: str):
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    for row in office_rows:
        if row["TTN"] == ttn:
            return row["row"]
    return None


def compare_buffer_with_office():
    """Повертає (added, not_added) — ТТН з буфера, що (не)потрапили в office."""
    _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    office_ttns = {r["TTN"] for r in office_rows}
    added, not_added = [], []
    for entry in buffer_rows:
        (added if entry["TTN"] in office_ttns else not_added).append(entry["TTN"])
    return added, not_added


def warehouse_office_diff():
    """ТТН, що є в warehouse, але відсутні в office (офлайн-діагностика)."""
    _, warehouse_rows = read_csv_file(LOCAL_WAREHOUSE_FILE)
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    return list({r["TTN"] for r in warehouse_rows} - {r["TTN"] for r in office_rows})


def write_diff_file(missing) -> None:
    write_csv_file(DIFF_FILE, ["TTN"], [{"TTN": t} for t in missing])


def count_office_ttn() -> int:
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    return sum(1 for r in office_rows if r["TTN"].strip() != "")


def clear_ttn_locals() -> None:
    write_csv_file(LOCAL_OFFICE_FILE, OFFICE_HEADERS, [])
    write_csv_file(LOCAL_WAREHOUSE_FILE, WAREHOUSE_HEADERS, [])
