import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from producer import models
from producer.database import get_db
from scripts.db_init import PersonLost, Case, CaseStatusEnum

DEFAULT_TIMEZONE = "America/Guayaquil"
_tz_name = os.getenv("REPORT_LOCAL_TZ", DEFAULT_TIMEZONE)
try:
    REPORT_TIMEZONE = ZoneInfo(_tz_name)
except ZoneInfoNotFoundError:
    REPORT_TIMEZONE = ZoneInfo("UTC")


def _local_now() -> datetime:
    # DB column is naive; store local system time without tz info
    return datetime.now(REPORT_TIMEZONE).replace(tzinfo=None)

app = FastAPI(title="Lost Persons Reporter API")

allowed_origins = [
    "http://localhost:58102",
    "http://127.0.0.1:58102",
    "http://localhost:58101",
    "http://127.0.0.1:58101",
    "http://localhost:40145",
    "http://127.0.0.1:40145",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/report_person/", response_model=models.ReportPersonPayload)
def report_person(payload: models.ReportPersonPayload, db: Session = Depends(get_db)):
    """
    Endpoint para reportar una persona como perdida.
    Los datos se validan con Pydantic y se guardan en MySQL usando SQLAlchemy.
    """
    # Calcular edad
    today = date.today()
    age = today.year - payload.birth_date.year - ((today.month, today.day) < (payload.birth_date.month, payload.birth_date.day))

    db_person = PersonLost(
        first_name=payload.first_name,
        last_name=payload.last_name,
        gender=payload.gender,
        birth_date=payload.birth_date,
        age=age,
        lost_timestamp=_local_now(),
        lost_location=payload.lost_location,
        details=payload.details,
        status='active'
    )
    
    try:
        db.add(db_person)
        db.flush()  # ensure person_id is available for the related case

        db_case = Case(
            person_id=db_person.person_id,
            status=CaseStatusEnum.NEW,
            reported_at=db_person.lost_timestamp,
            priority=None,
            is_priority=False,
        )
        db.add(db_case)

        db.commit()
        db.refresh(db_person)
        return db_person
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar en la base de datos: {e}")

@app.get("/report_person/", response_model=list[models.ReportPersonResponse])
def list_reports(
    limit: int = Query(10, ge=1, le=100, description="Número máximo de reportes recientes a devolver."),
    db: Session = Depends(get_db),
):
    """
    Devuelve una lista de reportes recientes para facilitar la verificación manual desde la UI.
    """
    reports = (
        db.query(PersonLost)
        .order_by(PersonLost.lost_timestamp.desc())
        .limit(limit)
        .all()
    )
    return reports

@app.get("/")
def read_root():
    return {"message": "Producer API is running. Use POST /report_person/ to submit data."}
