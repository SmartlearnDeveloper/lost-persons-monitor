# Scripts Guidelines

## Overview
- `scripts/db_init.py`: define/crea tablas (`case_responsible_history`, `responsible_contacts`, `case_actions.responsible_name`, etc.).
- `scripts/reset_db.sh`: arranca MySQL, recrea el esquema y muestra `SHOW TABLES` para confirmar migraciones.
- `scripts/stack_check.py`: sanidad de servicios (Producer, Dashboard, Case Manager, Kafka Connect).

## Usage
- `python scripts/db_init.py --reset` (cuando corras fuera de contenedores).
- `./scripts/reset_db.sh` (usado normalmente dentro de la pila Docker): ejecuta `db_init.py` en el contenedor del producer.
- Añade nuevos scripts en Python siempre que sea posible para mantener compatibilidad cross-platform.

## Notes
- Cada cambio en `db_init.py` implica reconstruir la imagen del producer: `docker compose build producer`.
- Documenta cualquier operación destructiva con banderas `--force`/`--dry-run`.
