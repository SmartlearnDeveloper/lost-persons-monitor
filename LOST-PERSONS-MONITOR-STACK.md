# Lost Persons Monitor Stack

## 1. Project Explanation
- Lost Persons Monitor ingests missing-person reports through a FastAPI producer service, persists them in MySQL, streams change events with Debezium into Kafka, aggregates insights via Apache Flink, and exposes real-time dashboards through a FastAPI/Jinja frontend. The goal is to deliver low-latency situational awareness (age groups, gender distribution, hourly activity) for emergency-response teams.

## 2. Required Stack & Startup Commands
- Dependencies: Python 3.11+, Docker, Docker Compose, and network access between containers.
- Run the following commands in order to prepare and launch the full stack (each command is complete and should be executed from the repository root). The repository already includes legacy environments under `producer/venv` and `dashboard/venv`; you can activate one with `source producer/venv/bin/activate` or `source dashboard/venv/bin/activate`, but creating a fresh root `.venv` is recommended for consistency:
  1. `python scripts/db_init.py`
  2. `docker-compose up -d`
  3. `python -m venv .venv`
  4. `source .venv/bin/activate`
  5. `pip install -r producer/requirements.txt`
  6. `pip install -r dashboard/requirements.txt`
  7. `uvicorn producer.main:app --host 0.0.0.0 --port 58101`
  8. `uvicorn dashboard.main:app --host 0.0.0.0 --port 58102`
- Register the Debezium connector once services are healthy:  
  `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json`

## 3. Port Usage Overview
- Producer API: host `58101` (FastAPI ingestion service running on the host)
- Dashboard API/UI: host `58102` (FastAPI dashboard + Jinja templates running on the host)
- MySQL: host `33307` → container `3306` (primary database for producer and aggregates)
- Kafka Broker: host `19093` → container `9092` (CDC event stream)
- Zookeeper: host `32182` → container `2181` (Kafka coordination)
- Kafka Connect (Debezium): host `18084` → container `8083` (CDC connector management API)
- Flink JobManager: host `18082` → container `8081` (Flink control UI/RPC)
- Flink TaskManager: internal only (communicates within Docker network; no host port exposed)
