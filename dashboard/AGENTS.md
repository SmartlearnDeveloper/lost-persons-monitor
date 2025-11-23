# Dashboard Guidelines

## Overview
- FastAPI app sirviendo HTML (Jinja) + API JSON.
- Secciones principales: `/report`, `/dashboard`, `/cases`, `/reports`, `/case-responsibles/catalog`, `/case-stats/*`.
- `http://localhost:40145` cuando corre en Docker Compose.

## Build & Run
- `python -m venv .venv && source .venv/bin/activate`
- `pip install -r dashboard/requirements.txt`
- `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`
- En contenedor: `docker compose up -d dashboard`

## UI Features
- Dashboard muestra KPIs + gráficas Chart.js con WebSockets.
- `/cases` permite editar casos, asignar responsables (modal) y registrar acciones.
- PDF de casos incluye “Historial de responsables” y “Historial de acciones” (con responsable capturado en el momento).

## Dev Notes
- Mantén `case_manager_url`, `CASE_MANAGER_PUBLIC_URL` en `docker-compose.yml`.
- Cuando edites templates (Jinja), recuerda reconstruir el contenedor o usar `uvicorn --reload`.
- Tests en `tests/dashboard/` (FastAPI `TestClient`).
- Documenta cambios visuales con screenshots en PRs.
