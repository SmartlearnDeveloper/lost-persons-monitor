FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    libpng-dev \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

COPY dashboard/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY config_loader.py ./config_loader.py
COPY config.json ./config.json
COPY config ./config
COPY scripts ./scripts
COPY common ./common
COPY dashboard ./dashboard

ENV PYTHONPATH=/app
EXPOSE 58102

CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "58102"]
