import os
import re
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
# TOKEN, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_URL (для TTН), GOOGLE_SHEET_URL_USERS (для користувачів)
from config import (
    TOKEN,
    GOOGLE_SHEETS_CREDENTIALS,
    GOOGLE_SHEET_URL,
    GOOGLE_SHEET_URL_USERS,
)

# ======= Створення об’єкта бота =======
# Переконуємося, що ця стрічка знаходиться до всіх звернень до bot
bot = telebot.TeleBot(TOKEN)

# ======= Flask-сервер для пінгування (UptimeRobot) =======
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

# ======= Функції роботи з таблицею TTН =======
# Таблиця TTН має заголовки: A: TTН, B: Дата, C: Нікнейм
def add_ttn_to_sheet(ttn, username, chat_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        col_a = worksheet_ttn.col_values(1)
        next_row = len(col_a) + 1
        worksheet_ttn.update(f"A{next_row}:C{next_row}", [[ttn, now, username]])
        bot.send_message(chat_id, f"✅ ТТН `{ttn}` додано!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка запису ТТН до таблиці!")
        print(e)
        notify_admins(f"Error in add_ttn_to_sheet for chat_id {chat_id}: {e}")

def check_ttn_in_sheet(chat_id, ttn):
    try:
        records = worksheet_ttn.get_all_values()
        if len(records) <= 1:
            bot.send_message(chat_id, "❌ В базі немає ТТН.")
            return
        for row in records[1:]:
            if row and len(row) >= 1 and row[0] == ttn:
                date_time = row[1] if len(row) > 1 else "невідомо"
                bot.send_message(chat_id, f"✅ Замовлення зібрано! ТТН: `{ttn}`\n🕒 Час: {date_time}", parse_mode="Markdown")
                return
        bot.send_message(chat_id, f"❌ ТТН `{ttn}` не знайдено у базі!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка зчитування таблиці для перевірки!")
        print(e)
        notify_admins(f"Error in check_ttn_in_sheet for chat_id {chat_id}: {e}")

def clear_ttn_sheet():
    try:
        records = worksheet_ttn.get_all_values()
        row_count = len(records)
        if row_count > 1:
            empty_data = [[""] * 3 for _ in range(row_count - 1)]
            worksheet_ttn.update(f"A2:C{row_count}", empty_data)
            # Очищення форматування для діапазону клітинок A2:C_lastRow:
            requests = [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": worksheet_ttn.id,
                            "startRowIndex": 1,       # рядок 2 (індекс 1)
                            "endRowIndex": row_count,   # до кінця
                            "startColumnIndex": 0,      # стовпець A (індекс 0)
                            "endColumnIndex": 3         # до стовпця C (end=3)
                        },
                        "cell": {"userEnteredFormat": {}},
                        "fields": "userEnteredFormat"
                    }
                }
            ]
            sheet_ttn.batch_update({"requests": requests})
            print("TTN sheet cleared successfully (contents and formatting).")
    except Exception as e:
        print("Error clearing TTN sheet:", e)
        notify_admins(f"Error clearing TTN sheet: {e}")

def run_clear_ttn_sheet_with_tz():
    tz_kiev = pytz.timezone("Europe/Kiev")
    now_kiev = datetime.now(tz_kiev)
    if now_kiev.strftime("%H:%M") == "00:00":
        clear_ttn_sheet()

# ======= Періодична реініціалізація Google Sheets (щогодини) =======
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
        print("Google Sheets reinitialized successfully.")
    except Exception as e:
        print("Error reinitializing Google Sheets:", e)
        notify_admins(f"Error reinitializing Google Sheets: {e}")

# ======= Функції для відправлення повідомлень адміністраторам =======
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

# ======= Telegram-бот: Команди та обробники =======

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
        bot.send_message(
            chat_id,
            f"👋 Вітаю! Ваша роль: *{role}*.\n\n"
            "Ви можете змінити роль за допомогою:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦"
            f"{subscribe_info}",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(
            chat_id,
            "Цей бот спрощує роботу з ТТН.\n\n"
            "Оберіть роль:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦"
            f"{subscribe_info}"
        )

@bot.message_handler(commands=["Office"])
def cmd_office(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not username:
        username = message.from_user.username or ""
    update_user_data(chat_id, "Офіс", username, report_time, last_sent)
    bot.send_message(chat_id, "✅ Ви обрали роль: *Офіс*.\n\nНадсилайте ТТН (код або фото), вони обробляться.", parse_mode="Markdown")

@bot.message_handler(commands=["Cklad"])
def cmd_cklad(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not username:
        username = message.from_user.username or ""
    update_user_data(chat_id, "Склад", username, report_time, last_sent)
    bot.send_message(chat_id, "✅ Ви обрали роль: *Склад*.\n\nНадсилайте ТТН (код або фото), вони обробляться.", parse_mode="Markdown")

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
    bot.send_message(chat_id, f"Ви успішно підписалися на повідомлення о {sub_time}.")

@bot.message_handler(commands=["unsubscribe"])
def cmd_unsubscribe(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not role:
        bot.send_message(chat_id, "Спочатку встановіть роль за допомогою /start")
        return
    update_user_data(chat_id, role, username, "", last_sent)
    bot.send_message(chat_id, "Ви успішно відписалися від повідомлень.")

@bot.message_handler(content_types=["photo"])
def handle_barcode_image(message):
    chat_id = str(message.chat.id)
    role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if not role:
        bot.send_message(chat_id, "Спочатку встановіть роль: /Office або /Cklad")
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
                # Змінено перевірку: тепер TTН має складатися від 10 до 18 цифр
                if not digits or not (10 <= len(digits) <= 18):
                    continue
                handle_ttn_logic(chat_id, digits, username)
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
    # Оновлено перевірку на довжину коду: має бути 10-18 цифр
    if digits and 10 <= len(digits) <= 18:
        role, username, report_time, last_sent, admin_flag = get_user_data(chat_id)
        if not role:
            bot.send_message(chat_id, "Спочатку встановіть роль: /Office або /Cklad")
            return
        handle_ttn_logic(chat_id, digits, username)

def handle_ttn_logic(chat_id, ttn, username):
    role, usern, report_time, last_sent, admin_flag = get_user_data(chat_id)
    if role == "Склад":
        add_ttn_to_sheet(ttn, username, chat_id)
    elif role == "Офіс":
        check_ttn_in_sheet(chat_id, ttn)
    else:
        bot.send_message(chat_id, "Спочатку встановіть роль: /Office або /Cklad")

# ======= Розсилка звітів підписникам =======
def send_subscription_notifications():
    tz = pytz.timezone("Europe/Kiev")
    now = datetime.now(tz)
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    all_users = get_all_users_data()
    for chat_id, info in all_users.items():
        report_time = info.get("time", "")
        if not report_time:
            continue
        if current_time_str == report_time:
            last_sent = info.get("last_sent", "")
            if last_sent != today_str:
                try:
                    col_a = worksheet_ttn.col_values(1)[1:]
                    count_ttn = sum(1 for x in col_a if x.strip() != "")
                except Exception as e:
                    count_ttn = "Невідомо (помилка)"
                    notify_admins(f"Error counting TTН for chat {chat_id}: {e}")
                bot.send_message(chat_id, f"За сьогодні оброблено ТТН: {count_ttn}")
                role, username, report_time, _ , admin_flag = get_user_data(chat_id)
                update_user_data(chat_id, role, username, report_time, today_str)

# ======= Періодична реініціалізація Google Sheets =======
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
        print("Google Sheets reinitialized successfully.")
    except Exception as e:
        print("Error reinitializing Google Sheets:", e)
        notify_admins(f"Error reinitializing Google Sheets: {e}")

# ======= Функція запуску bot.polling з обробкою помилок =======
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

# ======= Планувальник (schedule) =======
def run_scheduler():
    schedule.every().minute.do(send_subscription_notifications)
    schedule.every().minute.do(run_clear_ttn_sheet_with_tz)
    schedule.every().hour.do(reinitialize_google_sheets)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ======= Основна функція =======
def main():
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
