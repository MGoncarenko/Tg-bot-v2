FROM python:3.11-slim

# Оновлюємо індекс пакетів і встановлюємо потрібні бібліотеки:
# 1) libzbar0 – для pyzbar (штрих-коди)
# 2) libgl1-mesa-glx, libsm6, libxext6, libxrender-dev – для OpenCV
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Створюємо робочу директорію
WORKDIR /app

# Копіюємо requirements.txt і встановлюємо Python-залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь проєкт (за винятком того, що у .dockerignore)
COPY . .

# Запускаємо бот
CMD ["python", "bot.py"]
