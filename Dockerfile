FROM python:3.11-slim

# Оновлюємо індекс пакетів і встановлюємо потрібні бібліотеки, включаючи tzdata для часової зони
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libzbar0 \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Встановлюємо часову зону на Europe/Kiev
ENV TZ=Europe/Kiev
RUN ln -snf /usr/share/zoneinfo/Europe/Kiev /etc/localtime && echo "Europe/Kiev" > /etc/timezone

# Створюємо робочу директорію
WORKDIR /app

# Копіюємо requirements.txt і встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь проєкт
COPY . .

# Запускаємо бот
CMD ["python", "bot.py"]
