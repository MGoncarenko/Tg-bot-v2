FROM python:3.11-slim

# Встановлюємо libzbar для pyzbar
RUN apt-get update && apt-get install -y libzbar0

# Створюємо робочу директорію
WORKDIR /app

# Копіюємо requirements.txt і встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо увесь код (крім того, що у .dockerignore)
COPY . .

# Запускаємо наш бот
CMD ["python", "bot.py"]
