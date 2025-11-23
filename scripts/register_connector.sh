#!/bin/sh
set -eu

CONNECT_URL="http://connect:8083"
CONNECTOR_NAME="lost-persons-connector"
CONFIG_PATH="/config/debezium-connector.json"

echo "Esperando a Kafka Connect (${CONNECT_URL}) para registrar el conector..."
STATUS="000"
while true; do
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${CONNECT_URL}/connectors/" || true)
    if [ "$STATUS" = "200" ]; then
        break
    fi
    sleep 5
done

echo "Kafka Connect listo, registrando ${CONNECTOR_NAME}..."
curl -s -X DELETE "${CONNECT_URL}/connectors/${CONNECTOR_NAME}" >/dev/null 2>&1 || true

REGISTER=$(curl -s -o /tmp/register.log -w '%{http_code}' -X POST \
    -H "Accept:application/json" \
    -H "Content-Type:application/json" \
    "${CONNECT_URL}/connectors/" \
    -d @"${CONFIG_PATH}" || true)

cat /tmp/register.log
echo

if [ "$REGISTER" != "200" ] && [ "$REGISTER" != "201" ]; then
    echo "Error registrando conector (HTTP ${REGISTER})." >&2
    exit 1
fi

echo "Conector Debezium registrado (HTTP ${REGISTER})."
