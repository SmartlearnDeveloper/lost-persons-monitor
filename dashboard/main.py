from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime

from dashboard.database import get_db
from scripts.db_init import AggAgeGroup, AggGender, AggHourly, PersonLost

app = FastAPI(title="Lost Persons Dashboard")
templates = Jinja2Templates(directory="dashboard/templates")

@app.get("/", response_class=HTMLResponse)
async def read_home(request: Request):
    """
    Página de inicio con enlaces al formulario y al dashboard.
    """
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "current_year": datetime.utcnow().year,
        },
    )

@app.get("/report", response_class=HTMLResponse)
async def read_report(request: Request):
    """
    Sirve una GUI mínima para enviar reportes de prueba al producer.
    """
    producer_endpoint = "http://localhost:58101/report_person/"
    return templates.TemplateResponse(
        "tester.html",
        {"request": request, "producer_endpoint": producer_endpoint},
    )

@app.get("/tester")
async def legacy_tester_redirect():
    """
    Compatibilidad con la ruta anterior /tester.
    """
    return RedirectResponse(url="/report", status_code=307)

@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """Sirve el dashboard principal en HTML."""
    return templates.TemplateResponse("index.html", {"request": request})

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
def get_age_stats(db: Session = Depends(get_db)):
    """Devuelve estadísticas por grupo de edad."""
    stats = db.query(AggAgeGroup).all()
    if stats:
        return {"data": [{"label": s.age_group, "value": s.count} for s in stats]}
    return {"data": _fallback_age_stats(db)}

@app.get("/stats/gender")
def get_gender_stats(db: Session = Depends(get_db)):
    """Devuelve estadísticas por género."""
    stats = db.query(AggGender).all()
    if stats:
        return {"data": [{"label": s.gender, "value": s.count} for s in stats]}
    return {"data": _fallback_gender_stats(db)}

@app.get("/stats/hourly")
def get_hourly_stats(db: Session = Depends(get_db)):
    """Devuelve estadísticas por hora del día."""
    stats = db.query(AggHourly).order_by(AggHourly.hour_of_day).all()
    if stats:
        return {"data": [{"label": f"{s.hour_of_day}:00", "value": s.count} for s in stats]}
    return {"data": _fallback_hourly_stats(db)}
