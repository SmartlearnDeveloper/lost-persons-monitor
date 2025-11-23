# Repository Guidelines

## Project Overview
- Lost Persons Monitor is a CDC pipeline: the `producer` writes reports to MySQL, Debezium streams binlog events into Kafka, Flink aggregates them, and the `dashboard` renders live intelligence.
- As of `version_2_0_0` the system ships as a Docker-based microservice architecture: MySQL, Zookeeper, Kafka, Kafka Connect, Flink, Producer, Dashboard, Case Manager, and a helper container wire together via `docker compose`.
- Docker Compose keeps services decoupled while delivering low-latency snapshots (age, gender, hourly distributions) for responders.

## Project Structure & Module Organization
- `producer/` is the sole write surface into MySQL; expanding ingestion flows happens here.
- `dashboard/` consumes the aggregated tables created by Flink to render HTML and JSON endpoints.
- `scripts/db_init.py` defines SQLAlchemy ORM tables (personas, agregaciones y casos) and provisions schema; run it after schema edits.
- `flink/` stores `flink_sql_job.sql` and connector JARs that mount into the JobManager/TaskManager images.
- `config.json` centralizes local credentials and ports, while `debezium-connector.json` registers the Kafka Connect connector.
- `case_manager/` exposes a FastAPI module for CRUD operations on cases, action timelines, and KPI endpoints consumed by the dashboard.

## Build & Test Commands
- Prepare a Python env (recommended: `python -m venv .venv && source .venv/bin/activate`; legacy environments remain under `producer/venv` and `dashboard/venv` and can be reactivated with `source producer/venv/bin/activate` or `source dashboard/venv/bin/activate` if needed).
- `pip install -r producer/requirements.txt`, `pip install -r dashboard/requirements.txt`, and `pip install -r case_manager/requirements.txt` inside the active env to install service deps.
- `python scripts/db_init.py` prepares the schema (including case tables); rerun after ORM edits.
- To reset the database to zero records, run `./scripts/reset_db.sh` (arranca MySQL, borra el esquema y vuelve a ejecutar `db_init.py` dentro del contenedor).
- Build the Flink job jar with `mvn -f flink-job/pom.xml clean package` before starting containers so the JobManager can submit it.
- `docker compose up -d --build` launches the entire microservice stack (MySQL, Kafka, Kafka Connect, Flink, and the FastAPI services) using the 4011x–4015x host port scheme. The `connector_init` helper container automatically registers Debezium on startup; rerun it with `docker compose run --rm connector_init` when connector config changes. The JobManager automatically runs `lost-persons-job.jar` once it is healthy so aggregates stay fresh. Use `docker compose down` to stop the stack.
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`, `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`, and `uvicorn case_manager.main:app --reload --host 0.0.0.0 --port 58103` run APIs locally; if you bypass Docker, register CDC manually with `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:40125/connectors/ -d @debezium-connector.json`.

## Code Style Guidelines
- Follow PEP 8: four-space indentation, snake_case functions, PascalCase classes, and descriptive module names.
- Use type hints and Pydantic models for API contracts, and centralize configuration access rather than duplicating file parsing.
- Keep aggregation helpers or shared ORM entities with the existing definitions in `scripts/db_init.py`.

## Testing Instructions
- Add FastAPI integration tests under `/tests` (e.g., `test_<feature>.py`) using `pytest` and `fastapi.TestClient`.
- Cover new endpoints with success and failure tests using SQLite or SQLAlchemy fixtures instead of live MySQL, and note manual checks in PRs.

## Security Considerations
- Never commit real credentials; override `config.json` via environment variables outside local dev.
- Keep sensitive or bulky datasets in a gitignored `data/` directory.
- Before deployment, run `docker compose pull` then `docker compose up -d --build`, confirm Kafka topics exist, and review Flink SQL for unbounded joins or missing primary keys.

## Known Issues (investigating)
- The `connector_init` automation may exit early (curl error 7) if Kafka Connect is still booting. Re-run `docker compose run --rm connector_init` or register the connector manually once `connect` is healthy; root cause triage is in progress.

## Commit & Pull Request Guidelines
- Write imperative, ≤72-character commit subjects such as `Add hourly dashboard endpoint`, with optional body context for reviewers.
- Scope commits to a single concern (API, streaming, infra) and mention impacted services.
- Pull requests must outline functional changes, deployment/migration steps, verification evidence, and link related issues when available.
