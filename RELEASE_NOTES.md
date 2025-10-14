# version_1_1_0

## Highlights

- Introduces the `case_manager` FastAPI service with full CRUD, action timelines, and KPI endpoints used by the dashboard.
- Adds a web Case Management UI at `/cases` to create/update cases, log actions via configurable selectors, and prevent duplicate assignments.
- Expands dashboard KPIs (new/in-progress/resolved/cancelled/archived, average response time) and totals in demographic/hourly tables.
- Publishes configurable catalogs: priorities (`config/case_priorities.json`) and action types (`config/case_action_types.json`).
- Applies consistent branding across dashboards and reports, and captures the new schema in `scripts/db_init.py`.

## Verification Checklist

- `python scripts/db_init.py`
- `pip install -r producer/requirements.txt`
- `pip install -r dashboard/requirements.txt`
- `pip install -r case_manager/requirements.txt`
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`
- `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`
- `uvicorn case_manager.main:app --reload --host 0.0.0.0 --port 58103`
- `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json`
- In `/cases`, create a sample case, add actions, and confirm KPIs and time series update on `/dashboard`.
- Generate PDF reports (operational, demographic, geographic, hourly, executive, sensitive) to ensure totals/branding render.

# version_1_0_0

## Highlights

- Adds a landing page with clear navigation between the reporting form and the analytics dashboard.
- Introduces a browser-based generator (`/report`) that pre-populates random sample data and posts it to the producer API.
- Enables CORS on the producer so the dashboard UI can create reports directly from the client.
- Provides a `GET /report_person/` endpoint to list recent reports for verification.
- Enhances the dashboard charts with tabular summaries, error handling, and fallback SQL queries when Flink aggregates are empty.
- Launches a PDF reports hub (`/reports`) and delivers the first "Alertas operativas" report with configurable filters, charts, and detailed tables powered by Pandas, Matplotlib, and ReportLab (incluye controles de orientacion portrait/landscape y tablas ajustadas a los margenes).
- Adds the "Distribucion demografica" PDF with barras de edad, analisis por genero y tabla cruzada para planear recursos.
- Incorpora el reporte "Mapa de ubicaciones" con graficos tematicos por ciudad/estado y tablas ordenadas para detectar hotspots geograficos.
- Presenta el reporte "Analisis horario" con graficas por hora, mapa de calor semanal y tabla de picos para ajustar turnos operativos.
- Suma el "Resumen ejecutivo" con indicadores clave, graficos de genero/edad, top ubicaciones y casos recientes en un unico PDF.
- Agrega "Casos sensibles" con catalogo de terminos configurable, graficos de categorias y tabla resaltada de casos prioritarios.
- Introduce el servicio `case_manager` con operaciones CRUD, timeline de acciones y KPI endpoints reutilizados por el dashboard.
- Actualiza la UI del dashboard con tarjetas de KPI, grafica temporal y branding corporativo consistente.
- Incorpora un gestor web de casos con prioridades configurables (`config/case_priorities.json`) y tipos de acción (`config/case_action_types.json`).
- Refuerza los KPIs del dashboard (new/in-progress/resolved/cancelled/archived y promedio de respuesta) y añade totales en tablas.

## Verification Checklist

- `docker-compose up -d`
- `python scripts/db_init.py`
- `uvicorn producer.main:app --reload --host 0.0.0.0 --port 58101`
- `uvicorn dashboard.main:app --reload --host 0.0.0.0 --port 58102`
- `uvicorn case_manager.main:app --reload --host 0.0.0.0 --port 58103`
- Register Debezium connector with `curl -i -X POST -H "Accept:application/json" -H "Content-Type:application/json" localhost:18084/connectors/ -d @debezium-connector.json`
- Visit `http://localhost:58102/`, open the form, generate + send several sample reports, and confirm the dashboard aggregates update in real time.
- Navigate to `http://localhost:58102/reports`, generate the "Alertas operativas" PDF for a chosen window, and review the output (chart + roster) to validate the reporting pipeline.
- Generate the "Distribucion demografica" PDF (ambas orientaciones) y confirmar que las graficas y tablas reflejan los filtros aplicados.
- Genera el "Mapa de ubicaciones" en ambos formatos, revisando los graficos y la tabla de ubicaciones para validar la agregacion geoespacial.
- Genera el "Analisis horario" en ambas orientaciones y comprueba las graficas y la tabla de horas con mayor demanda.
- Genera el "Resumen ejecutivo" para verificar graficos, tabla de ubicaciones y listado de casos recientes.
- Genera el "Casos sensibles" PDF y confirma que los terminos definidos resaltan los registros correspondientes.
- Comprueba en el dashboard web que las tarjetas KPI y la grafica de tendencias reflejan los datos de casos.
