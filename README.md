# Lost Persons Monitor

Lost Persons Monitor es una plataforma CDC que recibe reportes de personas perdidas, los replica mediante Debezium/Kafka, genera agregados con Flink y expone dashboards y reportes PDF para equipos de respuesta. Cada reporte crea un caso, registra responsables y acciones y actualiza indicadores en tiempo real.

## Guía rápida

1. **Requisitos**: Python 3.11+, Docker y Docker Compose.
2. **Reconstruir producer** (si cambió `scripts/db_init.py`):
   ```bash
   docker compose build producer
   ```
3. **Reiniciar la base** (opcional, recomendado antes de demos):
   ```bash
   ./scripts/reset_db.sh
   ```
   Este script levanta MySQL, elimina y crea `lost_persons_db`, y al final ejecuta `SHOW TABLES FROM lost_persons_db` para confirmar que existen `case_responsible_history`, `responsible_contacts`, etc.
4. **Compilar Flink**:
   ```bash
   mvn -f flink-job/pom.xml clean package
   ```
5. **Levantar la pila completa**:
   ```bash
   docker compose up -d --build
   ```
6. **Verificar Debezium** (si `connector_init` falló con `curl: (7)`):
   ```bash
   docker compose run --rm connector_init
   ```
7. **Comprobar servicios**:
   ```bash
   docker compose exec jobmanager /opt/flink/bin/flink list
   docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status
   ```
8. **Modo local opcional**: levanta un servicio puntual con `uvicorn` y registra el conector manualmente (`curl localhost:40125/connectors/`).

## URLs principales

| Servicio / UI                      | URL                                        |
|------------------------------------|---------------------------------------------|
| Reporte de personas perdidas       | `http://localhost:40145/report`             |
| Dashboard en tiempo real           | `http://localhost:40145/dashboard`          |
| Gestión de casos + PDF             | `http://localhost:40145/cases`              |
| Catálogo de reportes PDF           | `http://localhost:40145/reports`            |
| API del producer                   | `http://localhost:40140/docs`               |
| API del case manager               | `http://localhost:40150/docs`               |
| Kafka Connect                      | `http://localhost:40125/connectors/`        |

## Flujo de datos

1. El `producer` valida el payload, calcula edad y marca `lost_timestamp` usando `REPORT_LOCAL_TZ` (por defecto `America/Guayaquil`).
2. Debezium (configurado con `poll.interval.ms=500` y `max.batch.size=256`) lee los binlogs y publica en `lost_persons_server.*`.
3. Flink (`FLINK_LOCAL_TIMEZONE`) agrupa por edad, género y hora y guarda los resultados en MySQL (`agg_age_group`, `agg_gender`, `agg_hourly`).
4. El case manager expone `/case-stats/*`, `/cases/{id}/actions`, `/cases/{id}/responsibles` y notifica al dashboard vía `/internal/refresh` después de cualquier cambio.
5. El dashboard consume los agregados (SQL o WebSocket) y actualiza tarjetas, gráficas, historial de acciones y responsables en tiempo real; los reportes PDF incluyen ambos historiales.

## Variables de entorno clave

- `REPORT_LOCAL_TZ`: zona horaria usada por el producer.
- `FLINK_LOCAL_TIMEZONE`: zona horaria para las funciones de fecha/hora en Flink.
- `CASE_MANAGER_URL` / `CASE_MANAGER_PUBLIC_URL`: endpoints interno y expuesto para el dashboard.
- `DASHBOARD_REFRESH_URL`: ruta interna (`http://dashboard:58102/internal/refresh`) que el case manager invoca tras cada cambio.

## Validación tras despliegue

1. `docker compose ps` → todos los contenedores deben estar “Up”.
2. `SHOW TABLES FROM lost_persons_db` → verifica que existan `case_responsible_history`, `responsible_contacts` y `case_actions` con `responsible_name`.
3. Envía un reporte desde `/report`, asigna un responsable en `/cases`, registra una acción y descarga el PDF para confirmar que Prioridad (Alta/Media/Baja) y el responsable aparecen en español.
4. Observa `/dashboard`: los KPIs y gráficas deberían reaccionar sin recargar.

## Estructura del repo

- `producer/`: API de entrada, crea personas y casos.
- `case_manager/`: control de casos, acciones, responsables y KPIs.
- `dashboard/`: Jinja + API para dashboard, formularios y reportes PDF.
- `flink/`, `flink-job/`: job de streaming (SQL/Java) que alimenta las tablas agregadas.
- `scripts/`: herramientas (`db_init.py`, `reset_db.sh`, `stack_check.py`).
- `config/`: plantillas (`config.json`, `debezium-connector.json`, prioridades, etc.).

## Pruebas

- Usa `pytest` con `fastapi.TestClient` en los servicios FastAPI (productor, dashboard, case_manager).
- Mockea la base con SQLite o Sessions en memoria para evitar dependencias externas.
- Incluye pasos manuales (por ejemplo, generar un PDF y comprobar encabezados) en la descripción de cada PR.

## Problemas frecuentes

- **Conector Debezium no registrado**: reejecuta `docker compose run --rm connector_init` y valida con `curl http://localhost:40125/connectors/`.
- **Error “Unknown column…”**: reconstruye la imagen del producer (`docker compose build producer`) y corre `./scripts/reset_db.sh` para crear las columnas/ tablas nuevas.
- **Dashboard muestra “NetworkError”**: revisa `docker compose logs dashboard case_manager`; usualmente indica que falta una migración de base o que el case manager no puede alcanzar MySQL.
- **Gráficas no se actualizan**: confirma que el job de Flink está “RUNNING” y que el conector Debezium sigue en `state: RUNNING`.

Consulta los `AGENTS.md` de cada subdirectorio para lineamientos específicos (por ejemplo, cómo ejecutar pruebas del dashboard o empaquetar el job de Flink).
