#!/usr/bin/env bash
set -euo pipefail

JOB_JAR="/opt/flink/usrlib/lost-persons-job.jar"
LOG_FILE="/opt/flink/log/flink-job.log"

# Start the default entrypoint (JobManager) in the background
/docker-entrypoint.sh jobmanager &
JM_PID=$!

# Wait for the REST endpoint to become available (max ~2.5 min)
attempt=0
until wget -qO- http://localhost:8081/overview >/dev/null 2>&1 || [ $attempt -ge 30 ]; do
  attempt=$((attempt + 1))
  sleep 5
done

if wget -qO- http://localhost:8081/overview >/dev/null 2>&1; then
  echo "Ensuring Kafka topic exists before submitting Flink job..."
  if python3 - <<'PY'
import sys
import time
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, NoBrokersAvailable

TOPIC_NAME = "lost_persons_server.lost_persons_db.persons_lost"
MAX_ATTEMPTS = 30
SLEEP_SECONDS = 5

for attempt in range(1, MAX_ATTEMPTS + 1):
    try:
        admin = KafkaAdminClient(bootstrap_servers="kafka:9092", client_id="flink-bootstrap")
        topic = NewTopic(name=TOPIC_NAME, num_partitions=1, replication_factor=1)
        try:
            admin.create_topics([topic])
            print(f"Kafka topic '{TOPIC_NAME}' created.")
        except TopicAlreadyExistsError:
            print(f"Kafka topic '{TOPIC_NAME}' already exists.")
        finally:
            admin.close()
        break
    except NoBrokersAvailable:
        if attempt == MAX_ATTEMPTS:
            print("ERROR: Unable to reach Kafka brokers after multiple attempts.", file=sys.stderr)
            sys.exit(1)
        time.sleep(SLEEP_SECONDS)
PY
  then
    sleep 5
    if [ -f "${JOB_JAR}" ]; then
      echo "Submitting Flink job jar ${JOB_JAR}" | tee -a "${LOG_FILE}"
      /opt/flink/bin/flink run -d "${JOB_JAR}" >> "${LOG_FILE}" 2>&1 || {
        echo "Flink job submission failed, check ${LOG_FILE}" >&2
      }
    else
      echo "Warning: Job jar ${JOB_JAR} not found, skipping submission" >&2
    fi
  else
    echo "Warning: Kafka was unavailable; skipping Flink job submission" >&2
  fi
else
  echo "Warning: JobManager REST endpoint not ready, skipping Flink job submission" >&2
fi

wait "${JM_PID}"
