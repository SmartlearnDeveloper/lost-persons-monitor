# Lost Persons Monitor

Lost Persons Monitor es una plataforma CDC que recibe reportes de personas perdidas, los replica mediante Debezium/Kafka, genera agregados con Flink y expone dashboards y reportes PDF para equipos de respuesta. Cada reporte crea un caso, registra responsables y acciones y actualiza indicadores en tiempo real.

## Guía rápida

1. **Requisitos**: Python 3.11+, Docker y Docker Compose.
2. **Reconstruir producer** (si cambió `scripts/db_init.py`):
   ```bash
   docker compose build producer
   ```
3. **Reiniciar la base** (opcional, recomendado antes de demos):
   ```bash
   ./scripts/reset_db.sh
   ```
   Este script levanta MySQL, elimina y crea `lost_persons_db`, y al final ejecuta `SHOW TABLES FROM lost_persons_db` para confirmar que existen `case_responsible_history`, `responsible_contacts`, `auth_users`, `auth_roles`, etc.
4. **Compilar Flink**:
   ```bash
   mvn -f flink-job/pom.xml clean package
   ```
5. **Levantar la pila completa (incluye auth_service, dashboard, producer, case manager, Flink, Kafka, Debezium)**:
   ```bash
   docker compose up -d --build
   ```
6. **Iniciar sesión**: visita `http://localhost:40145/login` y usa las credenciales por defecto `admin / admin123` para generar un token JWT que desbloquea los módulos de reporte, dashboard, reportes PDF y gestión de casos.
7. **Verificar Debezium** (si `connector_init` falló con `curl: (7)`):
   ```bash
   docker compose run --rm connector_init
   ```
8. **Comprobar servicios**:
   ```bash
   docker compose exec jobmanager /opt/flink/bin/flink list
   docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status
    docker compose exec auth_service curl -s http://localhost:58104/health
   ```
9. **Modo local opcional**: levanta un servicio puntual con `uvicorn` y registra el conector manualmente (`curl localhost:40125/connectors/`).

## URLs principales

| Servicio / UI                      | URL                                        |
|------------------------------------|---------------------------------------------|
| Reporte de personas perdidas       | `http://localhost:40145/report`             |
| Dashboard en tiempo real           | `http://localhost:40145/dashboard`          |
| Gestión de casos + PDF             | `http://localhost:40145/cases`              |
| Catálogo de reportes PDF           | `http://localhost:40145/reports`            |
| Portal de autenticación            | `http://localhost:40145/login`              |
| API del servicio de autenticación  | `http://localhost:40155/docs`               |
| API del producer                   | `http://localhost:40140/docs`               |
| API del case manager               | `http://localhost:40150/docs`               |
| Kafka Connect                      | `http://localhost:40125/connectors/`        |

## Autenticación y roles

- `auth_service` expone `/auth/login`, `/auth/register`, `/auth/assign-role` y `/auth/permissions`. Usa el mismo MySQL para guardar usuarios, roles y permisos.
- Roles disponibles:
  - `reporter`: puede registrar personas perdidas (`report`) y ver estadísticas básicas (`dashboard`).
  - `analyst`: incluye permisos para descargar reportes PDF (`pdf_reports`).
  - `coordinator`: añade acceso al case manager (`case_manager`).
  - `admin`: suma `manage_users` para crear/editar usuarios desde `/auth/register` y `/auth/assign-role`.
- Todos los frontales (`/report`, `/dashboard`, `/cases`, `/reports`) redirigen a `/login` si no detectan un JWT vigente. El login guarda el token en `localStorage` y en una cookie HTTP-only (`lpm_token`) para que FastAPI valide tanto `fetch` como los formularios tradicionales (PDF).
- Para automatizar pruebas, solicita un token con cURL:
  ```bash
  curl -X POST http://localhost:40155/auth/login \
       -H "Content-Type: application/x-www-form-urlencoded" \
       -d 'username=admin&password=admin123'
  ```
  El `access_token` debe enviarse como `Authorization: Bearer <token>` en cada microservicio.

## Flujo de datos

1. El `producer` valida el payload, calcula edad y marca `lost_timestamp` usando `REPORT_LOCAL_TZ` (por defecto `America/Guayaquil`).
2. Debezium (configurado con `poll.interval.ms=500` y `max.batch.size=256`) lee los binlogs y publica en `lost_persons_server.*`.
3. Flink (`FLINK_LOCAL_TIMEZONE`) agrupa por edad, género y hora y guarda los resultados en MySQL (`agg_age_group`, `agg_gender`, `agg_hourly`).
4. El case manager expone `/case-stats/*`, `/cases/{id}/actions`, `/cases/{id}/responsibles` y notifica al dashboard vía `/internal/refresh` después de cualquier cambio.
5. El dashboard consume los agregados (SQL o WebSocket) y actualiza tarjetas, gráficas, historial de acciones y responsables en tiempo real; los reportes PDF incluyen ambos historiales.

## Variables de entorno clave

- `REPORT_LOCAL_TZ`: zona horaria usada por el producer.
- `FLINK_LOCAL_TIMEZONE`: zona horaria para las funciones de fecha/hora en Flink.
- `CASE_MANAGER_URL` / `CASE_MANAGER_PUBLIC_URL`: endpoints interno y expuesto para el dashboard.
- `DASHBOARD_REFRESH_URL`: ruta interna (`http://dashboard:58102/internal/refresh`) que el case manager invoca tras cada cambio.
- `AUTH_SECRET_KEY`: clave compartida para firmar/verificar los JWT. Debe mantenerse idéntica en `auth_service`, producer, dashboard y case manager.
- `AUTH_PUBLIC_URL`: URL expuesta del servicio de autenticación (`http://localhost:40155` en local).
- `AUTH_TOKEN_URL`: endpoint usado por Swagger/OAuth2 (`http://localhost:40155/auth/login`).
- `AUTH_DEFAULT_ADMIN_USERNAME` / `AUTH_DEFAULT_ADMIN_PASSWORD`: credenciales creadas automáticamente por `db_init.py` cuando la base se reinicia.

## Validación tras despliegue

1. `docker compose ps` → todos los contenedores (incluido `auth_service`) deben estar “Up”.
2. `SHOW TABLES FROM lost_persons_db` → verifica que existan `case_responsible_history`, `responsible_contacts`, `case_actions` con `responsible_name` y todas las tablas `auth_*`.
3. Envía un reporte desde `/report`, asigna un responsable en `/cases`, registra una acción y descarga el PDF para confirmar que Prioridad (Alta/Media/Baja) y el responsable aparecen en español.
4. Observa `/dashboard`: los KPIs y gráficas deberían reaccionar sin recargar.

## Estructura del repo

- `producer/`: API de entrada, crea personas y casos.
- `case_manager/`: control de casos, acciones, responsables y KPIs.
- `dashboard/`: Jinja + API para dashboard, formularios y reportes PDF.
- `auth_service/`: microservicio FastAPI (JWT + roles) que centraliza login/registro.
- `common/`: utilitarios compartidos (por ejemplo `common/security.py`). Cada vez que edites este directorio, recompila producer, dashboard, case_manager y auth_service.
- `flink/`, `flink-job/`: job de streaming (SQL/Java) que alimenta las tablas agregadas.
- `scripts/`: herramientas (`db_init.py`, `reset_db.sh`, `stack_check.py`).
- `config/`: plantillas (`config.json`, `debezium-connector.json`, prioridades, etc.).

## Pruebas

- Usa `pytest` con `fastapi.TestClient` en los servicios FastAPI (productor, dashboard, case_manager).
- Mockea la base con SQLite o Sessions en memoria para evitar dependencias externas.
- Incluye pasos manuales (por ejemplo, generar un PDF y comprobar encabezados) en la descripción de cada PR.

## Problemas frecuentes

- **Conector Debezium no registrado**: reejecuta `docker compose run --rm connector_init` y valida con `curl http://localhost:40125/connectors/`.
- **Error “Unknown column…”**: reconstruye la imagen del producer (`docker compose build producer`) y corre `./scripts/reset_db.sh` para crear las columnas/ tablas nuevas.
- **Dashboard muestra “NetworkError”**: revisa `docker compose logs dashboard case_manager`; usualmente indica que falta una migración de base o que el case manager no puede alcanzar MySQL.
- **Gráficas no se actualizan**: confirma que el job de Flink está “RUNNING” y que el conector Debezium sigue en `state: RUNNING`.

Consulta los `AGENTS.md` de cada subdirectorio para lineamientos específicos (por ejemplo, cómo ejecutar pruebas del dashboard o empaquetar el job de Flink).
