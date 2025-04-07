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
# TOKEN, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_URL (для TTN),
# GOOGLE_SHEET_URL_USERS (для користувачів)
from config import (
    TOKEN,
    GOOGLE_SHEETS_CREDENTIALS,
    GOOGLE_SHEET_URL,
    GOOGLE_SHEET_URL_USERS,
)

# ======= Ініціалізація Telegram-бота =======
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
        notify_admins(f"Error initializing Google Sheets: {e}")
        print("Error initializing Google Sheets:", e)

initialize_google_sheets()

# ======= Функції для роботи з даними користувачів (Google Таблиця) =======
# Таблиця користувачів має стовпці:
# A: Tg ID, B: Роль, C: Tg нік, D: Час для звіту, E: Останній звіт, F: Admin (якщо "Admin", то користувач є адміністратором)
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
            admin_flag = row[5].strip().lower() == "admin" if len(row) >= 6 else False
            data[tg_id] = {"role": role, "username": username, "time": report_time, "last_sent": last_sent, "admin": admin_flag}
    except Exception as e:
        notify_admins(f"Error reading users data: {e}")
        print("Error reading users data:", e)
    return data

def find_user_row(tg_id):
    try:
        rows = worksheet_users.get_all_values()
        for i, row in enumerate(rows, start=1):
            if row and row[0] == tg_id:
                return i
    except Exception as e:
        notify_admins(f"Error in find_user_row for {tg_id}: {e}")
        print("Error in find_user_row:", e)
    return None

def update_user_data(tg_id, role, username, report_time, last_sent=""):
    try:
        row_index = find_user_row(tg_id)
        if row_index is None:
            next_row = len(worksheet_users.get_all_values()) + 1
            worksheet_users.update(f"A{next_row}:F{next_row}", [[tg_id, role, username, report_time, last_sent, ""]])
        else:
            current_row = worksheet_users.row_values(row_index)
            admin_value = current_row[5] if len(current_row) >= 6 else ""
            worksheet_users.update(f"A{row_index}:F{row_index}", [[tg_id, role, username, report_time, last_sent, admin_value]])
    except Exception as e:
        notify_admins(f"Error updating user data for {tg_id}: {e}")
        print("Error updating user data:", e)

def get_user_data(tg_id):
    row_index = find_user_row(tg_id)
    if row_index is None:
        return None, "", "", "", False
    try:
        row = worksheet_users.row_values(row_index)
        role = row[1] if len(row) > 1 else None
        username = row[2] if len(row) > 2 else ""
        report_time = row[3] if len(row) > 3 else ""
        last_sent = row[4] if len(row) > 4 else ""
        admin_flag = row[5].strip().lower() == "admin" if len(row) > 5 else False
        return role, username, report_time, last_sent, admin_flag
    except Exception as e:
        notify_admins(f"Error getting user data for {tg_id}: {e}")
        print("Error getting user data:", e)
        return None, "", "", "", False

def update_admin_file():
    try:
        rows = worksheet_users.get_all_values()
        admin_ids = []
        for row in rows[1:]:
            if len(row) >= 6 and row[5].strip().lower() == "admin":
                admin_ids.append(row[0])
        with open("admins.json", "w", encoding="utf-8") as f:
            json.dump(admin_ids, f)
        return admin_ids
    except Exception as e:
        print("Error updating admin file:", e)
        try:
            with open("admins.json", "r", encoding="utf-8") as f:
                admin_ids = json.load(f)
            return admin_ids
        except Exception as ex:
            return []

def get_admin_ids():
    return update_admin_file()

def notify_admins(error_msg):
    admin_ids = get_admin_ids()
    if not admin_ids:
        print("No admin IDs available to notify.")
        return
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, f"[ALERT] {error_msg}")
        except Exception as e:
            print(f"Failed to notify admin {admin_id}: {e}")

# ======= Функції для роботи з таблицею TTN =======
# Таблиця TTN має заголовки в першому рядку: A: TTN, B: Дата, C: Нікнейм
def add_ttn_to_sheet(ttn, username, chat_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        col_a = worksheet_ttn.col_values(1)
        next_row = len(col_a) + 1
        worksheet_ttn.update(f"A{next_row}:C{next_row}", [[ttn, now, username]])
        bot.send_message(chat_id, f"✅ ТТН `{ttn}` додано!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка запису ТТН до таблиці!")
        notify_admins(f"Error in add_ttn_to_sheet for chat_id {chat_id}: {e}")
        print(e)

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
        notify_admins(f"Error in check_ttn_in_sheet for chat_id {chat_id}: {e}")
        print(e)

def clear_ttn_sheet():
    try:
        records = worksheet_ttn.get_all_values()
        row_count = len(records)
        if row_count > 1:
            empty_data = [[""] * 3 for _ in range(row_count - 1)]
            worksheet_ttn.update(f"A2:C{row_count}", empty_data)
            print("TTN sheet cleared successfully.")
    except Exception as e:
        notify_admins(f"Error clearing TTN sheet: {e}")
        print("Помилка при очищенні таблиці TTN:", e)

def run_clear_ttn_sheet_with_tz():
    tz_kiev = pytz.timezone("Europe/Kiev")
    now_kiev = datetime.now(tz_kiev)
    if now_kiev.strftime("%H:%M") == "00:00":
        clear_ttn_sheet()

# ======= Функції періодичної реініціалізації Google Sheets та Telegram-з’єднання =======
def reinitialize_google_sheets():
    try:
        initialize_google_sheets()
        print("Google Sheets reinitialized successfully.")
    except Exception as e:
        notify_admins(f"Error reinitializing Google Sheets: {e}")
        print("Error reinitializing Google Sheets:", e)

def run_bot_polling():
    while True:
        try:
            bot.infinity_polling(skip_pending=False, timeout=30)
        except Exception as e:
            notify_admins(f"Telegram polling error: {e}")
            print(f"Telegram polling error: {e}")
            time.sleep(5)

# ======= Планувальник (schedule) =======
def run_scheduler():
    schedule.every().minute.do(send_subscription_notifications)
    schedule.every().minute.do(run_clear_ttn_sheet_with_tz)
    schedule.every().hour.do(reinitialize_google_sheets)
    while True:
        schedule.run_pending()
        time.sleep(30)

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
                    notify_admins(f"Error counting TTN for report for chat {chat_id}: {e}")
                bot.send_message(chat_id, f"За сьогодні оброблено ТТН: {count_ttn}")
                role, username, report_time, _ , admin_flag = get_user_data(chat_id)
                update_user_data(chat_id, role, username, report_time, today_str)

# ======= Основна функція =======
def main():
    admin_ids = get_admin_ids()
    if admin_ids:
        print("Loaded admin IDs:", admin_ids)
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
