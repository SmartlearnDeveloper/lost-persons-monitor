#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-rootpassword}"
MAX_ATTEMPTS=40
SLEEP_SECONDS=3

echo "Asegurando que MySQL esté disponible..."
docker compose up -d mysql >/dev/null

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if docker compose exec -T mysql env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h localhost -uroot --silent >/dev/null 2>&1; then
    echo "MySQL respondió al intento #$attempt."
    break
  fi
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    echo "MySQL no respondió después de $MAX_ATTEMPTS intentos. Revisa 'docker compose logs mysql'." >&2
    exit 1
  fi
  echo "Esperando a MySQL... (intento $attempt/$MAX_ATTEMPTS)"
  sleep "$SLEEP_SECONDS"
done

echo "Eliminando y recreando el esquema, luego aplicando migraciones..."
docker compose run --rm --no-deps -e RESET_DB=1 producer python scripts/db_init.py

echo "Base de datos reiniciada; ejecuta 'docker compose up -d' para el resto del stack."
