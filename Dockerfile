# Використовуємо офіційний образ Python (3.9-slim або будь-яку іншу потрібну версію)
FROM python:3.9-slim

# Встановлюємо змінні оточення. PYTHONUNBUFFERED=1 гарантує негайний вивід логів, TZ задає часовий пояс як Київський.
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Kiev

# Оновлюємо apt-кеш, встановлюємо tzdata для роботи з часовими поясами
RUN apt-get update && apt-get install -y tzdata && \
    ln -sf /usr/share/zoneinfo/Europe/Kiev /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Встановлюємо робочу директорію в контейнері
WORKDIR /app

# Копіюємо файл залежностей та встановлюємо їх
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Копіюємо увесь проект у контейнер
COPY . /app

# Вказуємо команду для запуску бота
CMD ["python", "bot.py"]
