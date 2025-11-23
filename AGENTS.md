# Lineamientos del Repositorio

## Panorama general
- Lost Persons Monitor es un pipeline CDC: el `producer` registra reportes en MySQL, Debezium los replica hacia Kafka, Flink calcula agregados y el `dashboard` muestra indicadores y reportes PDF en tiempo real.
- Desde la `versión_2_1_0` todo corre en Docker Compose (`mysql`, `zookeeper`, `kafka`, `connect`, `flink_jobmanager`, `flink_taskmanager`, `producer_service`, `case_manager_service`, `dashboard_service`, `auth_service`, `connector_init`).
- Cada reporte crea un caso automáticamente, registra responsables y acciones, y actualiza los KPIs mediante WebSockets.

## Estructura
- `producer/`: API FastAPI que persiste personas y casos.
- `case_manager/`: CRUD de casos, acciones, historial de responsables y KPIs.
- `dashboard/`: UI (formularios, dashboard, reportes PDF y módulo de administración). Aloja `/admin/users`, la tabla interactiva con íconos, el botón *Listado de usuarios* (PDF sin contraseñas) y los endpoints `/stats/*`.
- `auth_service/`: FastAPI con JWT, roles (`reporter`, `analyst`, `coordinator`, `admin`) y endpoints `/auth/*`.
- `common/`: utilitarios compartidos como `common/security.py`.
- `flink/` y `flink-job/`: job SQL/Java que consume Kafka y escribe `agg_*`.
- `scripts/`: `db_init.py`, `reset_db.sh`, `stack_check.py` y utilidades varias.
- `config/`: plantillas de configuración (`config.json`, `debezium-connector.json`, prioridades, etc.).

## Comandos básicos
1. `docker compose build producer` (tras cambiar `scripts/db_init.py` o `common/`).
2. `./scripts/reset_db.sh` → reinicia MySQL, crea tablas y muestra `SHOW TABLES` al final (verifica que existan `auth_users`, `auth_roles`, etc.).
3. `mvn -f flink-job/pom.xml clean package` → recompila el job.
4. `docker compose up -d --build` → levanta toda la pila.
5. `docker compose run --rm connector_init` → re-registra Debezium si falló.
6. Verificaciones rápidas:
   - `docker compose exec jobmanager /opt/flink/bin/flink list`
   - `docker compose exec connect curl -s http://localhost:8083/connectors/lost-persons-connector/status`
   - `docker compose exec dashboard env | grep REPORT_LOCAL_TZ` (confirma el huso configurado para los PDF y timestamps).

## Buenas prácticas
- Sigue PEP 8, usa tipados y evita duplicar configuración; importa modelos desde `scripts/db_init.py`.
- Documenta cambios visuales con capturas y pasos de prueba manual en cada PR.
- Los tests deben cubrir flujos felices y de error (usa SQLite/mocks para no depender de MySQL real).
- Antes de desplegar, confirma que las tablas nuevas existen (`case_responsible_history`, `responsible_contacts`, `case_actions.responsible_name`, `auth_*`) ejecutando `reset_db.sh` o `SHOW TABLES`.
- Cada vez que edites `common/` vuelve a construir producer, dashboard, case_manager y auth_service para que compartan la misma lógica de seguridad.
- Ajusta `REPORT_LOCAL_TZ` cuando necesites reflejar la hora continental correcta (por defecto `America/Bogota`). El producer y el dashboard lo usan para sellar reportes, PDF y métricas.
- Mantén sincronizada la UX de `/admin/users`: los botones son íconos pequeños, el estado se cambia mediante un modal y la opción *Listado de usuarios* debe seguir generando PDF con header/footer y número de página.

## Autenticación
- `auth_service` se levanta con la pila de Docker (`docker compose up -d --build`) y expone `http://localhost:40155/auth/login`.
- `db_init.py` crea un usuario administrador (`admin / admin123`); cambia la contraseña inmediatamente usando `/auth/register` y `/auth/assign-role`.
- Todos los módulos UI (`/report`, `/dashboard`, `/cases`, `/reports`) requieren un JWT. El login lo guarda en una cookie (`lpm_token`) y en `localStorage` para que el navegador envíe `Authorization: Bearer …` en cada `fetch` y para que los formularios (PDF) se autentiquen automáticamente.
- `/register` habilita el autoservicio (rol `member`: `report`, `dashboard`, `pdf_reports`). `/admin/users` sólo aparece para `manage_users` y permite listar, consultar, editar, generar el PDF *Listado de usuarios* y alternar estados mediante un modal (sin eliminar cuentas).
- Para scripts o Postman: ejecuta `curl -XPOST http://localhost:40155/auth/login -d 'username=admin&password=admin123'` y reutiliza el `access_token` contra producer, dashboard o case manager.

## Flujo de contribución
- Commits en imperativo (≤72 caracteres). Ejemplo: `feat: asignar responsables a casos`.
- Los PR deben describir impacto funcional, pasos de despliegue/migración y evidencia (logs, PDFs, capturas).
- Sincroniza cambios multiplataforma: si tocas Flink o Debezium, especifica los comandos necesarios (`docker compose build …`).
