# Repository Guidelines

## Project Overview
- Lost Persons Monitor es un pipeline CDC completo: el `producer` registra reportes de personas perdidas en MySQL, Debezium transmite los cambios a Kafka, Flink genera agregados en tiempo (casi) real y el `dashboard` expone métricas, dashboards y reportes PDF (incluyendo historial de responsables y acciones).
- Desde `version_2_0_0`, toda la plataforma corre dentro de Docker Compose (`mysql`, `zookeeper`, `kafka`, `connect`, `flink_jobmanager`, `flink_taskmanager`, `producer_service`, `dashboard_service`, `case_manager_service`, `connector_init`).
- Los casos se crean automáticamente con cada reporte y ahora incluyen seguimiento de responsables (`case_responsible_history`) y contactos disponibles (`responsible_contacts`).

## Estructura del Repositorio
- `producer/`: FastAPI para recepción de reportes; crea personas, casos y dispara responsables/prioridades base.
- `case_manager/`: API de casos, acciones, historial de responsables, KPIs y endpoints para PDF.
- `dashboard/`: UI (Forms, Dashboard, Cases, Reports), WebSocket listener y generador de reportes PDF.
- `flink/`, `flink-job/`: job SQL/Java que consume Kafka y escribe agregados `agg_*` en MySQL.
- `scripts/`: `db_init.py`, `reset_db.sh`, `stack_check.py` y utilidades extras.
- `config/`: plantillas (`config.json`, `debezium-connector.json`, prioridades, etc.).

## Comandos Clave
1. `docker compose build producer` (cuando cambie `db_init.py`).
2. `./scripts/reset_db.sh` – reinicia esquema, crea tablas nuevas y muestra `SHOW TABLES` al final.
3. `mvn -f flink-job/pom.xml clean package` – recompila el job.
4. `docker compose up -d --build` – levanta toda la pila.
5. `docker compose run --rm connector_init` – re-registra Debezium si hiciera falta.
6. Verificaciones:
   - `docker compose exec jobmanager /opt/flink/bin/flink list`
   - `docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status`

## Estándares de Código y Tests
- PEP 8 para Python, SQL/HTML bien formateado y modular.
- Tests por servicio (`tests/producer`, `tests/dashboard`, etc.) usando `pytest` + `fastapi.TestClient`. Mockear MySQL vía SQLite/fixtures.
- Documentar validaciones manuales (trazas WebSocket, screenshots, PDFs) en PRs.

## Seguridad y Operación
- Variables sensibles fuera del repo (`config.json` sólo para local). `REPORT_LOCAL_TZ`, `FLINK_LOCAL_TIMEZONE`, `CASE_MANAGER_URL/PUBLIC_URL`, `DASHBOARD_REFRESH_URL` controlan comportamientos clave.
- `reset_db.sh` y `stack_check.py` ayudan a mantener la integridad antes de demos.
- Revisa logs (`docker compose logs <service>`) ante cualquier “NetworkError” e identifica si falta migrar tablas (`case_actions.responsible_name`, `case_responsible_history`, etc.).

## Workflow de Contribución
- Commits imperativos ≤72 caracteres (ej. `feat: assign and track case responsibles`).
- PRs deben incluir cambios funcionales, pasos de despliegue/migración, evidencia (logs, screenshots, PDFs) y dependencias nuevas.
- Coordina reinicios de la pila cuando se toque Flink o la base; la documentación en cada `AGENTS.md` de subcarpeta resume detalles específicos de cada servicio.
