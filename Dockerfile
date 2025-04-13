# Використовуємо офіційний образ Python (3.9-slim або потрібну версію)
FROM python:3.9-slim

# Встановлюємо змінні оточення
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Kiev

# Оновлення системи, встановлення tzdata і бібліотек для OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libgl1 \
    libglib2.0-0 \
    # Якщо потрібно, можна додати сюди інші залежності для OpenCV:
    # libsm6 libxext6 libxrender-dev
    && ln -sf /usr/share/zoneinfo/Europe/Kiev /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Вказуємо робочу директорію
WORKDIR /app

# Копіюємо файл із залежностями
COPY requirements.txt /app/requirements.txt

# Встановлюємо залежності Python
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код у контейнер
COPY . /app

# Вказуємо команду за замовчуванням
CMD ["python", "bot.py"]
