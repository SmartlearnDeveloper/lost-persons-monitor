# Repository Guidelines

## Project Overview
- Lost Persons Monitor is a CDC pipeline: the `producer` writes reports to MySQL, Debezium streams binlog events into Kafka, Flink aggregates them, and the `dashboard` renders live intelligence.
- Docker Compose keeps services decoupled while delivering low-latency snapshots (age, gender, hourly distributions) for responders.

## Project Structure & Module Organization
- `producer/` is the sole write surface into MySQL; expanding ingestion flows happens here.
- `dashboard/` consumes the aggregated tables created by Flink to render HTML and JSON endpoints.
- `scripts/db_init.py` defines SQLAlchemy ORM tables and provisions schema; run it after schema edits.
- `flink/` stores `flink_sql_job.sql` and connector JARs that mount into the JobManager/TaskManager images.
- `config.json` centralizes local credentials and ports, while `debezium-connector.json` registers the Kafka Connect connector.

## Build & Test Commands
- Prepare a Python env (recommended: `python -m venv .venv && source .venv/bin/activate`; legacy environments remain under `producer/venv` and `dashboard/venv` and can be reactivated with `source producer/venv/bin/activate` or `source dashboard/venv/bin/activate` if needed).
- `pip install -r producer/requirements.txt` or `pip install -r dashboard/requirements.txt` inside the active env to install service deps.
- `python scripts/db_init.py` prepares the schema; rerun after ORM edits.
- `docker-compose up -d` launches MySQL, Kafka, Kafka Connect, and Flink; `docker-compose down` stops the stack.
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101` and `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102` run APIs locally; register CDC via `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json` once services are healthy.

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
- Before deployment, run `docker-compose pull` then `docker-compose up -d --build`, confirm Kafka topics exist, and review Flink SQL for unbounded joins or missing primary keys.

## Commit & Pull Request Guidelines
- Write imperative, ≤72-character commit subjects such as `Add hourly dashboard endpoint`, with optional body context for reviewers.
- Scope commits to a single concern (API, streaming, infra) and mention impacted services.
- Pull requests must outline functional changes, deployment/migration steps, verification evidence, and link related issues when available.
