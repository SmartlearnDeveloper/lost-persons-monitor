# Repository Guidelines

## Project Overview
- The `scripts` package contains operational tooling for the platform, most notably `db_init.py`, which defines the canonical SQLAlchemy models and provisions the MySQL schema for producer and dashboard services.
- Utility scripts in this directory may seed aggregates, run maintenance tasks, or orchestrate data migrations that keep the CDC pipeline consistent.
- Starting with `version_2_0_0`, this folder also stores stack validation helpers (e.g., `stack_check.py`) aligned with the Dockerized microservice architecture.

## Build & Test Commands
- Execute `python scripts/db_init.py` to create or update schemas; the script retries MySQL connections and should succeed before starting other services.
- Run `python scripts/stack_check.py` after `docker compose up -d --build` to confirm FastAPI and Kafka Connect endpoints are reachable on host ports 40140–40150 / 40125.
- Add new utilities as executable modules (e.g., `python scripts/<tool>.py`) and document invocation options with `--help`.
- Where shell scripting is required, prefer Python wrappers to stay cross-platform and log actions for later auditing.

## Code Style Guidelines
- Follow PEP 8 and keep functions under roughly 40 lines; extract helpers for repeated DDL or seeding logic.
- Reuse the SQLAlchemy `Base` defined in `db_init.py` and export shared models via `__all__` to make imports intention-revealing.
- Avoid hardcoding credentials; read configuration from `config.json` or environment variables and allow overrides via CLI arguments.

## Testing Instructions
- Add unit tests for script helpers under `tests/scripts/`, mocking database engines to avoid destructive operations.
- Provide smoke-test instructions in the script docstring (e.g., expected console output) and include dry-run modes when practical.
- For migration utilities, create reversible fixtures and ensure tests leave the database in its original state.

## Security Considerations
- Guard destructive actions (drop, truncate) behind explicit CLI flags and confirmation prompts; default to read-only dry runs.
- Sanitize logged data, especially when scripts touch personally identifiable information; write sensitive logs to protected locations.
- Keep large seed datasets out of version control by storing them in a gitignored `data/` directory and documenting retrieval steps elsewhere.

## Additional Contribution Guidelines
- Use imperative commit subjects (e.g., `Add hourly aggregate seed script`) and describe migration impacts in the body.
- Pull requests must include rollback instructions, sample outputs, and coordination notes for affected services (producer, Flink, dashboard).

## Known Issues
- `stack_check.py` will flag failures if the Debezium connector was not auto-registered (current investigations show `connector_init` may exit early with curl error 7). Re-run the helper container manually before opening bug reports.
