from __future__ import annotations
import json
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib import request as urllib_request, error as urllib_error

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from case_manager import crud, schemas
from case_manager.database import get_db
# Note: ORM models are imported indirectly through crud module

app = FastAPI(title="Lost Persons Case Manager")
DASHBOARD_REFRESH_URL = os.environ.get("DASHBOARD_REFRESH_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


def notify_dashboard_refresh(event: str, case_id: Optional[int] = None) -> None:
    if not DASHBOARD_REFRESH_URL:
        return
    payload = json.dumps({"event": event, "case_id": case_id}).encode("utf-8")
    req = urllib_request.Request(
        DASHBOARD_REFRESH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib_request.urlopen(req, timeout=2)
    except urllib_error.URLError:
        pass


@app.get("/")
def healthcheck():
    return {
        "message": "Case Manager API is running. See /docs for interactive specification.",
        "endpoints": [
            "/cases",
            "/cases/{case_id}",
            "/cases/{case_id}/actions",
            "/cases/stats/summary",
            "/cases/stats/time-series",
        ],
    }


@app.get("/cases", response_model=schemas.CaseListResponse)
def list_cases(
    status: Optional[schemas.CaseStatus] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    cases, total = crud.list_cases(
        db,
        status=status.value if status else None,
        search=search,
        skip=skip,
        limit=limit,
    )
    return schemas.CaseListResponse(items=cases, total=total)


@app.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: int, db: Session = Depends(get_db)):
    case = crud.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/cases", response_model=schemas.Case, status_code=201)
def create_case(payload: schemas.CaseCreate, db: Session = Depends(get_db)):
    case = crud.create_case(
        db,
        person_id=payload.person_id,
        status=payload.status.value,
        priority=payload.priority,
        reported_at=payload.reported_at,
        is_priority=payload.is_priority or False,
    )
    notify_dashboard_refresh("case_created", case.case_id)
    return case


@app.patch("/cases/{case_id}", response_model=schemas.Case)
def update_case(case_id: int, payload: schemas.CaseUpdate, db: Session = Depends(get_db)):
    case = crud.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case = crud.update_case(
        db,
        case=case,
        status=payload.status.value if payload.status else None,
        priority=payload.priority,
        resolved_at=payload.resolved_at,
        resolution_summary=payload.resolution_summary,
        is_priority=payload.is_priority,
    )
    notify_dashboard_refresh("case_updated", case.case_id)
    return case


@app.get("/cases/{case_id}/actions", response_model=list[schemas.CaseAction])
def list_actions(case_id: int, db: Session = Depends(get_db)):
    if not crud.get_case(db, case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    actions = crud.list_case_actions(db, case_id=case_id)
    return actions


@app.post("/cases/{case_id}/actions", response_model=schemas.CaseAction, status_code=201)
def create_action(case_id: int, payload: schemas.CaseActionCreate, db: Session = Depends(get_db)):
    case = crud.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    action = crud.create_case_action(
        db,
        case=case,
        action_type=payload.action_type,
        notes=payload.notes,
        actor=payload.actor,
        metadata_json=payload.metadata_json,
    )
    notify_dashboard_refresh("case_action_created", case.case_id)
    return action


@app.get("/cases/stats/summary", response_model=schemas.CaseSummary)
def summary_stats(db: Session = Depends(get_db)):
    data = crud.get_cases_summary(db)
    return schemas.CaseSummary(**data)


@app.get("/cases/stats/time-series", response_model=schemas.TimeSeriesResponse)
def time_series(range: str = Query("7d", pattern="^(24h|7d|30d)$"), db: Session = Depends(get_db)):
    if range == "24h":
        days = 1
    elif range == "7d":
        days = 7
    else:
        days = 30
    points = crud.get_time_series(db, days=days)
    return schemas.TimeSeriesResponse(
        range=range,
        points=[
            schemas.TimeSeriesDataPoint(
                date=datetime.combine(item["date"], datetime.min.time()),
                reported=item["reported"],
                resolved=item["resolved"],
            )
            for item in points
        ],
    )
