# Lineamientos del Producer

## Descripción
- API FastAPI (`producer/main.py`) que recibe reportes de personas perdidas, calcula edad y registra cada entrada en MySQL.
- Cada reporte crea automáticamente el caso asociado (`case_cases`) para que el case manager y el dashboard estén sincronizados.
- Servicio `producer_service` expuesto en `http://localhost:40140` dentro de Docker Compose.

## Configuración
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r producer/requirements.txt
uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101
```
- En contenedor: `docker compose up -d producer` (o `docker compose up -d --build` para reconstruir imagen).

## Reglas clave
- Importa los modelos de `scripts/db_init.py` para mantener el ORM alineado con la base.
- Cada inserción debe envolver `db.add()`, `db.flush()` y `db.commit()`; usa `db.rollback()` en excepciones.
- Respectar `REPORT_LOCAL_TZ` para sellar `lost_timestamp` con hora local.
- Tests en `tests/producer/` (usar `fastapi.TestClient` y DB mockeada).
