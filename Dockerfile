FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Kiev

# opencv-python-headless потребує мінімум системних бібліотек;
# zbar більше не потрібен (перейшли на zxing-cpp).
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libgl1 \
    libglib2.0-0 \
    && ln -sf /usr/share/zoneinfo/Europe/Kiev /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["python", "-m", "app.main"]
