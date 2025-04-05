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

# Імпортуємо дані з файлу конфігурації (цей файл містить API ключі і не повинен бути в репозиторії)
from config import TOKEN, GOOGLE_SHEETS_CREDENTIALS, GOOGLE_SHEET_URL

#####################
# Налаштування Flask
#####################
app = Flask(__name__)

@app.route('/')
def ping():
    return "OK", 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

#####################
# Налаштування бота
#####################

# Підключення до Google Таблиці
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDENTIALS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(GOOGLE_SHEET_URL)
worksheet = sheet.sheet1  # За потреби змініть на sheet.worksheet("НазваВкладки")

bot = telebot.TeleBot(TOKEN)

# Файли для зберігання даних (user_roles та subscriptions)
USER_ROLES_FILE = "user_roles.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"

# Функції роботи з файлами user_roles.json
def load_user_roles():
    try:
        with open(USER_ROLES_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def save_user_roles(user_roles):
    with open(USER_ROLES_FILE, "w", encoding="utf-8") as file:
        json.dump(user_roles, file, ensure_ascii=False, indent=4)

# Функції роботи з файлами subscriptions.json
def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_subscriptions(subs):
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=4)

# Функція логування помилок (штрих-кодів)
def log_barcode_error(user_nickname, error_message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("barcode_error_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {user_nickname}: {error_message}\n")

#####################
# Обробка команд бота
#####################

# /start – відправляє привітальне повідомлення з інструкцією щодо підписки
@bot.message_handler(commands=["start"])
def send_welcome(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    subscribe_info = ("\n\nВи можете підписатися на щоденний звіт, "
                      "ввівши команду /subscribe <час> (наприклад, /subscribe 22:00). "
                      "Якщо час не вказано – за замовчуванням 22:00. "
                      "Відписатися – командою /unsubscribe.")
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

# Команди для вибору ролі
@bot.message_handler(commands=["Office"])
def set_office_role(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    user_roles[chat_id] = {
        "role": "Офіс",
        "username": message.from_user.username
    }
    save_user_roles(user_roles)
    bot.send_message(chat_id, "✅ Ви обрали роль: *Офіс*\n\nНадсилайте ТТН (код або фото), вони автоматично обробляться.", parse_mode="Markdown")

@bot.message_handler(commands=["Cklad"])
def set_cklad_role(message):
    chat_id = str(message.chat.id)
    user_roles = load_user_roles()
    user_roles[chat_id] = {
        "role": "Склад",
        "username": message.from_user.username
    }
    save_user_roles(user_roles)
    bot.send_message(chat_id, "✅ Ви обрали роль: *Склад*\n\nНадсилайте ТТН (код або фото), вони автоматично обробляться.", parse_mode="Markdown")

# Команда підписки. Формат: /subscribe або /subscribe 22:00
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

# Команда відписки
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

# Обробка фото – зчитуються всі штрих-коди
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

# Обробка текстових повідомлень (якщо повідомлення містить ТТН)
@bot.message_handler(func=lambda message: True)
def handle_text_message(message):
    if message.text.startswith("/"):
        return
    chat_id = str(message.chat.id)
    digits = re.sub(r"\D", "", message.text)
    if digits and 8 <= len(digits) <= 18:
        handle_ttn_logic(chat_id, digits, message.from_user.username)

# Основна логіка обробки ТТН залежно від ролі користувача
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

# Функція додавання ТТН у блок для поточного дня (колонки A, B, C)
def add_ttn_to_sheet(ttn, username, chat_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # Припускаємо, що A1 містить заголовок, а ТТН записуються з A2
        col_a = worksheet.col_values(1)
        next_row = len(col_a) + 1
        worksheet.update(f"A{next_row}:C{next_row}", [[ttn, now, username]])
        bot.send_message(chat_id, f"✅ ТТН `{ttn}` додано!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка запису ТТН до таблиці!")
        user_nickname = username or str(chat_id)
        log_barcode_error(user_nickname, f"append_row error: {e}")

# Функція перевірки ТТН по всіх блоках (TTН зберігаються в A, E, I, M, Q, U)
def check_ttn_in_sheet(chat_id, ttn):
    try:
        ttn_block1 = worksheet.col_values(1)[1:]   # блок 1 (A)
        ttn_block2 = worksheet.col_values(5)[1:]   # блок 2 (E)
        ttn_block3 = worksheet.col_values(9)[1:]   # блок 3 (I)
        ttn_block4 = worksheet.col_values(13)[1:]  # блок 4 (M)
        ttn_block5 = worksheet.col_values(17)[1:]  # блок 5 (Q)
        ttn_block6 = worksheet.col_values(21)[1:]  # блок 6 (U)
    except Exception as e:
        bot.send_message(chat_id, "❌ Помилка зчитування таблиці для перевірки!")
        return

    all_ttns = ttn_block1 + ttn_block2 + ttn_block3 + ttn_block4 + ttn_block5 + ttn_block6
    if ttn in all_ttns:
        records = worksheet.get_all_values()
        found = False
        for row in records[1:]:
            if ttn in row:
                idx = row.index(ttn)
                date_time = row[idx + 1] if idx + 1 < len(row) else "невідомо"
                bot.send_message(chat_id, f"✅ Замовлення зібрано! ТТН: `{ttn}`\n🕒 Час: {date_time}", parse_mode="Markdown")
                found = True
                break
        if not found:
            bot.send_message(chat_id, f"❌ ТТН `{ttn}` не знайдено у базі!", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, f"❌ ТТН `{ttn}` не знайдено у базі!", parse_mode="Markdown")

# Функція зміщення блоків (6 блоків по 3 колонки)
def shift_table():
    """
    Зсуває дані в таблиці:
      - Блок 6 (U-V-W) ← блок 5 (Q-R-S)
      - Блок 5 (Q-R-S) ← блок 4 (M-N-O)
      - Блок 4 (M-N-O) ← блок 3 (I-J-K)
      - Блок 3 (I-J-K) ← блок 2 (E-F-G)
      - Блок 2 (E-F-G) ← блок 1 (A-B-C)
      - Блок 1 (A-B-C) очищається для нового дня
    Також оновлюються заголовки в A1, E1, I1, M1, Q1, U1 із відповідними датами.
    """
    try:
        block1_data = worksheet.get_values("A2:C")
        block2_data = worksheet.get_values("E2:G")
        block3_data = worksheet.get_values("I2:K")
        block4_data = worksheet.get_values("M2:O")
        block5_data = worksheet.get_values("Q2:S")
        worksheet.update("U2", block5_data)   # блок 5 → блок 6
        worksheet.update("Q2", block4_data)   # блок 4 → блок 5
        worksheet.update("M2", block3_data)   # блок 3 → блок 4
        worksheet.update("I2", block2_data)   # блок 2 → блок 3
        worksheet.update("E2", block1_data)   # блок 1 → блок 2
        # Очищення блоку 1 для нового дня
        row_count = len(block1_data)
        if row_count > 0:
            empty_data = [[""] * 3 for _ in range(row_count)]
            worksheet.update("A2", empty_data)

        # Оновлення заголовків із датами
        tz_kiev = pytz.timezone("Europe/Kiev")
        now_kiev = datetime.now(tz_kiev)
        dates = [
            now_kiev.date(),                           # блок 1 – поточний день
            now_kiev.date() - timedelta(days=1),         # блок 2
            now_kiev.date() - timedelta(days=2),         # блок 3
            now_kiev.date() - timedelta(days=3),         # блок 4
            now_kiev.date() - timedelta(days=4),         # блок 5
            now_kiev.date() - timedelta(days=5)          # блок 6
        ]
        worksheet.update("A1", [[str(dates[0])]])
        worksheet.update("E1", [[str(dates[1])]])
        worksheet.update("I1", [[str(dates[2])]])
        worksheet.update("M1", [[str(dates[3])]])
        worksheet.update("Q1", [[str(dates[4])]])
        worksheet.update("U1", [[str(dates[5])]])
    except Exception as e:
        print(f"Помилка при зсуві таблиці: {e}")

def run_shift_table_with_tz():
    tz_kiev = pytz.timezone("Europe/Kiev")
    now_kiev = datetime.now(tz_kiev)
    if now_kiev.strftime("%H:%M") == "00:00":
        shift_table()

# Функція розсилки повідомлень підписникам (рахуємо ТТН за поточний день із блоку 1, починаючи з A3)
def send_subscription_notifications():
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
                # Читаємо дані з колонки A, починаючи з третього рядка (A3 і далі)
                col_a = worksheet.col_values(1)[2:]
                count_ttn = sum(1 for x in col_a if x.strip() != "")
            except Exception as e:
                count_ttn = "Невідомо (помилка)"
            bot.send_message(chat_id, f"За сьогодні оброблено ТТН: {count_ttn}")
            subs[chat_id]["last_sent"] = today_str
    save_subscriptions(subs)

# Планувальник: розсилка повідомлень кожну хвилину та зсув таблиці о 00:00
def run_scheduler():
    schedule.every().minute.do(send_subscription_notifications)
    schedule.every().day.at("00:00").do(run_shift_table_with_tz)
    while True:
        schedule.run_pending()
        time.sleep(30)

#####################
# Головна функція
#####################
def main():
    # Запуск Flask-сервера для пінгування (для UptimeRobot)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запуск бота у фоновому потоці
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()

    # Запуск планувальника у головному потоці з обробкою KeyboardInterrupt
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("Shutting down gracefully (KeyboardInterrupt).")
        import sys
        sys.exit(0)

if __name__ == "__main__":
    main()
