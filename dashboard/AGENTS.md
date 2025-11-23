# Lineamientos del Dashboard

## Descripción
- Servicio FastAPI (`dashboard/main.py`) que entrega HTML (Jinja) y endpoints JSON.
- Funcionalidades clave: formularios de reporte, dashboard operativo, gestión de casos (edición, responsables, acciones), reportes PDF.
- Corre como `dashboard_service` en Docker Compose (`http://localhost:40145`). Expone `/login`, gestiona las cookies (`lpm_token`) y consume el servicio `auth_service` (`http://auth_service:58104`).

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
- `/login` -> obtiene un JWT desde `auth_service`, lo guarda en localStorage+cookie y redirige al módulo solicitado. Si el token expira, la UI llama a `LPMAuth.requireAuth()` y redirige automáticamente.

## Autenticación
- Todas las vistas verifican el token con `window.LPMAuth` (ver `dashboard/static/js/auth.js`). Si falta, redirigen a `/login?next=/ruta`.
- `auth_service` se alcanza por `AUTH_SERVICE_URL` (interno) y `AUTH_PUBLIC_URL` (navegador). Asegúrate de exponer `AUTH_SECRET_KEY` y `AUTH_TOKEN_URL` en el contenedor para que `common/security.py` pueda validar JWTs.
- El login crea una cookie HTTP-only (`lpm_token`) que `common/security` consume. Esa cookie se usa para los formularios PDF; no la cambies sin actualizar `common/security.py` y `auth.js`.
- Cada cambio en `common/` requiere reconstruir `dashboard`/`case_manager`/`producer`/`auth_service` para mantener la lógica de seguridad alineada.

## Recomendaciones
- Mantén las traducciones y etiquetas en español (HTML/JS/PDF).
- Usa `CASE_MANAGER_URL`/`CASE_MANAGER_PUBLIC_URL` en `docker-compose.yml` para que la UI llame al case manager correctamente.
- No hardcodees URLs del auth service; usa `AUTH_PUBLIC_URL` para JS (`window.LPM_AUTH_LOGIN_URL`) y `AUTH_SERVICE_URL` para llamadas internas.
- Verifica que los endpoints `/case-responsibles/catalog`, `/cases/{id}/responsibles` y `/cases/{id}/actions` respondan 200 antes de probar la UI (revisa `docker compose logs dashboard case_manager`).
- Tests: `pytest` + `fastapi.TestClient` (ver `tests/dashboard/`). Mockea MySQL si es posible.
