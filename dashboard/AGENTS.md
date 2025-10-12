# Repository Guidelines

## Project Overview
- The dashboard service is a FastAPI application that serves JSON endpoints and Jinja-rendered pages summarizing aggregated lost-person statistics (age group, gender, hourly trends).
- It reads from MySQL tables populated by Flink, transforming the aggregates into Chart.js-friendly datasets so response teams can monitor the situation in real time.

## Build & Test Commands
- Activate a Python environment (`source .venv/bin/activate` is recommended; an archived environment exists at `dashboard/venv` and can be reused with `source dashboard/venv/bin/activate` if necessary).
- `pip install -r dashboard/requirements.txt` inside the active environment installs the UI service dependencies.
- `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102` starts the API; open `/` in a browser for the dashboard or query `/stats/<metric>` via `curl` for JSON.
- Run `python scripts/db_init.py` and the Flink job before smoke-testing the dashboard so the aggregated tables exist.
- Rebuild and restart the containerized service with `docker compose build dashboard && docker compose restart dashboard` during deployments.

## Code Style Guidelines
- Follow PEP 8 for Python modules and two-space indentation for Jinja templates; keep HTML IDs/classes semantic.
- Hold route logic in lightweight functions that delegate SQL to helper utilities; avoid embedding ad hoc queries in templates.
- Extend `models.py` when new response schemas are required and keep client-side Chart.js code resilient to empty datasets.

## Testing Instructions
- Add tests under `tests/dashboard/` named `test_<feature>.py`, using `pytest` with `fastapi.TestClient`.
- Mock database sessions with SQLAlchemy fixtures or stubs so tests do not depend on MySQL; assert both JSON shape and content.
- Document manual validation (browser screenshots, network inspector output) in PRs when UI changes occur.

## Security Considerations
- Do not embed secrets or API keys in templates; rely on environment variables or configuration files that stay outside version control.
- Validate query parameters before passing them to SQLAlchemy to avoid injection risks and ensure statistics endpoints remain read-only.
- Minimize logging of personally identifiable information and scrub any example payloads before sharing.

## Additional Contribution Guidelines
- Keep commit messages imperative and specific (e.g., `Update hourly chart colors`) and include both backend and template changes when tightly coupled.
- Pull requests must capture screenshots of UI changes, list manual test steps, and call out any new dependencies or configuration switches.
