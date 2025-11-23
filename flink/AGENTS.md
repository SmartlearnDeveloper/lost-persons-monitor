# Flink Guidelines

## Overview
- Define el job que consume Kafka (Debezium) y escribe agregados en MySQL (`agg_age_group`, `agg_gender`, `agg_hourly`).
- Controla timezone vía `FLINK_LOCAL_TIMEZONE` para que `HOUR()` alimente correctamente al dashboard.

## Build & Deploy
- `mvn -f flink-job/pom.xml clean package`
- `docker compose build jobmanager taskmanager`
- `docker compose up -d jobmanager taskmanager`
- Verifica: `docker compose exec jobmanager /opt/flink/bin/flink list`

## Notes
- JAR en `/opt/flink/usrlib/lost-persons-job.jar` (copiado desde `flink-job/target`).
- Usa `scripts/run_flink_job.sh` para reinyectar el job manualmente.
- Mantén connectors/ JARs en `flink/jars/` actualizados y documenta versiones en PRs.
