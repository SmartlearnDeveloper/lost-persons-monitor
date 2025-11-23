# Lineamientos del Dashboard

## Descripción
- Servicio FastAPI (`dashboard/main.py`) que entrega HTML (Jinja) y endpoints JSON.
- Funcionalidades clave: formularios de reporte, dashboard operativo, gestión de casos (edición, responsables, acciones), reportes PDF.
- Corre como `dashboard_service` en Docker Compose (`http://localhost:40145`).

## Configuración y ejecución
- Entorno local:
  ```bash
  python -m venv .venv && source .venv/bin/activate
  pip install -r dashboard/requirements.txt
  uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102
  ```
- En contenedor: `docker compose up -d dashboard` (se recomienda `docker compose up -d --build` para tomar cambios).
- Las plantillas Jinja se actualizan automáticamente en modo `--reload`; en Docker se debe reconstruir el servicio.

## Interacciones principales
- `/dashboard`: KPIs y gráficas (Chart.js) que se refrescan vía WebSockets cuando el case manager notifica o Flink actualiza agregados.
- `/cases`: muestra la tabla “Personas reportadas perdidas”, permite editar estado/ prioridad, asignar responsables, registrar acciones y descargar reportes PDF.
- Reportes PDF incluyen “Historial de responsables” y “Historial de acciones”, mostrando la prioridad en español y el responsable que estaba activo al crear cada acción.

## Recomendaciones
- Mantén las traducciones y etiquetas en español (HTML/JS/PDF).
- Usa `CASE_MANAGER_URL`/`CASE_MANAGER_PUBLIC_URL` en `docker-compose.yml` para que la UI llame al case manager correctamente.
- Verifica que los endpoints `/case-responsibles/catalog`, `/cases/{id}/responsibles` y `/cases/{id}/actions` respondan 200 antes de probar la UI (revisa `docker compose logs dashboard case_manager`).
- Tests: `pytest` + `fastapi.TestClient` (ver `tests/dashboard/`). Mockea MySQL si es posible.
