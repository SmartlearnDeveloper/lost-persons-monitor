FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY auth_service/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY config_loader.py ./config_loader.py
COPY config.json ./config.json
COPY config ./config
COPY scripts ./scripts
COPY common ./common
COPY auth_service ./auth_service

ENV PYTHONPATH=/app \
    AUTH_SECRET_KEY=${AUTH_SECRET_KEY:-change_this_secret}

EXPOSE 58104

CMD ["uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "58104"]
