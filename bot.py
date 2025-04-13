import os
import re
import csv
import json
import threading
import time
from datetime import datetime, timedelta

import telebot
import gspread
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from oauth2client.service_account import ServiceAccountCredentials
import schedule
import pytz
from flask import Flask

# ======= Імпорт конфігурації =======
# Файл config.py має містити:
# TOKEN, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_URL, GOOGLE_SHEET_URL_USERS
from config import (
    TOKEN,
    GOOGLE_SHEETS_CREDENTIALS,
    GOOGLE_SHEET_URL,
    GOOGLE_SHEET_URL_USERS,
)

# ======= Глобальні змінні для локальних файлів =======
LOCAL_OFFICE_FILE = "local_office.csv"       # дані для офісу
LOCAL_WAREHOUSE_FILE = "local_warehouse.csv"  # дані для складу (з індексацією)
LOCAL_BUFFER_FILE = "local_buffer.csv"        # буферний файл

# Оновлено: тепер буфер містить TTН та Username
OFFICE_HEADERS = ["row", "TTN", "Date", "Username"]
WAREHOUSE_HEADERS = ["row", "TTN", "Date", "Username"]
BUFFER_HEADERS = ["TTN", "Username"]

# ======= Функції для роботи з CSV файлами =======
def ensure_local_file(filename, headers):
    if not os.path.exists(filename):
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

def read_csv_file(filename):
    try:
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames, list(reader)
    except Exception as e:
        return None, []

def write_csv_file(filename, headers, rows):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

def append_csv_row(filename, row, headers):
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow(row)

# Забезпечення наявності локальних файлів
for fname, hdr in [(LOCAL_OFFICE_FILE, OFFICE_HEADERS),
                   (LOCAL_WAREHOUSE_FILE, WAREHOUSE_HEADERS),
                   (LOCAL_BUFFER_FILE, BUFFER_HEADERS)]:
    ensure_local_file(fname, hdr)

# ======= Створення об’єкта бота та Flask-сервера =======
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def ping():
    return "OK", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# ======= Підключення до Google Таблиць =======
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def initialize_google_sheets():
    global creds, client, sheet_ttn, worksheet_ttn, sheet_users, worksheet_users
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
        client = gspread.authorize(creds)
        sheet_ttn = client.open_by_url(GOOGLE_SHEET_URL)
        worksheet_ttn = sheet_ttn.sheet1
        sheet_users = client.open_by_url(GOOGLE_SHEET_URL_USERS)
        worksheet_users = sheet_users.sheet1
        print("Google Sheets initialized successfully.")
    except Exception as e:
        print("Error initializing Google Sheets:", e)
        notify_admins(f"Error initializing Google Sheets: {e}")

initialize_google_sheets()

# ======= Кешування даних користувачів =======
GLOBAL_USERS = {}

def get_all_users_data():
    data = {}
    try:
        rows = worksheet_users.get_all_values()  # Перший рядок – заголовки
        for row in rows[1:]:
            if len(row) < 6:
                continue
            tg_id = row[0]
            role = row[1]
            username = row[2]
            report_time = row[3]
            last_sent = row[4] if len(row) >= 5 else ""
            admin_flag = (row[5].strip().lower() == "admin") if len(row) >= 6 else False
            data[tg_id] = {"role": role, "username": username, "time": report_time, "last_sent": last_sent, "admin": admin_flag}
    except Exception as e:
        print("Error reading users data:", e)
    return data

def load_users_cache():
    global GLOBAL_USERS
    GLOBAL_USERS = get_all_users_data()
    print("Users cache loaded. Total users:", len(GLOBAL_USERS))

load_users_cache()

def get_user_data(tg_id):
    global GLOBAL_USERS
    user = GLOBAL_USERS.get(tg_id)
    if user:
        return user["role"], user["username"], user["time"], user["last_sent"], user.get("admin", False)
    return None, "", "", "", False

def find_user_row(tg_id):
    try:
        rows = worksheet_users.get_all_values()
        for i, row in enumerate(rows, start=1):
            if row and row[0] == tg_id:
                return i
    except Exception as e:
        print("Error in find_user_row:", e)
    return None

def update_user_data(tg_id, role, username, report_time, last_sent=""):
    global GLOBAL_USERS
    try:
        row_index = find_user_row(tg_id)
        if row_index is None:
            next_row = len(worksheet_users.get_all_values()) + 1
            worksheet_users.update(f"A{next_row}:F{next_row}", [[tg_id, role, username, report_time, last_sent, ""]])
        else:
            current_row = worksheet_users.row_values(row_index)
            admin_value = current_row[5] if len(current_row) >= 6 else ""
            worksheet_users.update(f"A{row_index}:F{row_index}", [[tg_id, role, username, report_time, last_sent, admin_value]])
        GLOBAL_USERS[tg_id] = {"role": role, "username": username, "time": report_time, "last_sent": last_sent, "admin": GLOBAL_USERS.get(tg_id, {}).get("admin", False)}
    except Exception as e:
        print("Error updating user data:", e)
        notify_admins(f"Error updating user data for {tg_id}: {e}")

# ======= Функції для відправлення сповіщень адміністраторам =======
def get_admin_ids():
    admins = []
    users = get_all_users_data()
    for tg_id, info in users.items():
        if info.get("admin", False):
            admins.append(tg_id)
    try:
        with open("admins.json", "w", encoding="utf-8") as f:
            json.dump(admins, f)
    except Exception as ex:
        print("Error writing admins.json:", ex)
    return admins

def notify_admins(error_msg):
    admin_ids = get_admin_ids()
    if not admin_ids:
        print("No admin IDs available to notify.")
        return
    global LAST_ERROR_NOTIFY
    now = datetime.now()
    interval = timedelta(minutes=10)
    key = error_msg
    last_time = LAST_ERROR_NOTIFY.get(key)
    if last_time and now - last_time < interval:
        return
    LAST_ERROR_NOTIFY[key] = now
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, f"[ALERT] {error_msg}")
        except Exception as e:
            print(f"Failed to notify admin {admin_id}: {e}")

LAST_ERROR_NOTIFY = {}

# Placeholder для очищення TTН (якщо потрібно)
def clear_ttn_sheet():
    # Тут можна реалізувати логіку очищення Google таблиці TTН, якщо потрібно
    pass

# ======= Функції для роботи з локальними файлами TTН =======

def update_local_office_from_google():
    """
    Зчитує дані з Google таблиці TTН та записує у local_office.csv.
    """
    try:
        records = worksheet_ttn.get_all_values()  # включаючи заголовок
        office_rows = []
        for i, row in enumerate(records, start=1):
            if i == 1:
                continue  # пропускаємо заголовок
            office_rows.append({
                "row": str(i),
                "TTN": row[0] if len(row) > 0 else "",
                "Date": row[1] if len(row) > 1 else "",
                "Username": row[2] if len(row) > 2 else ""
            })
        write_csv_file(LOCAL_OFFICE_FILE, OFFICE_HEADERS, office_rows)
        print("Local office file updated from Google Sheets.")
    except Exception as e:
        print("Error updating local office file from Google Sheets:", e)
        notify_admins(f"Error updating local office file from Google Sheets: {e}")
        raise

def update_local_warehouse_from_google():
    """
    Зчитує дані з Google таблиці TTН та записує у local_warehouse.csv.
    Це потрібно для збереження індексації, як у Google таблиці.
    """
    try:
        records = worksheet_ttn.get_all_values()  # включаючи заголовок
        warehouse_rows = []
        for i, row in enumerate(records, start=1):
            if i == 1:
                continue  # пропускаємо заголовок
            warehouse_rows.append({
                "row": str(i),
                "TTN": row[0] if len(row) > 0 else "",
                "Date": row[1] if len(row) > 1 else "",
                "Username": row[2] if len(row) > 2 else ""
            })
        write_csv_file(LOCAL_WAREHOUSE_FILE, WAREHOUSE_HEADERS, warehouse_rows)
        print("Local warehouse file updated from Google Sheets.")
    except Exception as e:
        print("Error updating local warehouse file from Google Sheets:", e)
        notify_admins(f"Error updating local warehouse file from Google Sheets: {e}")
        raise

def update_local_warehouse_from_buffer():
    """
    Зчитує TTН з буферного файлу та додає лише нові записи у local_warehouse.csv.
    Використовується, коли надходять нові TTН від користувача.
    """
    try:
        _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
        _, warehouse_rows = read_csv_file(LOCAL_WAREHOUSE_FILE)
        existing_ttns = {r["TTN"] for r in warehouse_rows}
        if warehouse_rows:
            next_row = max(int(r["row"]) for r in warehouse_rows) + 1
        else:
            next_row = 2
        for entry in buffer_rows:
            ttn_val = entry["TTN"]
            username_val = entry.get("Username", "")
            if ttn_val not in existing_ttns:
                now = datetime.now(pytz.timezone("Europe/Kiev")).strftime("%H:%M:%S")
                new_row = {"row": str(next_row), "TTN": ttn_val, "Date": now, "Username": username_val}
                append_csv_row(LOCAL_WAREHOUSE_FILE, new_row, WAREHOUSE_HEADERS)
                next_row += 1
        print("Local warehouse file updated from buffer.")
    except Exception as e:
        print("Error updating local warehouse from buffer:", e)
        notify_admins(f"Error updating local warehouse from buffer: {e}")
        raise

def push_local_warehouse_to_google():
    """
    Порівнює індексацію між Google таблицею та local_warehouse.csv.
    Визначає останній рядок Google таблиці і пушить усі локальні записи з більшим номером.
    """
    try:
        records = worksheet_ttn.get_all_values()
        last_google_row = len(records)  # враховуючи заголовок
        _, warehouse_rows = read_csv_file(LOCAL_WAREHOUSE_FILE)
        for entry in warehouse_rows:
            try:
                row_num = int(entry["row"])
            except:
                continue
            if row_num > last_google_row:
                ttn_val = entry["TTN"]
                date_val = entry["Date"]
                username_val = entry["Username"]
                worksheet_ttn.append_row([ttn_val, date_val, username_val])
                print(f"Pushed TTN {ttn_val} (row {row_num}) to Google Sheet.")
    except Exception as e:
        print("Error pushing local warehouse to Google Sheet:", e)
        notify_admins(f"Error pushing local warehouse to Google Sheet: {e}")

# ======= Механізм буферизації з затримкою =======
BUFFER_PROCESSING_LOCK = threading.Lock()
BUFFER_PROCESSING_TIMER_RUNNING = False

def start_buffer_timer(chat_id):
    global BUFFER_PROCESSING_TIMER_RUNNING
    with BUFFER_PROCESSING_LOCK:
        if not BUFFER_PROCESSING_TIMER_RUNNING:
            BUFFER_PROCESSING_TIMER_RUNNING = True
            threading.Thread(target=buffer_timer_thread, args=(chat_id,), daemon=True).start()

def buffer_timer_thread(chat_id):
    time.sleep(5)  # Затримка 5 секунд для акумуляції нових TTН
    process_buffer(chat_id)
    global BUFFER_PROCESSING_TIMER_RUNNING
    with BUFFER_PROCESSING_LOCK:
        BUFFER_PROCESSING_TIMER_RUNNING = False

# ======= Обробка буфера з оновленою логікою =======
def process_buffer(chat_id):
    """
    Обробляє буферний файл:
      1. Переносить нові TTН з буфера у local_warehouse.csv.
      2. Пушить нові записи (за індексацією) з local_warehouse.csv до Google Sheet.
      3. Оновлює local_office.csv із Google таблиці.
      4. Порівнює TTН з буфера з даними з local_office.csv, формуючи списки доданих і не доданих.
      5. Надсилає повідомлення користувачу (роль "Склад") – кожен TTН з нового рядка.
      6. Очищає буфер.
    """
    try:
        # 1. Оновлюємо local_warehouse із буфера
        update_local_warehouse_from_buffer()
        # 2. Пушимо нові записи з local_warehouse до Google Sheet
        push_local_warehouse_to_google()
        # 3. Оновлюємо local_office із Google Sheet
        update_local_office_from_google()
    except Exception as e:
        print("Google Sheets query failed. Comparing local files directly.")
        _, warehouse_rows = read_csv_file(LOCAL_WAREHOUSE_FILE)
        _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
        warehouse_ttns = {r["TTN"] for r in warehouse_rows}
        office_ttns = {r["TTN"] for r in office_rows}
        missing = list(warehouse_ttns - office_ttns)
        if missing:
            diff_file = "diff_missing.csv"
            with open(diff_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["TTN"])
                writer.writeheader()
                for t in missing:
                    writer.writerow({"TTN": t})
            notify_admins(f"Failed to update from Google Sheets. Missing TTНs: {missing}. See attached file {diff_file}.")
    # 4. Порівнюємо буфер з офісним файлом
    _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    office_ttns = {r["TTN"] for r in office_rows}
    added = []
    not_added = []
    for entry in buffer_rows:
        ttn_val = entry["TTN"]
        if ttn_val in office_ttns:
            added.append(ttn_val)
        else:
            not_added.append(ttn_val)
    # 5. Формуємо повідомлення: кожен TTН з нового рядка
    msg_lines = []
    if added:
        msg_lines.append("Додано:")
        msg_lines.extend(added)
    if not_added:
        msg_lines.append("Не додано:")
        msg_lines.extend(not_added)
    msg = "\n".join(msg_lines)
    bot.send_message(chat_id, msg)
    # 6. Очищаємо буфер
    write_csv_file(LOCAL_BUFFER_FILE, BUFFER_HEADERS, [])
    print("Buffer cleared.")

def add_ttn_to_buffer(ttn, username):
    """
    Додає TTН та нік користувача до буферного файлу, якщо TTН ще не існує.
    """
    _, buffer_rows = read_csv_file(LOCAL_BUFFER_FILE)
    existing = {r["TTN"] for r in buffer_rows}
    if ttn not in existing:
        append_csv_row(LOCAL_BUFFER_FILE, {"TTN": ttn, "Username": username}, BUFFER_HEADERS)
        print(f"TTН {ttn} додано до буфера з Username {username}.")

def check_ttn_in_local_office(chat_id, ttn):
    """
    Для користувача з роллю "Офіс" перевіряє наявність TTН у local_office.csv.
    """
    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
    for row in office_rows:
        if row["TTN"] == ttn:
            bot.send_message(chat_id, f"TTН {ttn} знайдено на рядку {row['row']}.")
            return
    bot.send_message(chat_id, f"TTН {ttn} не знайдено в локальному файлі.")

def handle_ttn_logic(chat_id, ttn, username):
    role, usern, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if role == "Склад":
        add_ttn_to_buffer(ttn, username)
        # Запускаємо 5-секундну затримку для акумуляції нових записів
        start_buffer_timer(chat_id)
    elif role == "Офіс":
        check_ttn_in_local_office(chat_id, ttn)
    else:
        bot.send_message(chat_id, "Спочатку встановіть роль за допомогою /Office або /Cklad")

# ======= Обробники команд Telegram-бота =======

@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    subscribe_info = (
        "\n\nВи можете підписатися на щоденний звіт, ввівши команду /subscribe <час> "
        "(наприклад, /subscribe 22:00). Якщо час не вказано – за замовчуванням 22:00. "
        "Відписатися – командою /unsubscribe."
    )
    if role:
        bot.send_message(chat_id,
            f"👋 Вітаю! Ваша роль: *{role}*.\n\n"
            "Ви можете змінити роль за допомогою:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦" + subscribe_info,
            parse_mode="Markdown")
    else:
        bot.send_message(chat_id,
            "Цей бот спрощує роботу з ТТН.\n\n"
            "Оберіть роль:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦" + subscribe_info,
            parse_mode="Markdown")

@bot.message_handler(commands=["Office"])
def cmd_office(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not username:
        username = message.from_user.username or ""
    update_user_data(chat_id, "Офіс", username, report_time, last_sent)
    bot.send_message(chat_id,
                     "✅ Ви обрали роль: *Офіс*.\n\nНадсилайте TTН (код або фото) для перевірки.",
                     parse_mode="Markdown")

@bot.message_handler(commands=["Cklad"])
def cmd_cklad(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not username:
        username = message.from_user.username or ""
    update_user_data(chat_id, "Склад", username, report_time, last_sent)
    bot.send_message(chat_id,
                     "✅ Ви обрали роль: *Склад*.\n\nНадсилайте TTН (код або фото), вони збережуться в буфер.",
                     parse_mode="Markdown")

@bot.message_handler(commands=["subscribe"])
def cmd_subscribe(message):
    chat_id = str(message.chat.id)
    args = message.text.split()
    sub_time = "22:00"
    if len(args) > 1:
        candidate = args[1]
        if re.match(r'^\d{1,2}:\d{2}$', candidate):
            parts = candidate.split(":")
            hour = parts[0].zfill(2)
            minute = parts[1]
            sub_time = f"{hour}:{minute}"
        else:
            bot.send_message(chat_id, "Невірний формат часу. Використовуйте формат HH:MM, наприклад, 22:00.")
            return
    role, username, _, last_sent, admin_flag = get_user_data(chat_id)
    if not role:
        role = "Офіс"
        if not username:
            username = message.from_user.username or ""
    update_user_data(chat_id, role, username, sub_time, last_sent)
    bot.send_message(chat_id, f"Ви успішно підписалися на звіт о {sub_time}.")

@bot.message_handler(commands=["unsubscribe"])
def cmd_unsubscribe(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not role:
        bot.send_message(chat_id, "Спочатку встановіть роль за допомогою /start")
        return
    update_user_data(chat_id, role, username, "", last_sent)
    bot.send_message(chat_id, "Ви успішно відписалися від звітів.")

@bot.message_handler(content_types=["photo"])
def handle_barcode_image(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not role:
        bot.send_message(chat_id, "Спочатку встановіть роль за допомогою /start")
        return
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    np_arr = np.frombuffer(downloaded_file, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    try:
        barcodes = decode(img)
        if not barcodes:
            bot.send_message(chat_id, "❌ Не вдалося розпізнати штрих-коди!")
            return
        success_count = 0
        error_count = 0
        for barcode in barcodes:
            try:
                ttn_raw = barcode.data.decode("utf-8")
                digits = re.sub(r"\D", "", ttn_raw)
                if not digits or not (10 <= len(digits) <= 18):
                    continue
                if role == "Склад":
                    add_ttn_to_buffer(digits, username)
                    start_buffer_timer(chat_id)  # Запускаємо таймер обробки буфера
                else:
                    check_ttn_in_local_office(chat_id, digits)
                success_count += 1
            except Exception as inner_e:
                error_count += 1
        bot.send_message(chat_id, f"Оброблено штрих-кодів: успішно: {success_count}, з помилками: {error_count}")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка обробки зображення, спробуйте ще раз!")
        print(e)
        notify_admins(f"Error in handle_barcode_image for chat {chat_id}: {e}")

@bot.message_handler(func=lambda m: True)
def handle_text_message(message):
    if message.text.startswith("/"):
        return
    chat_id = str(message.chat.id)
    digits = re.sub(r"\D", "", message.text)
    if digits and (10 <= len(digits) <= 18):
        role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
        if not role:
            bot.send_message(chat_id, "Спочатку встановіть роль за допомогою /start")
            return
        if role == "Склад":
            add_ttn_to_buffer(digits, username)
            start_buffer_timer(chat_id)
        else:
            check_ttn_in_local_office(chat_id, digits)

def send_subscription_notifications():
    tz = pytz.timezone("Europe/Kiev")
    now = datetime.now(tz)
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    users = get_all_users_data()
    for chat_id, info in users.items():
        rt = info.get("time", "")
        if not rt:
            continue
        if current_time_str == rt:
            if info.get("last_sent", "") != today_str:
                try:
                    _, office_rows = read_csv_file(LOCAL_OFFICE_FILE)
                    count_ttn = sum(1 for r in office_rows if r["TTN"].strip() != "")
                except Exception as e:
                    count_ttn = "Невідомо (помилка)"
                    notify_admins(f"Error counting TTН for chat {chat_id}: {e}")
                bot.send_message(chat_id, f"За сьогодні оброблено TTН: {count_ttn}")
                role, username, rt, _ , admin_flag = get_user_data(chat_id)
                update_user_data(chat_id, role, username, rt, today_str)

def run_clear_ttn_sheet_with_tz():
    tz_kiev = pytz.timezone("Europe/Kiev")
    now_kiev = datetime.now(tz_kiev)
    if now_kiev.strftime("%H:%M") == "00:00":
        clear_ttn_sheet()

def reinitialize_google_sheets():
    global creds, client, sheet_ttn, worksheet_ttn, sheet_users, worksheet_users
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
        client = gspread.authorize(creds)
        sheet_ttn = client.open_by_url(GOOGLE_SHEET_URL)
        worksheet_ttn = sheet_ttn.sheet1
        sheet_users = client.open_by_url(GOOGLE_SHEET_URL_USERS)
        worksheet_users = sheet_users.sheet1
        load_users_cache()
        # Оновлюємо обидва файли з даними з Google Sheets:
        update_local_office_from_google()
        update_local_warehouse_from_google()
        print("Google Sheets reinitialized successfully.")
    except Exception as e:
        print("Error reinitializing Google Sheets:", e)
        notify_admins(f"Error reinitializing Google Sheets: {e}")

def run_bot_polling():
    while True:
        try:
            bot.polling()
        except Exception as e:
            error_text = f"Polling error: {e}"
            print(error_text)
            notify_admins(error_text)
            reinitialize_google_sheets()
            time.sleep(10)

def run_scheduler():
    schedule.every().minute.do(send_subscription_notifications)
    schedule.every().minute.do(run_clear_ttn_sheet_with_tz)
    schedule.every().hour.do(reinitialize_google_sheets)
    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    # При старті оновлюємо обидва локальні файли з даними з Google Sheets
    update_local_office_from_google()
    update_local_warehouse_from_google()
    
    admins = get_admin_ids()
    if admins:
        print("Loaded admin IDs:", admins)
    else:
        print("No admin IDs found.")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    bot_thread = threading.Thread(target=run_bot_polling, daemon=True)
    bot_thread.start()
    
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("Shutting down gracefully (KeyboardInterrupt).")
        import sys
        sys.exit(0)

if __name__ == "__main__":
    main()
