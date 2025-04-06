import os
import json
import re
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

# Якщо конфіг зберігається у файлі config.py, розкоментуйте:
from config import TOKEN, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_URL

#####################
# Flask для пінгування (UptimeRobot)
#####################
app = Flask(__name__)

@app.route('/')
def ping():
    return "OK", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

#####################
# Підключення до Google Таблиці
#####################
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(GOOGLE_SHEET_URL)
worksheet = sheet.sheet1  # Якщо потрібна інша вкладка, використайте sheet.worksheet("Назва")

#####################
# Налаштування бота
#####################
bot = telebot.TeleBot(TOKEN)

USER_ROLES_FILE = "user_roles.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"

#####################
# Функції для роботи з локальними файлами (ролі та підписки)
#####################
def load_user_roles():
    try:
        with open(USER_ROLES_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_user_roles(user_roles):
    with open(USER_ROLES_FILE, "w", encoding="utf-8") as file:
        json.dump(user_roles, file, ensure_ascii=False, indent=4)

def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_subscriptions(subs):
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=4)

#####################
# Логування помилок штрих-кодів
#####################
def log_barcode_error(user_nickname, error_message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("barcode_error_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {user_nickname}: {error_message}\n")

#####################
# Команди бота
#####################

@bot.message_handler(commands=["start"])
def send_welcome(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    subscribe_info = (
        "\n\nВи можете підписатися на щоденний звіт, ввівши команду /subscribe <час> "
        "(наприклад, /subscribe 22:00). Якщо час не вказано – за замовчуванням 22:00. "
        "Відписатися – командою /unsubscribe."
    )
    if chat_id in user_roles:
        role = user_roles[chat_id]["role"]
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
def set_office_role(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    user_roles[chat_id] = {
        "role": "Офіс",
        "username": message.from_user.username
    }
    save_user_roles(user_roles)
    bot.send_message(
        chat_id,
        "✅ Ви обрали роль: *Офіс*\n\nНадсилайте ТТН (код або фото), вони автоматично обробляться.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["Cklad"])
def set_cklad_role(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    user_roles[chat_id] = {
        "role": "Склад",
        "username": message.from_user.username
    }
    save_user_roles(user_roles)
    bot.send_message(
        chat_id,
        "✅ Ви обрали роль: *Склад*\n\nНадсилайте ТТН (код або фото), вони автоматично обробляться.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["subscribe"])
def subscribe(message):
    chat_id = str(message.chat.id)
    args = message.text.split()
    sub_time = "22:00"  # час за замовчуванням
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
    subs = load_subscriptions()
    subs[chat_id] = {
         "time": sub_time,
         "username": message.from_user.username,
         "last_sent": ""
    }
    save_subscriptions(subs)
    bot.send_message(chat_id, f"Ви успішно підписалися на повідомлення о {sub_time}.")

@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(message):
    chat_id = str(message.chat.id)
    subs = load_subscriptions()
    if chat_id in subs:
        del subs[chat_id]
        save_subscriptions(subs)
        bot.send_message(chat_id, "Ви успішно відписалися від повідомлень.")
    else:
        bot.send_message(chat_id, "Ви не були підписані.")

#####################
# Обробка фото (штрих-кодів)
#####################
@bot.message_handler(content_types=["photo"])
def handle_barcode_image(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    if chat_id not in user_roles:
        bot.send_message(chat_id, "Спочатку виберіть роль: /Office або /Cklad")
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
                if not digits or not (8 <= len(digits) <= 18):
                    continue
                handle_ttn_logic(chat_id, digits, message.from_user.username)
                success_count += 1
            except Exception as inner_e:
                user_nickname = message.from_user.username or str(message.chat.id)
                log_barcode_error(user_nickname, f"Обробка коду {ttn_raw if 'ttn_raw' in locals() else 'Unknown'}: {inner_e}")
                error_count += 1

        bot.send_message(chat_id, f"Оброблено штрих-кодів: успішно: {success_count}, з помилками: {error_count}")
    except Exception as e:
        user_nickname = message.from_user.username or str(message.chat.id)
        log_barcode_error(user_nickname, str(e))
        bot.send_message(chat_id, "❌ Помилка обробки зображення, спробуйте ще раз!")

#####################
# Обробка текстових повідомлень (якщо це TTN)
#####################
@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    if message.text.startswith("/"):
        return
    chat_id = str(message.chat.id)
    digits = re.sub(r"\D", "", message.text)
    if digits and 8 <= len(digits) <= 18:
        handle_ttn_logic(chat_id, digits, message.from_user.username)

#####################
# Основна логіка роботи з TTN
#####################
def handle_ttn_logic(chat_id, ttn, username):
    user_roles = load_user_roles()
    if chat_id not in user_roles:
        bot.send_message(chat_id, "Спочатку виберіть роль: /Office або /Cklad")
        return
    role = user_roles[chat_id]["role"]
    if role == "Склад":
        add_ttn_to_sheet(ttn, username, chat_id)
    elif role == "Офіс":
        check_ttn_in_sheet(chat_id, ttn)

def add_ttn_to_sheet(ttn, username, chat_id):
    """Записуємо TTN в рядок (A, B, C). Перший ряд - заголовок, запис починаємо з другого."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        col_a = worksheet.col_values(1)  # зчитуємо колонку A цілком
        next_row = len(col_a) + 1        # індекс наступного вільного рядка
        # Записуємо: A - TTN, B - час, C - нікнейм
        worksheet.update(f"A{next_row}:C{next_row}", [[ttn, now, username]])
        bot.send_message(chat_id, f"✅ ТТН `{ttn}` додано!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка запису ТТН до таблиці!")
        user_nickname = username or str(chat_id)
        log_barcode_error(user_nickname, f"append_row error: {e}")

def check_ttn_in_sheet(chat_id, ttn):
    """Перевіряємо, чи є TTN у колонці A (з рядка 2 і далі). Якщо так – повертаємо дату (колонка B)."""
    try:
        records = worksheet.get_all_values()
        # records[0] = ['TTN', 'Дата надсилання ТТН', 'Нікнейм в тт']
        # починаємо з 2-го рядка (індекс 1)
        if len(records) <= 1:
            bot.send_message(chat_id, "❌ В базі немає ТТН.")
            return

        for row in records[1:]:
            # row = [TTN, Дата, Нікнейм]
            if len(row) >= 1 and row[0] == ttn:
                date_time = row[1] if len(row) > 1 else "невідомо"
                bot.send_message(
                    chat_id,
                    f"✅ Замовлення зібрано! ТТН: `{ttn}`\n🕒 Час: {date_time}",
                    parse_mode="Markdown"
                )
                return
        bot.send_message(chat_id, f"❌ ТТН `{ttn}` не знайдено у базі!", parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка зчитування таблиці для перевірки!")
        print(e)

#####################
# Очищення таблиці опівночі (крім заголовків)
#####################
def clear_sheet():
    """
    Видаляємо всі дані, крім першого рядка (заголовків).
    """
    try:
        records = worksheet.get_all_values()
        row_count = len(records)  # кількість рядків
        if row_count > 1:
            # Очищаємо з 2-го рядка до останнього
            empty_data = [[""] * 3 for _ in range(row_count - 1)]
            worksheet.update(f"A2:C{row_count}", empty_data)
            print("Sheet cleared successfully.")
    except Exception as e:
        print(f"Помилка при очищенні таблиці: {e}")

def run_clear_sheet_with_tz():
    """Запускаємо clear_sheet() о 00:00 за Києвом."""
    tz_kiev = pytz.timezone("Europe/Kiev")
    now_kiev = datetime.now(tz_kiev)
    if now_kiev.strftime("%H:%M") == "00:00":
        clear_sheet()

#####################
# Розсилка підписникам
#####################
def send_subscription_notifications():
    """
    Кожну хвилину перевіряємо, чи настав час надсилати звіт.
    Рахуємо кількість TTN у колонці A (починаючи з рядка 2).
    """
    tz_kiev = pytz.timezone("Europe/Kiev")
    now = datetime.now(tz_kiev)
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    subs = load_subscriptions()
    for chat_id, data in subs.items():
        sub_time = data.get("time", "22:00")
        last_sent = data.get("last_sent", "")
        if current_time_str == sub_time and last_sent != today_str:
            try:
                # Зчитуємо колонку A, пропускаємо заголовок
                col_a = worksheet.col_values(1)[1:]  # з рядка 2
                count_ttn = sum(1 for x in col_a if x.strip() != "")
            except Exception as e:
                count_ttn = "Невідомо (помилка)"
            bot.send_message(chat_id, f"За сьогодні оброблено ТТН: {count_ttn}")
            subs[chat_id]["last_sent"] = today_str

    save_subscriptions(subs)

#####################
# Планувальник (schedule)
#####################
def run_scheduler():
    # Щохвилини перевіряємо, чи настав час відправляти звіти
    schedule.every().minute.do(send_subscription_notifications)
    # О 00:00 за Києвом очищаємо таблицю
    schedule.every().day.at("00:00").do(run_clear_sheet_with_tz)

    while True:
        schedule.run_pending()
        time.sleep(30)

#####################
# Головна функція
#####################
def main():
    # 1) Запускаємо Flask-сервер у фоновому потоці (для пінгування UptimeRobot)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 2) Запускаємо Telegram-бот у фоновому потоці
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()

    # 3) Запускаємо планувальник у головному потоці (з обробкою KeyboardInterrupt)
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("Shutting down gracefully (KeyboardInterrupt).")
        import sys
        sys.exit(0)

if __name__ == "__main__":
    main()
