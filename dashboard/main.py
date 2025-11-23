import os
import json
import asyncio
import contextlib
import logging
from collections import Counter
from datetime import datetime, date, time, timedelta
from html import escape
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Callable, Set

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import httpx
from fastapi import FastAPI, Depends, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape as landscape_pagesize
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from aiokafka import AIOKafkaConsumer

from dashboard.database import get_db
from scripts.db_init import (
    AggAgeGroup,
    AggGender,
    AggHourly,
    Case,
    CaseStatusEnum,
    PersonLost,
)
from common.security import (
    TokenPayload,
    decode_token,
    get_token_from_request,
    require_permissions,
)

app = FastAPI(title="Lost Persons Dashboard")
templates = Jinja2Templates(directory="dashboard/templates")
HOURS = list(range(24))
AGE_GROUP_ORDER = ["0-12", "13-17", "18-25", "26-40", "41-60", "61+", "Unknown"]
WEEKDAY_NAMES_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
BRAND_NAME = "Lost Persons Monitor"
BRAND_OWNER = "ICM Software Development"
BRAND_REPORT_FOOTER = f"Reporte generado por el sistema {BRAND_NAME}."
CASE_MANAGER_INTERNAL_URL = os.environ.get("CASE_MANAGER_URL", "http://localhost:58103")
CASE_MANAGER_PUBLIC_URL = os.environ.get("CASE_MANAGER_PUBLIC_URL", CASE_MANAGER_INTERNAL_URL)
PRODUCER_PUBLIC_URL = os.environ.get("PRODUCER_PUBLIC_URL", "http://localhost:40140/report_person/")
CASE_STATUS_VALUES = [status.value for status in CaseStatusEnum]
CASE_STATUS_LABELS = {
    "new": "Nuevo",
    "in_progress": "En progreso",
    "resolved": "Resuelto",
    "cancelled": "Cancelado",
    "archived": "Archivado",
}
SENSITIVE_TERMS: List[dict] = []
SENSITIVE_INDEX: List[dict] = []
SEVERITY_RANK = {"alta": 3, "media": 2, "baja": 1}
PRIORITY_OPTIONS: List[dict] = []
PRIORITY_LABELS: dict = {}
CASE_ACTION_TYPES: List[dict] = []
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "lost_persons_server.lost_persons_db.persons_lost")
AUTH_SERVICE_INTERNAL_URL = os.environ.get("AUTH_SERVICE_URL", "http://auth_service:58104")
AUTH_PUBLIC_BASE_URL = os.environ.get("AUTH_PUBLIC_URL", "http://localhost:40155")
AUTH_SERVICE_LOGIN_URL = os.environ.get("AUTH_SERVICE_LOGIN_URL", f"{AUTH_SERVICE_INTERNAL_URL.rstrip('/')}/auth/login")
APP_LOGIN_URL = os.environ.get("APP_LOGIN_URL", "/login")
AUTH_COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "lpm_token")
AUTH_COOKIE_MAX_AGE = int(os.environ.get("AUTH_COOKIE_MAX_AGE", "3600"))
ROLE_OPTIONS = [
    {"value": "member", "label": "Miembro"},
    {"value": "reporter", "label": "Reportero"},
    {"value": "analyst", "label": "Analista"},
    {"value": "coordinator", "label": "Coordinador"},
    {"value": "admin", "label": "Administrador"},
]

app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

require_dashboard_permission = require_permissions(["dashboard"])
require_case_permission = require_permissions(["case_manager"])
require_pdf_permission = require_permissions(["pdf_reports"])
require_report_permission = require_permissions(["report"])
require_admin_permission = require_permissions(["manage_users"])

class DashboardSocketManager:
    def __init__(self) -> None:
        self.connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.connections.discard(websocket)

    async def broadcast(self, payload: str) -> None:
        async with self._lock:
            websockets = list(self.connections)
        for connection in websockets:
            try:
                await connection.send_text(payload)
            except WebSocketDisconnect:
                await self.disconnect(connection)
            except Exception:
                await self.disconnect(connection)

ws_manager = DashboardSocketManager()
_consumer_task: Optional[asyncio.Task] = None
logger = logging.getLogger("dashboard")


async def _kafka_listener() -> None:
    retry_delay = 5
    while True:
        consumer = AIOKafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id="dashboard-realtime",
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )
        try:
            await consumer.start()
            logger.info("Kafka listener conectado al tópico %s", KAFKA_TOPIC)
            async for _msg in consumer:
                await ws_manager.broadcast(json.dumps({"event": "refresh"}))
        except Exception as exc:
            logger.warning("Kafka listener error: %s. Reintentando en %s s...", exc, retry_delay)
            await asyncio.sleep(retry_delay)
        finally:
            with contextlib.suppress(Exception):
                await consumer.stop()


@app.on_event("startup")
async def start_background_tasks() -> None:
    global _consumer_task
    loop = asyncio.get_event_loop()
    _consumer_task = loop.create_task(_kafka_listener())


@app.on_event("shutdown")
async def stop_background_tasks() -> None:
    global _consumer_task
    if _consumer_task:
        _consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _consumer_task


@app.post("/internal/refresh")
async def internal_refresh() -> dict:
    await ws_manager.broadcast(json.dumps({"event": "refresh"}))
    return {"status": "ok"}


def _load_sensitive_terms() -> None:
    global SENSITIVE_TERMS, SENSITIVE_INDEX
    try:
        config_path = Path(__file__).resolve().parent.parent / "config" / "sensitive_terms.json"
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        processed = []
        for entry in data:
            term = entry.get("term", "").strip()
            if not term:
                continue
            processed.append(
                {
                    "term": term,
                    "term_lower": term.lower(),
                    "category": entry.get("category", "General"),
                    "severity": entry.get("severity", "Media"),
                }
            )
        SENSITIVE_TERMS = processed
        SENSITIVE_INDEX = processed
    except FileNotFoundError:
        SENSITIVE_TERMS = []
        SENSITIVE_INDEX = []


_load_sensitive_terms()


def _load_priority_options() -> None:
    global PRIORITY_OPTIONS, PRIORITY_LABELS
    try:
        config_path = Path(__file__).resolve().parent.parent / "config" / "case_priorities.json"
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        PRIORITY_OPTIONS = [
            {
                "value": (entry.get("value") or "").strip() or "medium",
                "label": (entry.get("label") or "").strip() or entry.get("value", "").strip() or "Media",
            }
            for entry in data
            if entry.get("value")
        ]
    except FileNotFoundError:
        PRIORITY_OPTIONS = [
            {"value": "high", "label": "Alta"},
            {"value": "medium", "label": "Media"},
            {"value": "low", "label": "Baja"},
        ]
    PRIORITY_LABELS = {item["value"]: item["label"] for item in PRIORITY_OPTIONS}


_load_priority_options()


def _load_action_types() -> None:
    global CASE_ACTION_TYPES
    try:
        config_path = Path(__file__).resolve().parent.parent / "config" / "case_action_types.json"
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        CASE_ACTION_TYPES = [
            {
                "value": (entry.get("value") or "").strip() or "update",
                "label": (entry.get("label") or "").strip() or entry.get("value", "").strip() or "Actualizacion",
            }
            for entry in data
            if entry.get("value")
        ]
    except FileNotFoundError:
        CASE_ACTION_TYPES = [
            {"value": "call", "label": "Llamada"},
            {"value": "visit", "label": "Visita"},
            {"value": "update", "label": "Actualizacion"},
        ]


_load_action_types()


def _case_manager_get(
    path: str,
    params: Optional[dict] = None,
    auth_header: Optional[str] = None,
) -> Optional[dict]:
    url = f"{CASE_MANAGER_INTERNAL_URL}{path}"
    try:
        with httpx.Client(timeout=5.0) as client:
            headers = {}
            if auth_header:
                headers["Authorization"] = auth_header
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        print(f"Case manager request failed: {exc}")
        return None


def _proxy_auth_header(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization")
    if header:
        return header
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return f"Bearer {cookie_token}"
    return None


def _current_user_optional(request: Request) -> Optional[TokenPayload]:
    token = get_token_from_request(request)
    if not token:
        return None
    try:
        return decode_token(token)
    except HTTPException:
        return None


def _ensure_ui_permissions(request: Request, permissions: List[str]) -> Optional[TokenPayload]:
    user = _current_user_optional(request)
    if not user:
        return None
    if not set(permissions).issubset(set(user.permissions)):
        return None
    return user


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={next_path}", status_code=303)


def _auth_service_request(
    method: str,
    path: str,
    *,
    token: Optional[str] = None,
    payload: Optional[dict] = None,
    timeout: float = 8.0,
) -> dict | None:
    url = f"{AUTH_SERVICE_INTERNAL_URL.rstrip('/')}{path}"
    headers = {}
    if token:
        headers["Authorization"] = token
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=payload)
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or "Error en servicio de autenticación"
        raise HTTPException(status_code=exc.response.status_code, detail=detail)
    except httpx.HTTPError as exc:
        print(f"Auth service request failed: {exc}")
        raise HTTPException(status_code=502, detail="Servicio de autenticación no disponible")


def _current_year() -> int:
    return datetime.now().astimezone().year


def _copyright_notice() -> str:
    return f"© {_current_year()} {BRAND_OWNER}. Todos los derechos reservados."


def _template_context(request: Request, current_user: Optional[TokenPayload] = None, **kwargs) -> dict:
    if current_user is None:
        current_user = _current_user_optional(request)
    base = {
        "request": request,
        "current_year": _current_year(),
        "brand_name": BRAND_NAME,
        "brand_owner": BRAND_OWNER,
        "brand_report_footer": BRAND_REPORT_FOOTER,
        "brand_copyright": _copyright_notice(),
        "case_manager_url": CASE_MANAGER_PUBLIC_URL,
        "priority_options": PRIORITY_OPTIONS,
        "action_types": CASE_ACTION_TYPES,
        "case_status_values": CASE_STATUS_VALUES,
        "case_status_options": [
            {
                "value": value,
                "label": CASE_STATUS_LABELS.get(value, value.replace("_", " ").title()),
            }
            for value in CASE_STATUS_VALUES
        ],
        "current_user": current_user,
        "auth_login_url": APP_LOGIN_URL,
        "auth_base_url": AUTH_PUBLIC_BASE_URL,
        "role_options": ROLE_OPTIONS,
    }
    base.update(kwargs)
    return base


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_generation_timestamp() -> str:
    local_now = datetime.now().astimezone()
    tz_name = local_now.tzname() or "Local"
    return f"{local_now.strftime('%Y-%m-%d %H:%M')} {tz_name}"


def _assign_age_group(age: Optional[int]) -> str:
    if age is None or age < 0:
        return "Unknown"
    if age <= 12:
        return "0-12"
    if age <= 17:
        return "13-17"
    if age <= 25:
        return "18-25"
    if age <= 40:
        return "26-40"
    if age <= 60:
        return "41-60"
    return "61+"


def _split_location(location: Optional[str]) -> tuple[str, str]:
    if not location:
        return "Unknown", "Unknown"
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if not parts:
        return "Unknown", "Unknown"
    if len(parts) == 1:
        return parts[0], "Unknown"
    return parts[0], parts[-1]


def _detect_sensitive_terms(*text_parts: Optional[str]) -> List[dict]:
    if not SENSITIVE_INDEX:
        return []
    combined = " ".join(part for part in text_parts if part).lower()
    matches: List[dict] = []
    seen_terms = set()
    for entry in SENSITIVE_INDEX:
        term_lower = entry["term_lower"]
        if term_lower in combined and term_lower not in seen_terms:
            matches.append(
                {
                    "term": entry["term"],
                    "category": entry["category"],
                    "severity": entry["severity"],
                }
            )
            seen_terms.add(term_lower)
    return matches


def _create_pdf_doc(buffer: BytesIO, orientation: str, title: str) -> tuple[SimpleDocTemplate, Callable]:
    page_size = LETTER if orientation == "portrait" else landscape_pagesize(LETTER)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        title=title,
        author="Lost Persons Monitor",
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    def _add_page_number(canvas_obj, doc_obj):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 9)
        width, _ = canvas_obj._pagesize
        page_label = f"Pagina {doc_obj.page}"
        footer_left = f"{BRAND_REPORT_FOOTER} {_copyright_notice()}"
        canvas_obj.drawString(0.5 * inch, 0.5 * inch, footer_left)
        canvas_obj.drawRightString(width - 0.5 * inch, 0.5 * inch, page_label)
        canvas_obj.restoreState()

    return doc, _add_page_number


def _render_operational_alerts_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the operational alerts report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
    )
    return templates.TemplateResponse(
        "report_operational_alerts.html",
        context,
        status_code=400 if error_message else 200,
    )


def _render_demographic_distribution_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the demographic distribution report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
    )
    return templates.TemplateResponse(
        "report_demographic_distribution.html",
        context,
        status_code=400 if error_message else 200,
    )


def _render_geographic_distribution_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the geographic distribution report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
    )
    return templates.TemplateResponse(
        "report_geographic_distribution.html",
        context,
        status_code=400 if error_message else 200,
    )


def _render_hourly_analysis_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the hourly analysis report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
    )
    return templates.TemplateResponse(
        "report_hourly_analysis.html",
        context,
        status_code=400 if error_message else 200,
    )


def _render_executive_summary_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the executive summary report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
    )
    return templates.TemplateResponse(
        "report_executive_summary.html",
        context,
        status_code=400 if error_message else 200,
    )


def _render_sensitive_cases_form(
    request: Request,
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
    error_message: Optional[str] = None,
):
    """Render the filter form for the sensitive cases report."""
    context = _template_context(
        request,
        hours=HOURS,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
        error_message=error_message,
        terms_catalog=SENSITIVE_TERMS,
    )
    return templates.TemplateResponse(
        "report_sensitive_cases.html",
        context,
        status_code=400 if error_message else 200,
    )


def _build_operational_alerts_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the operational alerts report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Alertas operativas")
    styles = getSampleStyleSheet()
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Reporte de Alertas Operativas", styles["Title"]),
        Paragraph(
            f"Rango de fechas: {start_date.isoformat()} a {end_date.isoformat()} "
            f"| Horas: {start_hour:02d}:00 - {end_hour:02d}:00",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    if not records:
        story.append(
            Paragraph(
                "No se encontraron reportes para los filtros aplicados.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(records)
    df["gender_label"] = df["gender"].fillna("Unknown")
    df["location_label"] = df["lost_location"].fillna("Unknown")

    total_reports = len(df)
    story.append(Paragraph(f"Total de reportes activos: {total_reports}", styles["Heading3"]))

    top_locations = df["location_label"].value_counts().head(3)
    if not top_locations.empty:
        formatted_locations = ", ".join(
            f"{location}: {count}" for location, count in top_locations.items()
        )
        story.append(
            Paragraph(
                f"Ubicaciones principales: {formatted_locations}",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 12))

    gender_counts = df.groupby("gender_label")["person_id"].count().sort_values(ascending=False)
    fig_width = 5.5 if orientation == "portrait" else 7.0
    fig, ax = plt.subplots(figsize=(fig_width, 3.2))
    colors_palette = ["#0d6efd", "#6610f2", "#20c997", "#6c757d"]
    bars = ax.bar(
        gender_counts.index,
        gender_counts.values,
        color=colors_palette[: len(gender_counts.index)],
    )
    ax.set_ylabel("Total")
    ax.set_title("Reportes por genero")
    ax.grid(axis="y", alpha=0.2, linestyle="--", linewidth=0.5)
    ax.set_ylim(0, max(gender_counts.values.max() * 1.3, 1))
    ax.bar_label(bars, padding=3, fontsize=8)
    fig.tight_layout()
    chart_buffer = BytesIO()
    fig.savefig(chart_buffer, format="png", dpi=150)
    plt.close(fig)
    chart_buffer.seek(0)
    chart_width = (5.2 if orientation == "portrait" else 6.8) * inch
    story.append(Image(chart_buffer, width=chart_width, height=3.0 * inch))
    story.append(Spacer(1, 16))

    table_data = [
        ["ID", "Nombre", "Edad", "Genero", "Ubicacion", "Fecha reporte", "Detalles"],
    ]
    for record in records:
        full_name = f"{record['first_name']} {record['last_name']}".strip()
        table_data.append(
            [
                Paragraph(escape(str(record["person_id"])), table_text_center),
                Paragraph(escape(full_name) or "-", table_text_style),
                Paragraph(
                    escape(str(record["age"])) if record["age"] is not None else "-",
                    table_text_center,
                ),
                Paragraph(escape(record["gender"] or "Unknown"), table_text_center),
                Paragraph(escape(record["lost_location"] or "-"), table_text_style),
                Paragraph(
                    escape(record["lost_timestamp"].strftime("%Y-%m-%d %H:%M")),
                    table_text_center,
                ),
                Paragraph(escape(record["details"] or "-"), table_text_style),
            ]
        )

    if orientation == "portrait":
        column_layout = [0.5, 1.2, 0.6, 0.7, 1.2, 1.0, 2.2]
    else:
        column_layout = [0.6, 1.5, 0.7, 0.8, 1.5, 1.2, 3.0]

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[width * inch for width in column_layout],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f3f5")]),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (3, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


def _build_demographic_distribution_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the demographic distribution report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Distribucion demografica")
    styles = getSampleStyleSheet()
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Reporte de Distribucion Demografica", styles["Title"]),
        Paragraph(
            f"Rango de fechas: {start_date.isoformat()} a {end_date.isoformat()} "
            f"| Horas: {start_hour:02d}:00 - {end_hour:02d}:00",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    if not records:
        story.append(
            Paragraph(
                "No se encontraron reportes para los filtros aplicados.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(records)
    df["age_group"] = df["age"].apply(_assign_age_group)
    df["gender_label"] = df["gender"].fillna("Unknown")

    total_reports = len(df)
    story.append(Paragraph(f"Total de registros analizados: {total_reports}", styles["Heading3"]))

    age_counts = df["age_group"].value_counts().reindex(AGE_GROUP_ORDER, fill_value=0)
    gender_counts = df["gender_label"].value_counts().sort_values(ascending=False)

    if age_counts.sum() > 0:
        top_age_group = age_counts.idxmax()
        story.append(
            Paragraph(
                f"Grupo de edad predominante: {top_age_group} ({age_counts.loc[top_age_group]} casos).",
                styles["Normal"],
            )
        )
    if not gender_counts.empty:
        dominant_gender = gender_counts.index[0]
        story.append(
            Paragraph(
                f"Genero predominante: {dominant_gender} ({gender_counts.iloc[0]} casos).",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 12))

    age_for_plot = age_counts[age_counts > 0]
    if age_for_plot.empty:
        age_for_plot = age_counts

    fig_width = 5.5 if orientation == "portrait" else 7.0
    fig_age, ax_age = plt.subplots(figsize=(fig_width, 3.2))
    colors_palette = ["#0d6efd", "#6610f2", "#20c997", "#6c757d", "#fd7e14", "#198754", "#adb5bd"]
    bars_age = ax_age.bar(
        age_for_plot.index,
        age_for_plot.values,
        color=colors_palette[: len(age_for_plot.index)],
    )
    ax_age.set_ylabel("Total")
    ax_age.set_xlabel("Grupo etario")
    ax_age.set_title("Distribucion por grupo de edad")
    ax_age.grid(axis="y", alpha=0.2, linestyle="--", linewidth=0.5)
    ax_age.set_ylim(0, max(age_for_plot.values.max() * 1.2, 1))
    ax_age.bar_label(bars_age, padding=3, fontsize=8)
    ax_age.tick_params(axis="x", rotation=35)
    fig_age.tight_layout()
    chart_age_buffer = BytesIO()
    fig_age.savefig(chart_age_buffer, format="png", dpi=150)
    plt.close(fig_age)
    chart_age_buffer.seek(0)
    chart_age_width = (5.2 if orientation == "portrait" else 6.8) * inch
    story.append(Image(chart_age_buffer, width=chart_age_width, height=3.0 * inch))

    if not gender_counts.empty:
        story.append(Spacer(1, 12))
        fig_gender_width = 4.8 if orientation == "portrait" else 6.0
        fig_gender, ax_gender = plt.subplots(figsize=(fig_gender_width, 2.8))
        gender_colors = ["#0d6efd", "#d63384", "#20c997", "#6c757d", "#fd7e14"]
        bars_gender = ax_gender.barh(
            gender_counts.index[::-1],
            gender_counts.values[::-1],
            color=gender_colors[: len(gender_counts.index)],
        )
        ax_gender.set_xlabel("Total")
        ax_gender.set_title("Distribucion por genero")
        ax_gender.grid(axis="x", alpha=0.2, linestyle="--", linewidth=0.5)
        ax_gender.bar_label(bars_gender, padding=4, fontsize=8)
        fig_gender.tight_layout()
        chart_gender_buffer = BytesIO()
        fig_gender.savefig(chart_gender_buffer, format="png", dpi=150)
        plt.close(fig_gender)
        chart_gender_buffer.seek(0)
        chart_gender_width = (4.6 if orientation == "portrait" else 6.0) * inch
        story.append(Image(chart_gender_buffer, width=chart_gender_width, height=2.6 * inch))

    story.append(Spacer(1, 16))

    pivot = (
        df.pivot_table(
            index="age_group",
            columns="gender_label",
            values="person_id",
            aggfunc="count",
            fill_value=0,
        )
        .reindex(index=AGE_GROUP_ORDER, fill_value=0)
    )
    gender_columns = list(gender_counts.index)
    if not gender_columns:
        gender_columns = sorted(pivot.columns)
    pivot = pivot.reindex(columns=gender_columns, fill_value=0)

    header = ["Grupo etario"] + gender_columns + ["Total"]
    table_data = [header]

    column_totals = {gender: int(pivot[gender].sum()) for gender in gender_columns}
    overall_total = sum(column_totals.values())

    for group in AGE_GROUP_ORDER:
        row_counts = [int(pivot.at[group, gender]) if group in pivot.index else 0 for gender in gender_columns]
        row_total = sum(row_counts)
        row_cells = [
            Paragraph(group, table_text_style),
            *[Paragraph(str(value), table_text_center) for value in row_counts],
            Paragraph(str(row_total), table_text_center),
        ]
        table_data.append(row_cells)

    totals_row = [
        Paragraph("Total", table_text_style),
        *[Paragraph(str(column_totals[gender]), table_text_center) for gender in gender_columns],
        Paragraph(str(overall_total), table_text_center),
    ]
    table_data.append(totals_row)

    if orientation == "portrait":
        column_layout = [1.2] + [0.9] * len(gender_columns) + [0.9]
    else:
        column_layout = [1.5] + [1.1] * len(gender_columns) + [1.1]

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[width * inch for width in column_layout],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#198754")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8f9fa")]),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e9ecef")),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


def _build_geographic_distribution_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the geographic distribution report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Mapa de ubicaciones")
    styles = getSampleStyleSheet()
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Reporte de Mapa de Ubicaciones", styles["Title"]),
        Paragraph(
            f"Rango de fechas: {start_date.isoformat()} a {end_date.isoformat()} "
            f"| Horas: {start_hour:02d}:00 - {end_hour:02d}:00",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    if not records:
        story.append(
            Paragraph(
                "No se encontraron reportes para los filtros aplicados.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(records)
    df["lost_location"] = df["lost_location"].fillna("").apply(lambda loc: loc.strip())
    df["location_label"] = df["lost_location"].apply(lambda loc: loc if loc else "Unknown")
    split_series = df["location_label"].apply(_split_location)
    df["city"] = split_series.apply(lambda item: item[0])
    df["region"] = split_series.apply(lambda item: item[1])

    total_reports = len(df)
    unique_locations = df["location_label"].nunique()
    story.append(Paragraph(f"Total de reportes analizados: {total_reports}", styles["Heading3"]))
    story.append(
        Paragraph(
            f"Ubicaciones unicas en el periodo: {unique_locations}",
            styles["Normal"],
        )
    )

    top_location_series = df["location_label"].value_counts()
    if not top_location_series.empty:
        top_location = top_location_series.index[0]
        story.append(
            Paragraph(
                f"Ubicacion con mayor actividad: {top_location} ({top_location_series.iloc[0]} reportes).",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 12))

    top_locations = top_location_series.head(12)
    if top_locations.empty:
        top_locations = top_location_series

    fig_width = 5.6 if orientation == "portrait" else 7.2
    fig_locations, ax_locations = plt.subplots(figsize=(fig_width, 3.4))
    y_positions = np.arange(len(top_locations))
    cmap = plt.cm.get_cmap("Blues")
    location_colors = cmap(np.linspace(0.45, 0.85, len(top_locations)))
    bars = ax_locations.barh(
        y_positions,
        top_locations.values[::-1],
        color=location_colors[::-1],
    )
    ax_locations.set_yticks(y_positions)
    ax_locations.set_yticklabels(top_locations.index[::-1], fontsize=8)
    ax_locations.set_xlabel("Total de reportes")
    ax_locations.set_title("Top ubicaciones reportadas")
    ax_locations.invert_yaxis()
    ax_locations.grid(axis="x", alpha=0.2, linestyle="--", linewidth=0.5)
    ax_locations.bar_label(bars, padding=4, fontsize=8)
    fig_locations.tight_layout()
    chart_locations_buffer = BytesIO()
    fig_locations.savefig(chart_locations_buffer, format="png", dpi=150)
    plt.close(fig_locations)
    chart_locations_buffer.seek(0)
    chart_locations_width = (5.4 if orientation == "portrait" else 7.0) * inch
    story.append(Image(chart_locations_buffer, width=chart_locations_width, height=3.0 * inch))

    story.append(Spacer(1, 12))

    region_counts = df["region"].value_counts()
    region_counts = region_counts[region_counts > 0]
    if not region_counts.empty:
        fig_region_width = 4.8 if orientation == "portrait" else 6.2
        fig_regions, ax_regions = plt.subplots(figsize=(fig_region_width, 2.8))
        region_colors = plt.cm.get_cmap("Oranges")(np.linspace(0.45, 0.85, len(region_counts)))
        bars_regions = ax_regions.bar(
            region_counts.index,
            region_counts.values,
            color=region_colors,
        )
        ax_regions.set_ylabel("Total")
        ax_regions.set_xlabel("Estado / Region")
        ax_regions.set_title("Distribucion por region")
        ax_regions.grid(axis="y", alpha=0.2, linestyle="--", linewidth=0.5)
        ax_regions.bar_label(bars_regions, padding=3, fontsize=8)
        ax_regions.tick_params(axis="x", rotation=35)
        fig_regions.tight_layout()
        chart_regions_buffer = BytesIO()
        fig_regions.savefig(chart_regions_buffer, format="png", dpi=150)
        plt.close(fig_regions)
        chart_regions_buffer.seek(0)
        chart_regions_width = (4.6 if orientation == "portrait" else 6.0) * inch
        story.append(Image(chart_regions_buffer, width=chart_regions_width, height=2.6 * inch))
        story.append(Spacer(1, 12))

    location_summary = (
        df.groupby(["location_label", "city", "region"])
        .size()
        .reset_index(name="total")
        .sort_values("total", ascending=False)
    )

    summary_limit = 40 if orientation == "portrait" else 60
    summary_subset = location_summary.head(summary_limit)

    header = ["#", "Ubicacion", "Ciudad", "Estado / Region", "Total"]
    table_data = [header]
    for idx, row in enumerate(summary_subset.itertuples(index=False), start=1):
        table_data.append(
            [
                Paragraph(str(idx), table_text_center),
                Paragraph(escape(row.location_label), table_text_style),
                Paragraph(escape(row.city), table_text_style),
                Paragraph(escape(row.region), table_text_style),
                Paragraph(str(int(row.total)), table_text_center),
            ]
        )

    column_widths = (
        [0.6, 2.4, 1.5, 1.5, 0.9] if orientation == "portrait" else [0.6, 3.0, 1.7, 1.7, 1.0]
    )
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[width * inch for width in column_widths],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0dcaf0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f3f5")]),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (4, 1), (4, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    if len(location_summary) > summary_limit:
        remaining = len(location_summary) - summary_limit
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                f"Nota: se muestran las primeras {summary_limit} ubicaciones con mayor actividad. "
                f"Existen {remaining} ubicaciones adicionales en el periodo seleccionado.",
                styles["Italic"],
            )
        )

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


def _build_hourly_analysis_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the hourly analysis report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Analisis horario")
    styles = getSampleStyleSheet()
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )

    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Reporte de Analisis Horario", styles["Title"]),
        Paragraph(
            f"Rango de fechas: {start_date.isoformat()} a {end_date.isoformat()} "
            f"| Horas: {start_hour:02d}:00 - {end_hour:02d}:00",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    if not records:
        story.append(
            Paragraph(
                "No se encontraron reportes para los filtros aplicados.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(records)
    df["lost_timestamp"] = pd.to_datetime(df["lost_timestamp"])
    df["hour"] = df["lost_timestamp"].dt.hour
    df["weekday_index"] = df["lost_timestamp"].dt.weekday
    df["weekday_name"] = df["weekday_index"].apply(lambda idx: WEEKDAY_NAMES_ES[idx] if 0 <= idx < len(WEEKDAY_NAMES_ES) else "Desconocido")

    total_reports = len(df)
    story.append(Paragraph(f"Total de reportes analizados: {total_reports}", styles["Heading3"]))

    hour_counts = df.groupby("hour").size().reindex(range(24), fill_value=0)
    busiest_hour = hour_counts.idxmax()
    busiest_count = hour_counts.max()
    story.append(
        Paragraph(
            f"Hora con mayor actividad: {busiest_hour:02d}:00 ({busiest_count} reportes).",
            styles["Normal"],
        )
    )

    avg_per_hour = hour_counts.mean()
    story.append(
        Paragraph(
            f"Promedio de reportes por hora en el rango: {avg_per_hour:.2f}",
            styles["Normal"],
        )
    )

    story.append(Spacer(1, 12))

    fig_width = 6.2 if orientation == "portrait" else 7.5
    fig_line, ax_line = plt.subplots(figsize=(fig_width, 3.2))
    hours_range = list(range(24))
    ax_line.plot(hours_range, hour_counts.values, marker="o", color="#0d6efd", linewidth=2)
    ax_line.set_xlabel("Hora del dia")
    ax_line.set_ylabel("Total de reportes")
    ax_line.set_title("Volumen por hora del dia")
    ax_line.grid(alpha=0.3, linestyle="--", linewidth=0.6)
    ax_line.set_xticks(hours_range)
    ax_line.set_xticklabels([f"{hour:02d}" for hour in hours_range], rotation=45, fontsize=7)
    fig_line.tight_layout()
    chart_line_buffer = BytesIO()
    fig_line.savefig(chart_line_buffer, format="png", dpi=150)
    plt.close(fig_line)
    chart_line_buffer.seek(0)
    chart_line_width = (6.0 if orientation == "portrait" else 7.3) * inch
    story.append(Image(chart_line_buffer, width=chart_line_width, height=3.0 * inch))

    story.append(Spacer(1, 12))

    heatmap_data = (
        df.groupby(["weekday_index", "hour"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=range(7), columns=range(24), fill_value=0)
    )
    if heatmap_data.values.sum() > 0:
        fig_heat_width = 6.2 if orientation == "portrait" else 7.5
        fig_heat, ax_heat = plt.subplots(figsize=(fig_heat_width, 3.2))
        heatmap = ax_heat.imshow(
            heatmap_data.values,
            aspect="auto",
            cmap="YlGnBu",
        )
        ax_heat.set_title("Mapa de calor por dia y hora")
        ax_heat.set_xlabel("Hora del dia")
        ax_heat.set_ylabel("Dia de la semana")
        ax_heat.set_xticks(range(0, 24, 2))
        ax_heat.set_xticklabels([f"{hour:02d}" for hour in range(0, 24, 2)])
        ax_heat.set_yticks(range(7))
        ax_heat.set_yticklabels([WEEKDAY_NAMES_ES[idx] for idx in range(7)])
        fig_heat.colorbar(heatmap, ax=ax_heat, fraction=0.046, pad=0.04)
        fig_heat.tight_layout()
        chart_heat_buffer = BytesIO()
        fig_heat.savefig(chart_heat_buffer, format="png", dpi=150)
        plt.close(fig_heat)
        chart_heat_buffer.seek(0)
        chart_heat_width = (6.0 if orientation == "portrait" else 7.3) * inch
        story.append(Image(chart_heat_buffer, width=chart_heat_width, height=3.0 * inch))
        story.append(Spacer(1, 12))

    top_hours = hour_counts.sort_values(ascending=False).head(10)
    summary_table = [
        ["Hora", "Reportes", "% sobre el total"],
    ]
    for hour, count in top_hours.items():
        percentage = (count / total_reports * 100) if total_reports else 0
        summary_table.append(
            [
                Paragraph(f"{hour:02d}:00", table_text_center),
                Paragraph(str(int(count)), table_text_center),
                Paragraph(f"{percentage:.1f}%", table_text_center),
            ]
        )

    table_widths = [1.2, 1.0, 1.4] if orientation == "portrait" else [1.4, 1.1, 1.4]
    summary = Table(
        summary_table,
        repeatRows=1,
        colWidths=[width * inch for width in table_widths],
    )
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6f42c1")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("ALIGN", (0, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary)

    if len(hour_counts[hour_counts > 0]) > len(top_hours):
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                "Nota: se muestran las 10 horas con mayor actividad. Consulte el mapa de calor para ver el resto de las horas.",
                styles["Italic"],
            )
        )

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


def _build_executive_summary_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the executive summary report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Resumen ejecutivo")
    styles = getSampleStyleSheet()
    base_style = styles["BodyText"]
    summary_line_style = ParagraphStyle(
        name="SummaryLine",
        parent=base_style,
        leading=12,
    )
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=base_style,
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )
    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Resumen Ejecutivo de Personas Perdidas", styles["Title"]),
        Paragraph(
            f"Ventana analizada: {start_date.isoformat()} a {end_date.isoformat()} "
            f"(horas {start_hour:02d}:00 - {end_hour:02d}:00)",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    if not records:
        story.append(
            Paragraph(
                "No se encontraron reportes para los filtros aplicados.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(records)
    df["lost_timestamp"] = pd.to_datetime(df["lost_timestamp"])
    df["gender_label"] = df["gender"].fillna("Unknown")
    df["age_group"] = df["age"].apply(_assign_age_group)
    df["location_label"] = df["lost_location"].fillna("Unknown")

    total_reports = len(df)
    unique_locations = df["location_label"].nunique()
    active_days = df["lost_timestamp"].dt.date.nunique()
    latest_report = df["lost_timestamp"].max()
    avg_age = df["age"].dropna()
    avg_age_value = avg_age.mean() if not avg_age.empty else None

    summary_lines = [
        f"Total de reportes en el periodo: <b>{total_reports}</b>",
        f"Dias con actividad registrada: <b>{active_days}</b>",
        f"Ubicaciones unicas: <b>{unique_locations}</b>",
    ]
    if avg_age_value is not None:
        summary_lines.append(
            f"Edad promedio de las personas reportadas: <b>{avg_age_value:.1f}</b> años"
        )
    summary_lines.append(
        f"Ultimo reporte ingresado: <b>{latest_report.strftime('%Y-%m-%d %H:%M')}</b>"
    )
    for line in summary_lines:
        story.append(Paragraph(f"• {line}", summary_line_style))
    story.append(Spacer(1, 14))

    gender_counts = df["gender_label"].value_counts()
    age_group_counts = df["age_group"].value_counts().reindex(AGE_GROUP_ORDER, fill_value=0)

    fig_gender_width = 4.5 if orientation == "portrait" else 5.5
    fig_gender, ax_gender = plt.subplots(figsize=(fig_gender_width, 3.0))
    colors_gender = ["#0d6efd", "#d63384", "#20c997", "#6c757d"]
    ax_gender.pie(
        gender_counts.values,
        labels=gender_counts.index,
        autopct="%1.0f%%",
        startangle=140,
        colors=colors_gender[: len(gender_counts)],
    )
    ax_gender.set_title("Distribucion por genero")
    fig_gender.tight_layout()
    gender_buffer = BytesIO()
    fig_gender.savefig(gender_buffer, format="png", dpi=150)
    plt.close(fig_gender)
    gender_buffer.seek(0)

    fig_age_width = 4.5 if orientation == "portrait" else 6.0
    fig_age, ax_age = plt.subplots(figsize=(fig_age_width, 3.0))
    colors_age = ["#0d6efd", "#6610f2", "#20c997", "#6f42c1", "#fd7e14", "#198754", "#adb5bd"]
    bars_age = ax_age.bar(
        age_group_counts.index,
        age_group_counts.values,
        color=colors_age[: len(age_group_counts.index)],
    )
    ax_age.set_ylabel("Total")
    ax_age.set_title("Distribucion por grupo de edad")
    ax_age.grid(axis="y", alpha=0.2, linestyle="--", linewidth=0.5)
    ax_age.bar_label(bars_age, padding=3, fontsize=8)
    fig_age.tight_layout()
    age_buffer = BytesIO()
    fig_age.savefig(age_buffer, format="png", dpi=150)
    plt.close(fig_age)
    age_buffer.seek(0)

    if orientation == "portrait":
        chart_width = 4.6 * inch
        story.append(Image(gender_buffer, width=chart_width, height=2.8 * inch))
        story.append(Spacer(1, 8))
        story.append(Image(age_buffer, width=chart_width, height=2.8 * inch))
    else:
        chart_width_gender = 5.0 * inch
        chart_width_age = 5.5 * inch
        charts_table = Table(
            [
                [
                    Image(gender_buffer, width=chart_width_gender, height=3.0 * inch),
                    Image(age_buffer, width=chart_width_age, height=3.0 * inch),
                ]
            ],
            colWidths=[chart_width_gender, chart_width_age],
        )
        charts_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(charts_table)
    story.append(Spacer(1, 12))

    top_locations = (
        df["location_label"]
        .value_counts()
        .head(5)
        .reset_index(name="total")
        .rename(columns={"index": "location_label"})
    )
    location_rows = [
        [
            Paragraph("Ubicacion", table_text_style),
            Paragraph("Reportes", table_text_center),
        ]
    ]
    for location_value, total_value in top_locations.itertuples(index=False, name=None):
        location_rows.append(
            [
                Paragraph(escape(str(location_value)), table_text_style),
                Paragraph(str(int(total_value)), table_text_center),
            ]
        )
    location_table = Table(
        location_rows,
        repeatRows=1,
        colWidths=[(4.5 if orientation == "portrait" else 5.5) * inch, 1.0 * inch],
    )
    location_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0dcaf0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f3f5")]),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(location_table)
    story.append(Spacer(1, 12))

    recent_cases = df.sort_values("lost_timestamp", ascending=False).head(6)
    cases_rows = [
        [
            Paragraph("Fecha reporte", table_text_center),
            Paragraph("Nombre", table_text_style),
            Paragraph("Genero", table_text_center),
            Paragraph("Edad", table_text_center),
            Paragraph("Ubicacion", table_text_style),
            Paragraph("Detalles", table_text_style),
        ]
    ]
    for row in recent_cases.itertuples(index=False):
        full_name = f"{getattr(row, 'first_name', '')} {getattr(row, 'last_name', '')}".strip()
        cases_rows.append(
            [
                Paragraph(row.lost_timestamp.strftime("%Y-%m-%d %H:%M"), table_text_center),
                Paragraph(escape(full_name or "-"), table_text_style),
                Paragraph(escape(row.gender or "Unknown"), table_text_center),
                Paragraph(str(row.age) if row.age is not None else "-", table_text_center),
                Paragraph(escape(row.location_label or "-"), table_text_style),
                Paragraph(escape(row.details or "-"), table_text_style),
            ]
        )

    if orientation == "portrait":
        case_widths = [1.2, 1.8, 0.8, 0.6, 1.6, 2.4]
    else:
        case_widths = [1.4, 2.2, 0.8, 0.7, 1.9, 3.2]

    cases_table = Table(
        cases_rows,
        repeatRows=1,
        colWidths=[width * inch for width in case_widths],
    )
    cases_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#198754")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (3, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(cases_table)

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


def _build_sensitive_cases_pdf(
    records: List[dict],
    start_date: date,
    end_date: date,
    start_hour: int,
    end_hour: int,
    orientation: str,
) -> BytesIO:
    """Build the PDF bytes for the sensitive cases report."""
    buffer = BytesIO()
    doc, add_page_number = _create_pdf_doc(buffer, orientation, "Casos sensibles")
    styles = getSampleStyleSheet()
    base_style = styles["BodyText"]
    table_text_style = ParagraphStyle(
        name="TableBody",
        parent=base_style,
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )
    if orientation == "portrait":
        table_text_style.fontSize = 8
        table_text_style.leading = 10

    table_text_center = ParagraphStyle(
        name="TableBodyCenter",
        parent=table_text_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("Reporte de Casos Sensibles", styles["Title"]),
        Paragraph(
            f"Ventana analizada: {start_date.isoformat()} a {end_date.isoformat()} "
            f"(horas {start_hour:02d}:00 - {end_hour:02d}:00)",
            styles["Normal"],
        ),
        Paragraph(
            f"Generado: {_format_generation_timestamp()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    flagged_records = []
    for record in records:
        matches = _detect_sensitive_terms(record.get("details"), record.get("lost_location"))
        if matches:
            record_copy = record.copy()
            record_copy["matches"] = matches
            flagged_records.append(record_copy)

    if not flagged_records:
        story.append(
            Paragraph(
                "No se detectaron casos sensibles con los criterios actuales. "
                "Actualiza la lista de terminos en config/sensitive_terms.json para ampliar la cobertura.",
                styles["Italic"],
            )
        )
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return buffer

    df = pd.DataFrame(flagged_records)
    df["lost_timestamp"] = pd.to_datetime(df["lost_timestamp"])
    df["location_label"] = df["lost_location"].fillna("Unknown")
    df["match_terms"] = df["matches"].apply(lambda m: sorted({match["term"] for match in m}))
    df["match_categories"] = df["matches"].apply(lambda m: sorted({match["category"] for match in m}))
    df["max_severity"] = df["matches"].apply(
        lambda m: max((SEVERITY_RANK.get(match["severity"].lower(), 1) for match in m), default=1)
    )
    df["max_severity_label"] = df["matches"].apply(
        lambda m: max((match["severity"] for match in m), key=lambda s: SEVERITY_RANK.get(s.lower(), 1), default="Media")
    )

    total_sensitives = len(df)
    category_counter: Counter = Counter()
    term_counter: Counter = Counter()
    severity_counter: Counter = Counter()
    for matches in df["matches"]:
        for match in matches:
            category_counter[match["category"]] += 1
            term_counter[match["term"]] += 1
            severity_counter[match["severity"]] += 1

    summary_paragraphs = [
        f"Casos sensibles detectados en el periodo: <b>{total_sensitives}</b>",
        f"Categorias impactadas: <b>{len(category_counter)}</b>",
        f"Niveles de severidad: "
        + ", ".join(
            f"{severity} ({count})"
            for severity, count in sorted(
                severity_counter.items(),
                key=lambda item: SEVERITY_RANK.get(item[0].lower(), 1),
                reverse=True,
            )
        ),
    ]
    top_term = term_counter.most_common(1)
    if top_term:
        summary_paragraphs.append(
            f"Termino mas frecuente: <b>{top_term[0][0]}</b> ({top_term[0][1]} menciones)"
        )
    for line in summary_paragraphs:
        story.append(Paragraph(f"• {line}", base_style))
    story.append(Spacer(1, 12))

    if category_counter:
        categories, category_values = zip(*category_counter.most_common())
        fig_width = 6.0 if orientation == "portrait" else 7.2
        fig_categories, ax_categories = plt.subplots(figsize=(fig_width, 3.0))
        bars = ax_categories.bar(categories, category_values, color="#dc3545")
        ax_categories.set_ylabel("Coincidencias")
        ax_categories.set_title("Distribucion de categorias sensibles")
        ax_categories.grid(axis="y", alpha=0.2, linestyle="--", linewidth=0.5)
        ax_categories.tick_params(axis="x", rotation=35)
        ax_categories.bar_label(bars, padding=3, fontsize=8)
        fig_categories.tight_layout()
        categories_buffer = BytesIO()
        fig_categories.savefig(categories_buffer, format="png", dpi=150)
        plt.close(fig_categories)
        categories_buffer.seek(0)
        chart_width = (5.8 if orientation == "portrait" else 7.0) * inch
        story.append(Image(categories_buffer, width=chart_width, height=3.0 * inch))
        story.append(Spacer(1, 12))

    top_terms_rows = [
        [Paragraph("Termino", table_text_style), Paragraph("Coincidencias", table_text_center)]
    ]
    for term, count in term_counter.most_common(8):
        top_terms_rows.append(
            [
                Paragraph(escape(term), table_text_style),
                Paragraph(str(count), table_text_center),
            ]
        )
    term_table = Table(
        top_terms_rows,
        repeatRows=1,
        colWidths=[(3.8 if orientation == "portrait" else 4.6) * inch, 1.2 * inch],
    )
    term_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ffc107")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff3cd")]),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
            ]
        )
    )
    story.append(term_table)
    story.append(Spacer(1, 12))

    severity_labels = {3: "Alta", 2: "Media", 1: "Baja"}
    severity_colors = {
        3: colors.HexColor("#dc3545"),
        2: colors.HexColor("#fd7e14"),
        1: colors.HexColor("#ffc107"),
    }

    df = df.sort_values(["max_severity", "lost_timestamp"], ascending=[False, False])
    max_rows = 40 if orientation == "portrait" else 60
    limited_df = df.head(max_rows)

    cases_rows = [
        [
            Paragraph("Fecha", table_text_center),
            Paragraph("Nombre", table_text_style),
            Paragraph("Ubicacion", table_text_style),
            Paragraph("Severidad", table_text_center),
            Paragraph("Alertas detectadas", table_text_style),
            Paragraph("Detalles", table_text_style),
        ]
    ]
    row_severities: List[int] = []
    for row in limited_df.itertuples(index=False):
        full_name = f"{getattr(row, 'first_name', '')} {getattr(row, 'last_name', '')}".strip()
        severity_rank = getattr(row, "max_severity", 1)
        severity_label = severity_labels.get(severity_rank, "Media")
        matched_terms = getattr(row, "match_terms", [])
        cases_rows.append(
            [
                Paragraph(row.lost_timestamp.strftime("%Y-%m-%d %H:%M"), table_text_center),
                Paragraph(escape(full_name or "-"), table_text_style),
                Paragraph(escape(row.location_label or "-"), table_text_style),
                Paragraph(severity_label, table_text_center),
                Paragraph(", ".join(matched_terms) or "-", table_text_style),
                Paragraph(escape(row.details or "-"), table_text_style),
            ]
        )
        row_severities.append(severity_rank)

    if orientation == "portrait":
        column_layout = [1.0, 1.3, 1.2, 0.8, 1.5, 1.7]  # Total 7.5 in on portrait page (8.5in width - 1in margins)
    else:
        column_layout = [1.2, 1.8, 1.6, 0.8, 2.0, 2.6]  # Total 10.0 in on landscape page (11in width - 1in margins)

    cases_table = Table(
        cases_rows,
        repeatRows=1,
        colWidths=[width * inch for width in column_layout],
    )
    base_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6f42c1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#adb5bd")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ced4da")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for idx, severity_rank in enumerate(row_severities, start=1):
        fill_color = severity_colors.get(severity_rank, colors.HexColor("#fff3cd"))
        base_style_commands.append(("BACKGROUND", (0, idx), (-1, idx), fill_color))
    cases_table.setStyle(TableStyle(base_style_commands))
    story.append(cases_table)

    if len(df) > max_rows:
        remaining = len(df) - max_rows
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                f"Nota: se muestran los primeros {max_rows} casos sensibles. Existen {remaining} registros adicionales.",
                styles["Italic"],
            )
        )

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    next_path = next if next.startswith("/") else "/"
    existing_user = _current_user_optional(request)
    if existing_user:
        return RedirectResponse(url=next_path or "/dashboard", status_code=303)
    response = templates.TemplateResponse("login.html", _template_context(request, next_url=next_path))
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    next_path = next if next.startswith("/") else "/"
    form_payload = {"username": username, "password": password}
    auth_url = AUTH_SERVICE_LOGIN_URL
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(auth_url, data=form_payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        error_message = "Credenciales inválidas o servicio de autenticación no disponible."
        if exc.response is not None and exc.response.status_code >= 500:
            error_message = "Auth service no responde. Intenta más tarde."
        return templates.TemplateResponse(
            "login.html",
            _template_context(request, next_url=next_path, error_message=error_message),
            status_code=400,
        )
    token_payload = response.json()
    context = _template_context(request, next_url=next_path, token_payload=token_payload)
    result = templates.TemplateResponse("login_success.html", context)
    result.set_cookie(
        AUTH_COOKIE_NAME,
        token_payload.get("access_token"),
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return result


@app.post("/logout", response_class=HTMLResponse)
async def logout(request: Request, next: str = Form("/")):
    next_path = next if next.startswith("/") else "/"
    result = templates.TemplateResponse("logout.html", _template_context(request, next_url=next_path))
    result.delete_cookie(AUTH_COOKIE_NAME)
    return result


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    if _current_user_optional(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("register.html", _template_context(request))


@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
):
    if _current_user_optional(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    payload = {
        "username": username,
        "password": password,
        "full_name": full_name,
        "email": email,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{AUTH_SERVICE_INTERNAL_URL.rstrip('/')}/auth/self-register",
                json=payload,
            )
    except httpx.HTTPError:
        return templates.TemplateResponse(
            "register.html",
            _template_context(request, error_message="No fue posible registrar el usuario. Intenta más tarde."),
            status_code=502,
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text or "Solicitud inválida"
        return templates.TemplateResponse(
            "register.html",
            _template_context(request, error_message=detail),
            status_code=response.status_code,
        )
    data = response.json()
    context = _template_context(request, new_username=data.get("username"))
    return templates.TemplateResponse("register_success.html", context)


@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    """Landing page with navigation links to the main experiences."""
    current_user = _ensure_ui_permissions(request, ["report"])
    if not current_user:
        return _login_redirect(request)
    return templates.TemplateResponse("home.html", _template_context(request, current_user=current_user))


@app.get("/reports", response_class=HTMLResponse)
async def read_reports(request: Request):
    """List the available PDF reports."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    return templates.TemplateResponse("reports.html", _template_context(request))


@app.get("/report", response_class=HTMLResponse)
async def read_report(request: Request):
    """Serve the interactive form to submit new lost-person reports."""
    if not _ensure_ui_permissions(request, ["report"]):
        return _login_redirect(request)
    return templates.TemplateResponse(
        "tester.html",
        _template_context(request, producer_endpoint=PRODUCER_PUBLIC_URL),
    )


@app.get("/cases", response_class=HTMLResponse)
async def manage_cases(request: Request):
    """UI for case management operations."""
    if not _ensure_ui_permissions(request, ["case_manager"]):
        return _login_redirect(request)
    return templates.TemplateResponse("cases.html", _template_context(request))


@app.get("/case-responsibles/catalog")
def case_responsible_catalog(
    request: Request,
    _: TokenPayload = Depends(require_case_permission),
):
    data = _case_manager_get(
        "/responsibles/catalog",
        auth_header=_proxy_auth_header(request),
    )
    return {"items": data or []}


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    token = _proxy_auth_header(request)
    data = _auth_service_request("GET", "/auth/users", token=token)
    return templates.TemplateResponse(
        "admin_users.html",
        _template_context(request, users=data or [], current_user=current_user),
    )


@app.get("/admin/users/create", response_class=HTMLResponse)
async def admin_create_user_form(request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    return templates.TemplateResponse(
        "admin_user_form.html",
        _template_context(
            request,
            user=None,
            form_mode="create",
            title="Crear nuevo usuario",
            subtitle="Completa los campos requeridos",
            submit_label="Crear",
        ),
    )


@app.post("/admin/users/create", response_class=HTMLResponse)
async def admin_create_user_submit(request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    form = await request.form()
    roles = form.getlist("roles") or ["member"]
    payload = {
        "username": form.get("username"),
        "full_name": form.get("full_name"),
        "email": form.get("email"),
        "password": form.get("password"),
        "roles": roles,
    }
    token = _proxy_auth_header(request)
    try:
        _auth_service_request("POST", "/auth/register", token=token, payload=payload)
        return RedirectResponse(url="/admin/users", status_code=303)
    except HTTPException as exc:
        return templates.TemplateResponse(
            "admin_user_form.html",
            _template_context(
                request,
                user=payload,
                form_mode="create",
                title="Crear nuevo usuario",
                subtitle="Completa los campos requeridos",
                submit_label="Crear",
                error_message=exc.detail,
            ),
            status_code=exc.status_code,
        )


@app.get("/admin/users/{username}/edit", response_class=HTMLResponse)
async def admin_edit_user_form(username: str, request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    token = _proxy_auth_header(request)
    user = _auth_service_request("GET", f"/auth/users/{username}", token=token)
    return templates.TemplateResponse(
        "admin_user_form.html",
        _template_context(
            request,
            user=user,
            form_mode="edit",
            title=f"Editar usuario {username}",
            subtitle="Actualiza los datos necesarios",
            submit_label="Guardar",
        ),
    )


@app.post("/admin/users/{username}/edit", response_class=HTMLResponse)
async def admin_edit_user_submit(username: str, request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    form = await request.form()
    roles = form.getlist("roles") or None
    payload = {
        "full_name": form.get("full_name"),
        "email": form.get("email"),
        "is_active": form.get("is_active") == "on",
    }
    password = form.get("password")
    if password:
        payload["password"] = password
    if roles is not None:
        payload["roles"] = roles or ["member"]
    token = _proxy_auth_header(request)
    try:
        _auth_service_request("PATCH", f"/auth/users/{username}", token=token, payload=payload)
        return RedirectResponse(url="/admin/users", status_code=303)
    except HTTPException as exc:
        current_data = _auth_service_request("GET", f"/auth/users/{username}", token=token)
        return templates.TemplateResponse(
            "admin_user_form.html",
            _template_context(
                request,
                user=current_data,
                form_mode="edit",
                title=f"Editar usuario {username}",
                subtitle="Actualiza los datos necesarios",
                submit_label="Guardar",
                error_message=exc.detail,
            ),
            status_code=exc.status_code,
        )


@app.post("/admin/users/{username}/delete")
async def admin_user_toggle(username: str, request: Request):
    current_user = _ensure_ui_permissions(request, ["manage_users"])
    if not current_user:
        return _login_redirect(request)
    token = _proxy_auth_header(request)
    user = _auth_service_request("GET", f"/auth/users/{username}", token=token)
    payload = {"is_active": not user.get("is_active", True)}
    _auth_service_request("PATCH", f"/auth/users/{username}", token=token, payload=payload)
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/cases/{case_id}/report")
def case_pdf_report(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    case = db.query(Case).filter(Case.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    person = case.person
    person_name = f"{person.first_name} {person.last_name}".strip() if person else "Sin registrar"
    gender_map = {"M": "Masculino", "F": "Femenino", "O": "Otro"}
    gender_label = gender_map.get(getattr(person, "gender", None), getattr(person, "gender", "Desconocido"))

    auth_header = _proxy_auth_header(request)
    actions = _case_manager_get(f"/cases/{case_id}/actions", auth_header=auth_header)
    if actions is None:
        actions = [
            {
                "action_type": action.action_type,
                "notes": action.notes,
                "actor": action.actor,
                "created_at": action.created_at.isoformat(),
            }
            for action in case.actions
        ]
    responsibles = _case_manager_get(
        f"/cases/{case_id}/responsibles",
        auth_header=auth_header,
    )
    if responsibles is None:
        responsibles = [
            {
                "responsible_name": entry.responsible_name,
                "assigned_by": entry.assigned_by,
                "notes": entry.notes,
                "assigned_at": entry.assigned_at.isoformat(),
            }
            for entry in case.responsibles
        ]

    buffer = BytesIO()
    title = f"Reporte del caso #{case.case_id}"
    doc, add_page_number = _create_pdf_doc(buffer, orientation="portrait", title=title)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Heading1"]),
        Spacer(1, 12),
    ]

    table_body_style = ParagraphStyle(
        "CaseTableBody",
        parent=styles["BodyText"],
        fontSize=10,
        leading=12,
        spaceAfter=0,
    )
    table_header_style = ParagraphStyle(
        "CaseTableHeader",
        parent=styles["Heading4"],
        fontSize=10,
        leading=12,
        textColor=colors.black,
        spaceAfter=0,
    )

    def _table_cell(value: Optional[str], header: bool = False) -> Paragraph:
        text = value if value not in (None, "") else "-"
        return Paragraph(escape(str(text)), table_header_style if header else table_body_style)

    case_rows = [
        [_table_cell("ID de caso", header=True), _table_cell(f"#{case.case_id}")],
        [_table_cell("Persona", header=True), _table_cell(person_name)],
        [_table_cell("Género", header=True), _table_cell(gender_label)],
        [_table_cell("Edad", header=True), _table_cell(getattr(person, "age", None) or "Sin registro")],
        [_table_cell("Estado", header=True), _table_cell(CASE_STATUS_LABELS.get(case.status.value, case.status.value))],
        [_table_cell("Prioridad", header=True), _table_cell(PRIORITY_LABELS.get(case.priority, case.priority or "Sin prioridad"))],
        [_table_cell("¿Prioritario?", header=True), _table_cell("Sí" if case.is_priority else "No")],
        [_table_cell("Reportado", header=True), _table_cell(_format_datetime(case.reported_at))],
        [_table_cell("Resuelto", header=True), _table_cell(_format_datetime(case.resolved_at))],
        [_table_cell("Resumen de resolución", header=True), _table_cell(case.resolution_summary or "Sin resumen")],
        [_table_cell("Ubicación reportada", header=True), _table_cell(getattr(person, "lost_location", None) or "Sin registro")],
        [_table_cell("Detalles del reporte", header=True), _table_cell(getattr(person, "details", None) or "Sin detalles")],
    ]
    case_table = Table(case_rows, colWidths=[170, 360])
    case_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#94a3b8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), None),
            ]
        )
    )
    story.append(case_table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Historial de responsables", styles["Heading2"]))
    responsibles_rows = [[
        _table_cell("Fecha", header=True),
        _table_cell("Responsable", header=True),
        _table_cell("Notas", header=True),
        _table_cell("Asignado por", header=True),
    ]]
    for entry in responsibles:
        assigned_at = entry.get("assigned_at")
        assigned_ts = "-"
        if assigned_at:
            try:
                assigned_ts = _format_datetime(datetime.fromisoformat(assigned_at))
            except ValueError:
                assigned_ts = assigned_at
        responsibles_rows.append(
            [
                _table_cell(assigned_ts),
                _table_cell(entry.get("responsible_name") or "Sin nombre"),
                _table_cell(entry.get("notes") or "Sin notas"),
                _table_cell(entry.get("assigned_by") or "N/A"),
            ]
        )
    responsibles_table = Table(responsibles_rows, colWidths=[110, 160, 200, 80])
    responsibles_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d223d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#94a3b8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), None),
            ]
        )
    )
    story.append(responsibles_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Historial de acciones", styles["Heading2"]))
    actions_rows = [[
        _table_cell("Fecha", header=True),
        _table_cell("Tipo", header=True),
        _table_cell("Notas", header=True),
        _table_cell("Responsable", header=True),
    ]]
    for action in actions:
        label = next(
            (item["label"] for item in CASE_ACTION_TYPES if item["value"] == action.get("action_type")),
            action.get("action_type", ""),
        )
        created_at = action.get("created_at")
        action_date = "-"
        if created_at:
            try:
                action_date = _format_datetime(datetime.fromisoformat(created_at))
            except ValueError:
                action_date = created_at
        actions_rows.append(
            [
                _table_cell(action_date),
                _table_cell(label),
                _table_cell(action.get("notes") or "Sin notas"),
                _table_cell(action.get("responsible_name") or "Sin asignar"),
            ]
        )
    actions_table = Table(actions_rows, colWidths=[110, 110, 200, 110])
    actions_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d223d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#94a3b8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), None),
            ]
        )
    )
    story.append(actions_table)

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    filename = f"case_{case.case_id}_report.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ws_manager.disconnect(websocket)


@app.get("/reports/operational-alerts", response_class=HTMLResponse)
async def read_operational_alerts_form(request: Request):
    """Render the filters for the operational alerts report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=7)
    return _render_operational_alerts_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="portrait",
    )


@app.post("/reports/operational-alerts")
async def generate_operational_alerts_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("portrait"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for operational alerts within the selected window."""
    orientation = (orientation or "portrait").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_operational_alerts_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="portrait",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_operational_alerts_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_operational_alerts_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_operational_alerts_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    records = [
        {
            "person_id": person.person_id,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "gender": person.gender,
            "age": person.age,
            "lost_location": person.lost_location,
            "lost_timestamp": person.lost_timestamp,
            "details": person.details,
        }
        for person in (
            db.query(PersonLost)
            .filter(PersonLost.status == "active")
            .filter(PersonLost.lost_timestamp >= start_datetime)
            .filter(PersonLost.lost_timestamp <= end_datetime)
            .filter(hour_expr >= start_hour)
            .filter(hour_expr <= end_hour)
            .order_by(PersonLost.lost_timestamp.desc())
            .all()
        )
    ]

    pdf_buffer = _build_operational_alerts_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_alertas_operativas_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/reports/demographic-distribution", response_class=HTMLResponse)
async def read_demographic_distribution_form(request: Request):
    """Render the filters for the demographic distribution report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=30)
    return _render_demographic_distribution_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="portrait",
    )


@app.post("/reports/demographic-distribution")
async def generate_demographic_distribution_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("portrait"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for demographic distribution in the selected window."""
    orientation = (orientation or "portrait").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_demographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="portrait",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_demographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_demographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_demographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    query = (
        db.query(
            PersonLost.person_id,
            PersonLost.age,
            PersonLost.gender,
            PersonLost.lost_timestamp,
        )
        .filter(PersonLost.status == "active")
        .filter(PersonLost.lost_timestamp >= start_datetime)
        .filter(PersonLost.lost_timestamp <= end_datetime)
        .filter(hour_expr >= start_hour)
        .filter(hour_expr <= end_hour)
    )
    records = [
        {
            "person_id": row.person_id,
            "age": row.age,
            "gender": row.gender,
            "lost_timestamp": row.lost_timestamp,
        }
        for row in query.all()
    ]

    pdf_buffer = _build_demographic_distribution_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_distribucion_demografica_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/reports/geographic-distribution", response_class=HTMLResponse)
async def read_geographic_distribution_form(request: Request):
    """Render the filters for the geographic distribution report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=30)
    return _render_geographic_distribution_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="landscape",
    )


@app.post("/reports/geographic-distribution")
async def generate_geographic_distribution_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("landscape"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for geographic distribution in the selected window."""
    orientation = (orientation or "landscape").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_geographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="landscape",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_geographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_geographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_geographic_distribution_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    records = [
        {
            "person_id": row.person_id,
            "lost_location": row.lost_location,
            "lost_timestamp": row.lost_timestamp,
        }
        for row in (
            db.query(
                PersonLost.person_id,
                PersonLost.lost_location,
                PersonLost.lost_timestamp,
            )
            .filter(PersonLost.status == "active")
            .filter(PersonLost.lost_timestamp >= start_datetime)
            .filter(PersonLost.lost_timestamp <= end_datetime)
            .filter(hour_expr >= start_hour)
            .filter(hour_expr <= end_hour)
            .all()
        )
    ]

    pdf_buffer = _build_geographic_distribution_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_mapa_ubicaciones_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/reports/hourly-analysis", response_class=HTMLResponse)
async def read_hourly_analysis_form(request: Request):
    """Render the filters for the hourly analysis report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=14)
    return _render_hourly_analysis_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="landscape",
    )


@app.post("/reports/hourly-analysis")
async def generate_hourly_analysis_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("landscape"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for hourly analysis in the selected window."""
    orientation = (orientation or "landscape").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_hourly_analysis_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="landscape",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_hourly_analysis_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_hourly_analysis_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_hourly_analysis_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    records = [
        {
            "person_id": row.person_id,
            "lost_timestamp": row.lost_timestamp,
        }
        for row in (
            db.query(
                PersonLost.person_id,
                PersonLost.lost_timestamp,
            )
            .filter(PersonLost.status == "active")
            .filter(PersonLost.lost_timestamp >= start_datetime)
            .filter(PersonLost.lost_timestamp <= end_datetime)
            .filter(hour_expr >= start_hour)
            .filter(hour_expr <= end_hour)
            .all()
        )
    ]

    pdf_buffer = _build_hourly_analysis_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_analisis_horario_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/reports/executive-summary", response_class=HTMLResponse)
async def read_executive_summary_form(request: Request):
    """Render the filters for the executive summary report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=14)
    return _render_executive_summary_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="landscape",
    )


@app.post("/reports/executive-summary")
async def generate_executive_summary_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("landscape"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for the executive summary in the selected window."""
    orientation = (orientation or "landscape").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_executive_summary_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="landscape",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_executive_summary_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_executive_summary_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_executive_summary_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    records = [
        {
            "person_id": row.person_id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "gender": row.gender,
            "age": row.age,
            "lost_location": row.lost_location,
            "lost_timestamp": row.lost_timestamp,
            "details": row.details,
        }
        for row in (
            db.query(
                PersonLost.person_id,
                PersonLost.first_name,
                PersonLost.last_name,
                PersonLost.gender,
                PersonLost.age,
                PersonLost.lost_location,
                PersonLost.lost_timestamp,
                PersonLost.details,
            )
            .filter(PersonLost.status == "active")
            .filter(PersonLost.lost_timestamp >= start_datetime)
            .filter(PersonLost.lost_timestamp <= end_datetime)
            .filter(hour_expr >= start_hour)
            .filter(hour_expr <= end_hour)
            .all()
        )
    ]

    pdf_buffer = _build_executive_summary_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_resumen_ejecutivo_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/reports/sensitive-cases", response_class=HTMLResponse)
async def read_sensitive_cases_form(request: Request):
    """Render the filters for the sensitive cases report."""
    if not _ensure_ui_permissions(request, ["pdf_reports"]):
        return _login_redirect(request)
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=14)
    return _render_sensitive_cases_form(
        request=request,
        start_date=default_start,
        end_date=today,
        start_hour=0,
        end_hour=23,
        orientation="landscape",
    )


@app.post("/reports/sensitive-cases")
async def generate_sensitive_cases_report(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    orientation: str = Form("landscape"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_pdf_permission),
):
    """Generate the PDF for sensitive cases within the selected window."""
    orientation = (orientation or "landscape").lower()
    if orientation not in {"portrait", "landscape"}:
        return _render_sensitive_cases_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation="landscape",
            error_message="Selecciona una orientacion de pagina valida (portrait o landscape).",
        )
    if end_date < start_date:
        return _render_sensitive_cases_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La fecha final debe ser mayor o igual a la inicial.",
        )
    if start_hour > end_hour:
        return _render_sensitive_cases_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="La hora final debe ser mayor o igual a la inicial.",
        )
    if start_hour < 0 or end_hour > 23:
        return _render_sensitive_cases_form(
            request,
            start_date=start_date,
            end_date=end_date,
            start_hour=start_hour,
            end_hour=end_hour,
            orientation=orientation,
            error_message="Las horas deben estar entre 00 y 23.",
        )

    start_datetime = datetime.combine(start_date, time(hour=0, minute=0, second=0))
    end_datetime = datetime.combine(end_date, time(hour=23, minute=59, second=59))
    hour_expr = func.hour(PersonLost.lost_timestamp)

    records = [
        {
            "person_id": row.person_id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "gender": row.gender,
            "age": row.age,
            "lost_location": row.lost_location,
            "lost_timestamp": row.lost_timestamp,
            "details": row.details,
        }
        for row in (
            db.query(
                PersonLost.person_id,
                PersonLost.first_name,
                PersonLost.last_name,
                PersonLost.gender,
                PersonLost.age,
                PersonLost.lost_location,
                PersonLost.lost_timestamp,
                PersonLost.details,
            )
            .filter(PersonLost.status == "active")
            .filter(PersonLost.lost_timestamp >= start_datetime)
            .filter(PersonLost.lost_timestamp <= end_datetime)
            .filter(hour_expr >= start_hour)
            .filter(hour_expr <= end_hour)
            .all()
        )
    ]

    pdf_buffer = _build_sensitive_cases_pdf(
        records,
        start_date=start_date,
        end_date=end_date,
        start_hour=start_hour,
        end_hour=end_hour,
        orientation=orientation,
    )
    filename = f"reporte_casos_sensibles_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    headers = {"Content-Disposition": f'attachment; filename=\"{filename}\"'}
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers=headers)


@app.get("/tester")
async def legacy_tester_redirect():
    """Backwards compatibility for the legacy /tester route."""
    return RedirectResponse(url="/report", status_code=307)


@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """Serve the live analytics dashboard."""
    if not _ensure_ui_permissions(request, ["dashboard"]):
        return _login_redirect(request)
    return templates.TemplateResponse("index.html", _template_context(request))


def _fallback_age_stats(db: Session):
    age_group_case = case(
        (PersonLost.age.is_(None), "Unknown"),
        (PersonLost.age < 0, "Unknown"),
        (PersonLost.age <= 12, "0-12"),
        (PersonLost.age <= 17, "13-17"),
        (PersonLost.age <= 25, "18-25"),
        (PersonLost.age <= 40, "26-40"),
        (PersonLost.age <= 60, "41-60"),
        else_="61+",
    )
    rows = (
        db.query(
            age_group_case.label("age_group"),
            func.count(PersonLost.person_id).label("count"),
        )
        .group_by(age_group_case)
        .all()
    )
    return [{"label": row.age_group or "Unknown", "value": row.count} for row in rows]


def _fallback_gender_stats(db: Session):
    rows = (
        db.query(
            PersonLost.gender.label("gender"),
            func.count(PersonLost.person_id).label("count"),
        )
        .group_by(PersonLost.gender)
        .all()
    )
    return [
        {"label": row.gender or "Unknown", "value": row.count}
        for row in rows
    ]


def _fallback_hourly_stats(db: Session):
    hour_expr = func.hour(PersonLost.lost_timestamp)
    rows = (
        db.query(
            hour_expr.label("hour_of_day"),
            func.count(PersonLost.person_id).label("count"),
        )
        .group_by(hour_expr)
        .order_by(hour_expr)
        .all()
    )
    return [
        {
            "label": f"{int(row.hour_of_day):02d}:00" if row.hour_of_day is not None else "Unknown",
            "value": row.count,
        }
        for row in rows
    ]


@app.get("/stats/age")
def get_age_stats(
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_dashboard_permission),
):
    """Return counts by age group."""
    stats = db.query(AggAgeGroup).all()
    if stats:
        return {"data": [{"label": s.age_group, "value": s.count} for s in stats]}
    return {"data": _fallback_age_stats(db)}


@app.get("/stats/gender")
def get_gender_stats(
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_dashboard_permission),
):
    """Return counts by gender."""
    stats = db.query(AggGender).all()
    if stats:
        return {"data": [{"label": s.gender, "value": s.count} for s in stats]}
    return {"data": _fallback_gender_stats(db)}


@app.get("/stats/hourly")
def get_hourly_stats(
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_dashboard_permission),
):
    """Return counts by hour of the day."""
    stats = db.query(AggHourly).order_by(AggHourly.hour_of_day).all()
    if stats:
        return {"data": [{"label": f"{s.hour_of_day}:00", "value": s.count} for s in stats]}
    return {"data": _fallback_hourly_stats(db)}


def _case_summary_stats(db: Session, auth_header: Optional[str]) -> dict:
    data = _case_manager_get("/cases/stats/summary", auth_header=auth_header)
    if data:
        return data
    # fallback local computation
    counts = dict(
        db.query(Case.status, func.count(Case.case_id)).group_by(Case.status).all()
    )
    new_cases = int(counts.get(CaseStatusEnum.NEW, 0))
    in_progress_cases = int(counts.get(CaseStatusEnum.IN_PROGRESS, 0))
    resolved_cases = int(counts.get(CaseStatusEnum.RESOLVED, 0))
    cancelled_cases = int(counts.get(CaseStatusEnum.CANCELLED, 0))
    archived_cases = int(counts.get(CaseStatusEnum.ARCHIVED, 0))
    total_cases = new_cases + in_progress_cases + resolved_cases + cancelled_cases + archived_cases
    avg_seconds = (
        db.query(
            func.avg(
                func.timestampdiff(text("SECOND"), Case.reported_at, Case.resolved_at)
            )
        )
        .filter(Case.status == CaseStatusEnum.RESOLVED)
        .filter(Case.resolved_at.isnot(None))
        .scalar()
    )
    avg_hours = round(float(avg_seconds) / 3600, 2) if avg_seconds else None
    return {
        "total_cases": total_cases,
        "new_cases": new_cases,
        "in_progress_cases": in_progress_cases,
        "resolved_cases": resolved_cases,
        "cancelled_cases": cancelled_cases,
        "archived_cases": archived_cases,
        "average_response_hours": avg_hours,
    }


def _case_time_series(db: Session, days: int, auth_header: Optional[str]) -> list[dict]:
    range_param = "24h" if days == 1 else "7d" if days == 7 else "30d"
    data = _case_manager_get(
        "/cases/stats/time-series",
        params={"range": range_param},
        auth_header=auth_header,
    )
    if data and "points" in data:
        return data["points"]
    # fallback computation
    start_date = datetime.utcnow() - timedelta(days=days)
    reported = (
        db.query(func.date(Case.reported_at).label("day"), func.count(Case.case_id))
        .filter(Case.reported_at >= start_date)
        .group_by(func.date(Case.reported_at))
        .order_by(func.date(Case.reported_at))
        .all()
    )
    resolved = (
        db.query(func.date(Case.resolved_at).label("day"), func.count(Case.case_id))
        .filter(Case.resolved_at.isnot(None))
        .filter(Case.resolved_at >= start_date)
        .filter(Case.status == CaseStatusEnum.RESOLVED)
        .group_by(func.date(Case.resolved_at))
        .order_by(func.date(Case.resolved_at))
        .all()
    )
    reported_lookup = {row[0]: row[1] for row in reported}
    resolved_lookup = {row[0]: row[1] for row in resolved}
    points: list[dict] = []
    current = start_date.date()
    today = datetime.utcnow().date()
    while current <= today:
        points.append(
            {
                "date": current.isoformat(),
                "reported": reported_lookup.get(current, 0),
                "resolved": resolved_lookup.get(current, 0),
            }
        )
        current += timedelta(days=1)
    return points


@app.get("/case-stats/summary")
def case_summary(
    request: Request,
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_dashboard_permission),
):
    return _case_summary_stats(db, _proxy_auth_header(request))


@app.get("/case-stats/time-series")
def case_time_series(
    request: Request,
    range: str = Query("7d", pattern="^(24h|7d|30d)$"),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_dashboard_permission),
):
    days = 1 if range == "24h" else 7 if range == "7d" else 30
    points = _case_time_series(db, days, _proxy_auth_header(request))
    return {"range": range, "points": points}


@app.get("/persons/options")
def person_options(
    include_assigned: bool = Query(False),
    db: Session = Depends(get_db),
    _: TokenPayload = Depends(require_case_permission),
):
    query = db.query(PersonLost.person_id, PersonLost.first_name, PersonLost.last_name)
    if not include_assigned:
        query = query.filter(PersonLost.case == None)
    items = (
        query.order_by(PersonLost.last_name.asc(), PersonLost.first_name.asc()).all()
    )
    data = [
        {
            "person_id": person.person_id,
            "label": f"{person.first_name} {person.last_name} (#{person.person_id})",
        }
        for person in items
    ]
    return {"items": data}
