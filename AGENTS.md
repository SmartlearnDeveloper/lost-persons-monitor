# Lineamientos del Repositorio

## Panorama general
- Lost Persons Monitor es un pipeline CDC: el `producer` registra reportes en MySQL, Debezium los replica hacia Kafka, Flink calcula agregados y el `dashboard` muestra indicadores y reportes PDF en tiempo real.
- Desde la `versión_2_0_0` todo corre en Docker Compose (`mysql`, `zookeeper`, `kafka`, `connect`, `flink_jobmanager`, `flink_taskmanager`, `producer_service`, `case_manager_service`, `dashboard_service`, `connector_init`).
- Cada reporte crea un caso automáticamente, registra responsables y acciones, y actualiza los KPIs mediante WebSockets.

## Estructura
- `producer/`: API FastAPI que persiste personas y casos.
- `case_manager/`: CRUD de casos, acciones, historial de responsables y KPIs.
- `dashboard/`: UI (formularios, dashboard, reportes PDF) y endpoints `/stats/*`.
- `flink/` y `flink-job/`: job SQL/Java que consume Kafka y escribe `agg_*`.
- `scripts/`: `db_init.py`, `reset_db.sh`, `stack_check.py` y utilidades varias.
- `config/`: plantillas de configuración (`config.json`, `debezium-connector.json`, prioridades, etc.).

## Comandos básicos
1. `docker compose build producer` (tras cambiar `scripts/db_init.py`).
2. `./scripts/reset_db.sh` → reinicia MySQL, crea tablas y muestra `SHOW TABLES` al final.
3. `mvn -f flink-job/pom.xml clean package` → recompila el job.
4. `docker compose up -d --build` → levanta toda la pila.
5. `docker compose run --rm connector_init` → re-registra Debezium si falló.
6. Verificaciones rápidas:
   - `docker compose exec jobmanager /opt/flink/bin/flink list`
   - `docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status`

## Buenas prácticas
- Sigue PEP 8, usa tipados y evita duplicar configuración; importa modelos desde `scripts/db_init.py`.
- Documenta cambios visuales con capturas y pasos de prueba manual en cada PR.
- Los tests deben cubrir flujos felices y de error (usa SQLite/mocks para no depender de MySQL real).
- Antes de desplegar, confirma que las tablas nuevas existen (`case_responsible_history`, `responsible_contacts`, `case_actions.responsible_name`) ejecutando `reset_db.sh` o `SHOW TABLES`.

## Flujo de contribución
- Commits en imperativo (≤72 caracteres). Ejemplo: `feat: asignar responsables a casos`.
- Los PR deben describir impacto funcional, pasos de despliegue/migración y evidencia (logs, PDFs, capturas).
- Sincroniza cambios multiplataforma: si tocas Flink o Debezium, especifica los comandos necesarios (`docker compose build …`).
