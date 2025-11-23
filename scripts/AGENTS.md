# Lineamientos de Scripts

## Descripción
- `scripts/db_init.py` define todas las tablas (personas, casos, acciones, historial de responsables, contactos) y las crea/seed.
- `scripts/reset_db.sh` levanta MySQL, recrea la base y muestra `SHOW TABLES` al terminar.
- `scripts/stack_check.py` valida que producer, case manager, dashboard y Kafka Connect estén accesibles.

## Uso
- `python scripts/db_init.py --reset` (en entornos fuera de Docker).
- `./scripts/reset_db.sh` (usa el contenedor del producer para ejecutar `db_init.py`).
- `python scripts/stack_check.py` después de `docker compose up -d --build` para verificar servicios.

## Recomendaciones
- Cada cambio a `db_init.py` requiere `docker compose build producer`.
- Los scripts deben tener mensajes claros y, cuando destruyan datos, exigir confirmación o bandera explícita.
