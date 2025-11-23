# Producer Guidelines

## Overview
- FastAPI service (`producer.main`) recibe reportes de personas perdidas, calcula edad y marca el timestamp con `REPORT_LOCAL_TZ`.
- Cada reporte crea automáticamente la persona y un registro en `case_cases`; el case manager y el dashboard dependen de esa consistencia.
- Se ejecuta como `producer_service` (puerto 40140) dentro de Docker Compose.

## Build & Run
- `python -m venv .venv && source .venv/bin/activate`
- `pip install -r producer/requirements.txt`
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`
- En contenedor: `docker compose up -d producer`

## Key Notes
- Importa los modelos desde `scripts/db_init.py` para mantener sincronía.
- Cada inserción debe manejar transacciones (`db.flush()` + `db.commit()`).
- Logs deben evitar datos sensibles; sólo mostrar campos relevantes.
- Tests en `tests/producer/` usando `fastapi.TestClient` + DB mock.
