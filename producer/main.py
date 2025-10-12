from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import date, datetime

from producer import models
from producer.database import get_db
from scripts.db_init import PersonLost

app = FastAPI(title="Lost Persons Reporter API")

allowed_origins = [
    "http://localhost:58102",
    "http://127.0.0.1:58102",
    "http://localhost:58101",
    "http://127.0.0.1:58101",
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
        lost_timestamp=datetime.utcnow(),
        lost_location=payload.lost_location,
        details=payload.details,
        status='active'
    )
    
    try:
        db.add(db_person)
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
