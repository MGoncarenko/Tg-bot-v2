FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Kiev

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libgl1 \
    libglib2.0-0 \
    libzbar0 \
    # За потреби інші пакети:
    # libsm6 libxext6 libxrender-dev ...
    && ln -sf /usr/share/zoneinfo/Europe/Kiev /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["python", "bot.py"]
