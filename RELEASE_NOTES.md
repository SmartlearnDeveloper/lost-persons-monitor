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
