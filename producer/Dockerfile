FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY producer/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY config_loader.py ./config_loader.py
COPY config.json ./config.json
COPY config ./config
COPY scripts ./scripts
COPY producer ./producer

ENV PYTHONPATH=/app
EXPOSE 58101

CMD ["uvicorn", "producer.main:app", "--host", "0.0.0.0", "--port", "58101"]
