# Lineamientos de Flink

## Descripción
- Job SQL/Java (`flink-job/src/...`) que consume los tópicos Debezium (`lost_persons_server.*`), calcula agregados (edad, género, hora) y los escribe en MySQL (`agg_*`).
- Usa `FLINK_LOCAL_TIMEZONE` para que los cálculos horarios coincidan con la UI.

## Flujo de trabajo
1. `mvn -f flink-job/pom.xml clean package`
2. `docker compose build jobmanager taskmanager`
3. `docker compose up -d jobmanager taskmanager`
4. Verificar: `docker compose exec jobmanager /opt/flink/bin/flink list`

## Notas
- El `Dockerfile` copia `flink/start_jobmanager_with_sql.sh`, conecta a Kafka y ejecuta el jar automáticamente.
- Si debes redeployar manualmente, usa `scripts/run_flink_job.sh`.
- Documenta cambios en conectores JAR y versiones en cada PR.
