"""Приклад config.py. Скопіюйте у config.py та заповніть (config.py у .gitignore).

Альтернативно всі значення можна задати через змінні оточення з тими ж іменами
(зручно для Render). Для Render найпростіше задати env-змінні:
  TOKEN, GOOGLE_SHEET_URL, GOOGLE_SHEET_URL_USERS,
  GOOGLE_SHEETS_CREDENTIALS_JSON  (увесь вміст JSON-ключа одним рядком).
"""

TOKEN = "..."

# Локально — шлях до JSON-ключа сервісного акаунта Google.
# На Render замість шляху задайте env-змінну GOOGLE_SHEETS_CREDENTIALS_JSON
# зі вмістом цього JSON.
GOOGLE_SHEETS_CREDENTIALS = "..."

# Посилання на дві Google-таблиці
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/.../edit"
GOOGLE_SHEET_URL_USERS = "https://docs.google.com/spreadsheets/d/.../edit?gid=0#gid=0"
