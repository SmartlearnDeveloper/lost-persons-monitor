#!/usr/bin/env bash
set -euo pipefail

echo "Asegurando que MySQL esté disponible..."
docker compose up -d mysql >/dev/null
docker compose exec mysql bash -c "until mysqladmin ping -h localhost -uroot -prootpassword --silent; do sleep 2; done" >/dev/null

echo "Eliminando y recreando el esquema, luego aplicando migraciones..."
docker compose run --rm -e RESET_DB=1 producer python scripts/db_init.py

echo "Base de datos reiniciada; ejecuta 'docker compose up -d' para el resto del stack."
