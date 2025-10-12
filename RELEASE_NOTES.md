# version_1_0_0

## Highlights

- Adds a landing page with clear navigation between the reporting form and the analytics dashboard.
- Introduces a browser-based generator (`/report`) that pre-populates random sample data and posts it to the producer API.
- Enables CORS on the producer so the dashboard UI can create reports directly from the client.
- Provides a `GET /report_person/` endpoint to list recent reports for verification.
- Enhances the dashboard charts with tabular summaries, error handling, and fallback SQL queries when Flink aggregates are empty.

## Verification Checklist

- `docker-compose up -d`
- `python scripts/db_init.py`
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`
- `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`
- Register Debezium connector with `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json`
- Visit `http://localhost:58102/`, open the form, generate + send several sample reports, and confirm the dashboard aggregates update in real time.
