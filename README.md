# Lost Persons Monitor

Lost Persons Monitor is a change-data-capture (CDC) pipeline that ingests lost-person reports, streams database changes through Kafka, computes real-time aggregates with Apache Flink, and surfaces operational dashboards for emergency responders.

## Quick Start

1. Ensure Python 3.11+ and Docker are installed.
2. Run `python scripts/db_init.py` to create MySQL schemas (requires MySQL reachable at the host/port defined in `config.json`).
3. Create or activate a Python virtual environment:  
   `if [ ! -d .venv ]; then python -m venv .venv; fi && source .venv/bin/activate`  
   _(The repository also contains service-specific environments under `producer/venv` and `dashboard/venv`; activate one with `source producer/venv/bin/activate` or `source dashboard/venv/bin/activate` if you prefer to reuse them.)_
4. Install dependencies:  
   `pip install -r producer/requirements.txt`  
   `pip install -r dashboard/requirements.txt`
5. (Optional but recommended) Reset the MySQL schema to a blank slate:  
   `./scripts/reset_db.sh`  
   _(Esto inicia solo el contenedor de MySQL, espera a que esté saludable, elimina y recrea las tablas para comenzar sin registros.)_
6. Compile the Flink job (run this whenever you change the streaming logic):  
   `mvn -f flink-job/pom.xml clean package`
7. Build and launch the full microservice stack (introduced in `version_2_0_0`):  
   `docker compose up -d --build`
8. Wait for the `connector_init` helper to finish (it registers the Debezium connector automatically with `poll.interval.ms=500` and `max.batch.size=256` to minimize end-to-end latency). _Known issue_: Kafka Connect sometimes takes longer to boot, causing `connector_init` to exit with `curl: (7)`; if the logs show that error, rerun  
   `docker compose run --rm connector_init` once the `connect` service is healthy.
9. The JobManager automatically runs the packaged Flink job (`flink run -d /opt/flink/usrlib/lost-persons-job.jar`) after its REST endpoint is reachable and Kafka becomes available. Use  
   `docker compose exec jobmanager /opt/flink/bin/flink list`  
   to verify the aggregation job is RUNNING, or rerun `mvn clean package` + `docker compose up -d --build jobmanager taskmanager` anytime you change streaming logic.
10. For local-only experiments, you can still start an individual API with uvicorn (e.g., `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`), but the recommended workflow is through Docker so each service gets its own containerized runtime with the proper environment variables (`REPORT_LOCAL_TZ`, `FLINK_LOCAL_TIMEZONE`, etc.).

### Service Port Map

| Service            | Host Port | Container Port |
|--------------------|-----------|----------------|
| MySQL              | 40110     | 3306           |
| Zookeeper          | 40115     | 2181           |
| Kafka (PLAINTEXT)  | 40120     | 9092           |
| Kafka Connect      | 40125     | 8083           |
| Flink JobManager   | 40130     | 8081           |
| Flink TaskManager* | 40135     | 6123           |
| Producer API       | 40140     | 58101          |
| Dashboard API      | 40145     | 58102          |
| Case Manager API   | 40150     | 58103          |

\* TaskManager port exposure is optional and used primarily for debugging RPC calls.

## Bringing the Stack Up & Accessing the UIs

Once `docker compose up -d --build` finishes, the services with navegable UI endpoints are:

| URL | Description |
|-----|-------------|
| `http://localhost:40145/` | Página principal con accesos directos a formularios, dashboard y reportería PDF. |
| `http://localhost:40145/report` | Formulario para reportar personas perdidas (incluye botón “Generar aleatorio” y vista previa de carga/respuesta). Internamente hace `POST` a `http://localhost:40140/report_person/`. |
| `http://localhost:40145/dashboard` | Panel operativo con KPIs y gráficas. Usa WebSockets para refrescarse tan pronto Debezium → Kafka → Flink escriben nuevos agregados. |
| `http://localhost:40145/reports` | Catálogo de reportes PDF (Alertas operativas, Distribución demográfica, Horaria, Sensibles, etc.). Cada enlace abre un formulario `POST` dedicado. |
| `http://localhost:40145/cases` | Gestión de casos: crea/actualiza casos, registra acciones, marca prioridades y dispara los WebSockets del dashboard para que los KPIs se actualicen al instante. |
| `http://localhost:40150/docs` | Documentación interactiva de la API del case manager (FastAPI docs). |
| `http://localhost:40140/docs` (opcional) | Swagger UI del producer si ejecutas `uvicorn` fuera de Docker. |

Parada limpia: `docker compose down`. Para reiniciar con imágenes frescas sin tocar el volumen de MySQL ejecuta `docker compose down` seguido de `docker compose up -d --build`.

**Recomendaciones post-arranque**
- Verifica Debezium y Kafka Connect:  
  `docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status`  
  debería devolver `state: RUNNING`.
- Confirma el JobManager:  
  `docker compose exec jobmanager /opt/flink/bin/flink list`
- Revisa que los puertos mapeados (40140, 40145, 40150) respondan vía navegador o `curl`.

## PDF Reports

- **Alertas operativas** (`/reports/operational-alerts`) — configure a date and hour window, then generate a PDF that includes a gender distribution chart, location highlights, and a detailed roster of active cases. The PDF is assembled with Pandas, Matplotlib, and ReportLab to deliver a field-ready summary.
- **Distribucion demografica** (`/reports/demographic-distribution`) — analiza la composicion por grupo etario y genero para un periodo determinado. Entrega graficos de barras/series y una tabla cruzada con totales por segmento.
- **Mapa de ubicaciones** (`/reports/geographic-distribution`) — consolida reportes por ciudad/estado, genera graficos tematicos de concentracion y una tabla ordenada por zonas para planear despliegues.
- **Analisis horario** (`/reports/hourly-analysis`) — identifica picos por hora, produce graficas comparativas y resume las horas mas criticas mediante tablas y mapas de calor.
- **Resumen ejecutivo** (`/reports/executive-summary`) — sintetiza indicadores clave, graficas rapidas y casos recientes en un PDF listo para compartir con equipos directivos.
- **Casos sensibles** (`/reports/sensitive-cases`) — filtra reportes mediante el catalogo configurable `config/sensitive_terms.json` y resalta alertas medicas o situaciones prioritarias.
- Todos los dashboards muestran la marca corporativa y un pie actualizado automáticamente con el año y propietario legal.
- Mas formatos se podran sumar reutilizando el mismo pipeline de datos y librerias graficas.
- Each reporte permite elegir orientacion (`portrait` o `landscape`) y ajusta automaticamente tablas y graficas para respetar los margenes del documento.

## Producer API

- `POST /report_person/` — accepts the JSON payload produced by the reporter GUI (see `producer/models.py`).
- `GET /report_person/?limit=10` — returns the most recent reports for manual verification.
- `GET /` — health message describing available endpoints.

## Case Manager API

- `GET /cases` — list and filter active cases with pagination and search.
- `POST /cases` / `PATCH /cases/{id}` — create or update case metadata, statuses and resolution details.
- `POST /cases/{id}/actions` — append actions to a case timeline for audit tracking.
- `GET /cases/stats/summary` — summary KPIs (total, resolved, pending, average response).
- `GET /cases/stats/time-series?range=24h|7d|30d` — time-series data for reported vs resolved cases.
- Case data is backed by the new schema (`case_cases`, `case_actions`) created via `scripts/db_init.py`.
- Personaliza prioridades (`config/case_priorities.json`) y tipos de acción (`config/case_action_types.json`) sin tocar el código.

## Real-Time Data Path

1. Producer guarda `persons_lost` usando `REPORT_LOCAL_TZ` (por defecto `America/Guayaquil`) y crea automáticamente un caso relacionado.
2. Debezium (MySQL connector) vigila el binlog con `poll.interval.ms=500`, publica eventos JSON en `lost_persons_server.lost_persons_db.persons_lost`.
3. El job de Flink (`lost-persons-job.jar`) consume el tópico, aplica `HOUR(TO_TIMESTAMP_LTZ(...))` usando `FLINK_LOCAL_TIMEZONE`, luego escribe agregados en `agg_age_group`, `agg_gender` y `agg_hourly`.
4. El dashboard escucha Kafka mediante `aiokafka` y WebSockets; cada evento dispara `refreshDashboard()` para refrescar KPIs y gráficas sin recargar la página.
5. Cambios en los casos (resueltos, acciones, etc.) viajan por el case manager: cada `POST/PATCH` notifica al dashboard (`/internal/refresh`) para que los KPI (calculados desde `/case-stats/*`) reaccionen inmediatamente, aunque no haya nuevos eventos en `persons_lost`.

## Documentation Index

- Start with the nearest `AGENTS.md` file in any directory to see contributor guidance tailored to that service or package. The root `AGENTS.md` outlines project-wide practices, while subdirectories (e.g., `producer/AGENTS.md`, `dashboard/AGENTS.md`) provide focused instructions.
- Infrastructure diagrams, historical conversations, and additional context remain in `lost-persons-monitor.md`.
- `scripts/reset_db.sh` deja la base en blanco (cae cualquier esquema previo y vuelve a correr `db_init` dentro del contenedor). Útil antes de demos.
- `scripts/run_flink_job.sh` es útil si necesitas resubir manualmente el job de Flink después de recompilar el jar.

Refer to service-specific `AGENTS.md` files for detailed testing, deployment, and security practices.

## Environment Variables

- `REPORT_LOCAL_TZ`: zona horaria (IANA) usada por el producer para sellar `lost_timestamp` (ej. `America/Guayaquil`).
- `FLINK_LOCAL_TIMEZONE`: zona usada por Flink para funciones `TO_TIMESTAMP_LTZ` / `HOUR` (misma sugerencia que arriba).
- `CASE_MANAGER_URL` / `CASE_MANAGER_PUBLIC_URL`: endpoint interno y público consumidos por el dashboard.
- `DASHBOARD_REFRESH_URL`: URL interna para que el case manager dispare refrescos (`http://dashboard:58102/internal/refresh` por defecto).

Configura estos valores en `docker-compose.yml` antes de construir los contenedores si despliegas en otra región.

## Versioning & Releases

- Current release: `version_2_0_0` (see `VERSION`) — first microservice-based delivery with Dockerized FastAPI services.
- Previous stable: `version_1_0_0` (monolithic uvicorn processes, documented for reference in release notes).
- Release notes live in `RELEASE_NOTES.md` and are updated alongside tags. Mention any open investigations (e.g., Debezium automation) when tagging.

## Validation

After bringing the stack up, run `python scripts/stack_check.py` to hit the key service endpoints (producer, dashboard, case manager, and Kafka Connect). The script exits with a non-zero status if any check fails, making it suitable for CI or quick sanity checks before demos.
