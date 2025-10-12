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
5. Start the infrastructure with `docker-compose up -d`.
6. Launch APIs locally with `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101` and `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`.
7. Once the stack is healthy, register the Debezium connector:  
   `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json`.

## Web Application

- `http://localhost:58102/` — landing page with links to the reporter form and analytics dashboard.
- `http://localhost:58102/report` — simple GUI to generate random missing-person entries and post them to the producer API.
- `http://localhost:58102/dashboard` — real-time charts plus tabular summaries driven by Debezium/Flink aggregates, with direct SQL fallbacks when aggregates are empty.

The reporter UI issues `POST` requests to `http://localhost:58101/report_person/` (the producer service). A “Generar aleatorio” button pre-fills sample data so dispatch teams can simulate activity rapidly.

## Producer API

- `POST /report_person/` — accepts the JSON payload produced by the reporter GUI (see `producer/models.py`).
- `GET /report_person/?limit=10` — returns the most recent reports for manual verification.
- `GET /` — health message describing available endpoints.

## Documentation Index

- Start with the nearest `AGENTS.md` file in any directory to see contributor guidance tailored to that service or package. The root `AGENTS.md` outlines project-wide practices, while subdirectories (e.g., `producer/AGENTS.md`, `dashboard/AGENTS.md`) provide focused instructions.
- Infrastructure diagrams, historical conversations, and additional context remain in `lost-persons-monitor.md`.

Refer to service-specific `AGENTS.md` files for detailed testing, deployment, and security practices.

## Versioning & Releases

- Current release: `version_1_0_0` (see `VERSION`).
- Release notes live in `RELEASE_NOTES.md` and are updated alongside tags.
