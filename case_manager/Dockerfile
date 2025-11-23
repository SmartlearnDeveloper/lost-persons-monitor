FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY case_manager/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY config_loader.py ./config_loader.py
COPY config.json ./config.json
COPY config ./config
COPY scripts ./scripts
COPY common ./common
COPY case_manager ./case_manager

ENV PYTHONPATH=/app
EXPOSE 58103

CMD ["uvicorn", "case_manager.main:app", "--host", "0.0.0.0", "--port", "58103"]
