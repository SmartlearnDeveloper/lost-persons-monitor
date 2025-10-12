# Repository Guidelines

## Project Overview
- The Flink module defines the streaming topology that consumes Debezium change events from Kafka, aggregates lost-person signals, and writes results into MySQL tables consumed by the dashboard.
- `flink_sql_job.sql` captures the production job: source definitions, sink tables, and insert statements that compute age groups, gender splits, and hourly counts in near real time.

## Build & Test Commands
- Build custom images with `docker compose build jobmanager taskmanager` to package updated SQL or connector JARs.
- Validate SQL locally using `./bin/sql-client.sh -f /opt/flink/usrlib/flink_sql_job.sql` inside the JobManager container or open an interactive SQL client session for iterative testing.
- Keep Debezium and Kafka settings aligned by updating `docker-compose.yml` and `debezium-connector.json` whenever connector properties change.

## Code Style Guidelines
- Organize SQL into logical blocks (sources → sinks → inserts) and annotate non-obvious transformations with concise comments.
- Pin connector versions in `Dockerfile` and `jars/`, documenting upgrades in commit messages and PR descriptions.
- Avoid inline secrets; parameterize credentials via environment variables passed from Docker Compose.

## Testing Instructions
- Replay fixture events by posting sample reports through the producer API, then query `agg_*` tables to confirm expected results.
- For isolated checks, craft Kafka messages with the expected Debezium envelope and submit them via `kafka-console-producer` before running targeted SQL inserts in the client.
- Record observed metrics (e.g., row counts, sample results) in PRs to demonstrate correctness.

## Security Considerations
- Ensure sink tables declare primary keys to prevent uncontrolled growth and to support idempotent updates.
- Rotate connector credentials outside version control and restrict Kafka topics to least-privilege ACLs.
- Monitor job logs for backpressure or checkpoint failures; adjust parallelism cautiously to avoid overwhelming MySQL.

## Additional Contribution Guidelines
- Prefix commits with the streaming scope when helpful (e.g., `flink: Add hourly retention aggregate`) and bundle related SQL/Docker changes together.
- Pull requests must describe state compatibility expectations, checkpoint impacts, and required deploy steps (drain job, build images, redeploy).
