# Repository Guidelines

## Project Overview
- The producer service exposes a FastAPI interface for reporting missing persons, validates payloads with Pydantic, computes derived fields such as age, and persists records into MySQL via SQLAlchemy.
- It is the authoritative write path in the CDC pipeline: Debezium captures its inserts, Kafka and Flink propagate aggregates, and downstream systems assume the producer enforces data quality.

## Build & Test Commands
- Activate a Python environment (`source .venv/bin/activate` is recommended; the repository also ships with `producer/venv`, which can be reused via `source producer/venv/bin/activate` if compatibility is required).
- `pip install -r producer/requirements.txt` inside an activated environment installs service dependencies.
- `python scripts/db_init.py` must run before local testing to ensure ORM tables exist.
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101` launches the API; exercise endpoints through `/docs`, HTTPie (`http :58101/report_person/ ...`), or `curl`.
- Use `docker compose restart producer` when deploying containerized updates after rebuilding images.

## Code Style Guidelines
- Follow PEP 8 with four-space indentation and snake_case function names; group imports via `isort` when touching multiple modules.
- Prefer router modules included through a factory (e.g., `create_app()`) rather than expanding global state in `main.py`.
- Keep Pydantic models in `models.py`, reuse SQLAlchemy models from `scripts/db_init.py`, and centralize configuration access through `database.py`.
- Add docstrings for complex business rules (e.g., age calculations) and lean on type hints across public APIs.

## Testing Instructions
- Place automated tests under `tests/producer/` using `pytest` and `fastapi.TestClient`; name files `test_<feature>.py`.
- Stub the database with SQLite or scoped SQLAlchemy sessions to avoid relying on MySQL; seed fixtures with representative payloads.
- Cover success, validation error, and persistence failure scenarios; capture manual verification steps (sample requests/responses) in PR descriptions.

## Security Considerations
- Never hardcode credentials or secrets; read connection details from `config.json` locally and environment variables in deployed environments.
- Validate and sanitize optional text fields (`details`, `lost_location`) to mitigate injection risks; log only non-sensitive payload fragments.
- Rotate demo datasets regularly and store larger fixtures in a gitignored `data/` directory.

## Additional Contribution Guidelines
- Use imperative commit subjects under 72 characters (e.g., `Add report payload schema validation`) and group logical changes together.
- Pull requests should list new dependencies, schema impacts, verification evidence, and any required rollout steps.
