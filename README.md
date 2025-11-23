# Lost Persons Monitor

Lost Persons Monitor is a change-data-capture (CDC) platform that ingests lost-person reports, streams database changes through Kafka, computes aggregates with Apache Flink, and surfaces an operational dashboard plus PDF intelligence for responders. Each report automatically creates a case, tracks responsible agents over time, and updates KPIs in real time through WebSockets.

## Quick Start

1. **Install prerequisites** – Python 3.11+, Docker, and Docker Compose.
2. **Update/build images** – the producer image bundles `scripts/db_init.py`, so rebuild it whenever schemas change:
   ```bash
   docker compose build producer
   ```
3. **Reset the schema (optional but recommended)** – drops/recreates `lost_persons_db`, seeds contacts, and prints the resulting tables so you can confirm `case_responsible_history` and `responsible_contacts` exist:
   ```bash
   ./scripts/reset_db.sh
   ```
4. **Compile the Flink job** – run this every time streaming logic changes:
   ```bash
   mvn -f flink-job/pom.xml clean package
   ```
5. **Launch the stack** – spins up MySQL, Zookeeper, Kafka, Kafka Connect, Flink, producer, dashboard, case manager, etc.:
   ```bash
   docker compose up -d --build
   ```
6. **Register Debezium (if needed)** – `connector_init` tries automatically, but if logs show `curl: (7)` rerun:
   ```bash
   docker compose run --rm connector_init
   ```
7. **Verify Flink** – ensure the job is running:
   ```bash
   docker compose exec jobmanager /opt/flink/bin/flink list
   ```
8. **Optional local dev** – start individual APIs with uvicorn (e.g., `uvicorn producer.main:app --reload --port 58101`) and register the connector manually via `curl localhost:40125/connectors/`.

## Service & UI Map

| Service (container)        | Host Port | UI / Endpoint examples                                     |
|----------------------------|-----------|-------------------------------------------------------------|
| Producer (`producer_service`)   | 40140     | `http://localhost:40140/docs`, `/report_person/`             |
| Dashboard (`dashboard_service`) | 40145     | `/` landing page, `/report`, `/dashboard`, `/cases`, `/reports` |
| Case Manager (`case_manager_service`) | 40150     | `http://localhost:40150/docs` (FastAPI swagger)            |
| Kafka Connect              | 40125     | `http://localhost:40125/connectors/`                        |
| Flink JobManager           | 40130     | `http://localhost:40130/#/job/running`                      |

UI highlights:
- `/report`: submit reports (or auto-generate sample payloads) – every entry now creates a case and immediate responsible timeline.
- `/dashboard`: KPIs and charts refresh via WebSockets as soon as Debezium → Flink → MySQL writes new aggregates (age, gender, hourly).
- `/cases`: edit status, assign responsibles, log actions, download case PDFs (historial de responsables + acciones).
- `/reports`: generate PDF reports (alertas operativas, distribucción demográfica, análisis horario, casos sensibles, etc.).

## Real-Time Data Path

1. Producer validates payloads, normalizes timestamps using `REPORT_LOCAL_TZ`, and inserts into `persons_lost` plus `case_cases`.
2. Debezium reads MySQL binlogs (`poll.interval.ms=500`, `max.batch.size=256`) and emits JSON events to Kafka topics `lost_persons_server.*`.
3. Flink (`FLINK_LOCAL_TIMEZONE` configurable) consumes the topic, computes aggregates, and writes `agg_age_group`, `agg_gender`, `agg_hourly`.
4. Case Manager notifies the dashboard (via `/internal/refresh`) whenever cases, actions, or responsible assignments change so KPIs update instantly even without new CDC events.
5. Dashboard listeners (Kafka + WebSocket clients) trigger `refreshDashboard()` to update charts, KPIs, and tables without manual reloads.

## Environment Variables

- `REPORT_LOCAL_TZ` – producer timezone (default `America/Guayaquil`).
- `FLINK_LOCAL_TIMEZONE` – Flink local timezone for `TO_TIMESTAMP_LTZ`.
- `CASE_MANAGER_URL` / `CASE_MANAGER_PUBLIC_URL` – internal vs. browser-facing URLs used by dashboard.
- `DASHBOARD_REFRESH_URL` – internal endpoint (`http://dashboard:58102/internal/refresh`) hit by case manager after mutations.

## Validation Checklist

1. **Services up** – `docker compose ps` should show every container `Up`.
2. **Connector RUNNING** – `docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status`.
3. **Flink job RUNNING** – `docker compose exec jobmanager /opt/flink/bin/flink list`.
4. **UI sanity** – open `http://localhost:40145/dashboard` and `http://localhost:40145/cases`, submit a report, assign a responsable, log an action, and verify charts/ tables update immediately.
5. **PDF check** – from `/cases`, click “Reporte” to ensure the PDF lists Prioridad en español, historial de responsables y acciones con el responsable correcto.

## Repository Structure

- `producer/` – REST API for submissions (FastAPI + SQLAlchemy).
- `dashboard/` – public dashboard, report forms, PDF generators.
- `case_manager/` – case CRUD, KPI endpoints, responsible and action timelines.
- `flink/` & `flink-job/` – streaming job sources, sinks, connectors.
- `scripts/` – database bootstrap (`db_init.py`), reset helpers, health checks.
- `config/` – shared configuration (DB creds, Debezium connector, case priorities, etc.).

## Testing

- Producer & dashboard: `pytest` suites under `tests/producer`, `tests/dashboard` (use FastAPI `TestClient` + SQLAlchemy fixtures).
- Scripts: dry-run logic around `db_init.py`, `stack_check.py` (mock engines/config).
- Manual flows: submit a report, verify Kafka events, confirm aggregates in MySQL, and download case PDFs.

## Troubleshooting

- **Debezium not registered** – rerun `docker compose run --rm connector_init` after Kafka Connect is healthy.
- **Missing tables** – rebuild producer image (`docker compose build producer`) and re-run `./scripts/reset_db.sh` (script now prints table list).
- **Dashboard “NetworkError”** – check `docker compose logs dashboard` & `case_manager` for 500s; ensure schema includes `case_responsible_history`, `responsible_contacts`, and `case_actions.responsible_name`.
- **Charts lag** – confirm connector status; `poll.interval.ms=500` should keep latency < 1s. Use `/case-responsibles/catalog` and `/cases/{id}/responsibles` to ensure responsibles endpoints are reachable.

Refer to `AGENTS.md` files in each module for service-specific conventions and contribution guidelines.
