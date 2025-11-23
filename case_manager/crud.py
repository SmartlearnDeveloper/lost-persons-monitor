from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import Session

from scripts.db_init import Case, CaseAction, CaseStatusEnum, CaseResponsibleHistory, PersonLost, ResponsibleContact


PENDING_STATUSES = {CaseStatusEnum.NEW, CaseStatusEnum.IN_PROGRESS}
RESOLVED_STATUSES = {CaseStatusEnum.RESOLVED}


def get_case(db: Session, case_id: int) -> Optional[Case]:
    return db.query(Case).filter(Case.case_id == case_id).first()


def get_case_by_person(db: Session, person_id: int) -> Optional[Case]:
    return db.query(Case).filter(Case.person_id == person_id).first()


def list_cases(
    db: Session,
    *,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[Case], int]:
    query = db.query(Case).join(PersonLost)
    if status:
        try:
            enum_status = CaseStatusEnum(status)
            query = query.filter(Case.status == enum_status)
        except ValueError:
            query = query.filter(False)  # invalid status yields empty result
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(PersonLost.first_name).like(pattern),
                func.lower(PersonLost.last_name).like(pattern),
                func.lower(PersonLost.lost_location).like(pattern),
            )
        )
    total = query.count()
    results = query.order_by(Case.created_at.desc()).offset(skip).limit(limit).all()
    return results, total


def create_case(db: Session, *, person_id: int, status: str, priority: Optional[str], reported_at: Optional[datetime], is_priority: bool) -> Case:
    existing = get_case_by_person(db, person_id)
    if existing:
        kwargs = {}
        if status:
            kwargs["status"] = status
        if priority is not None:
            kwargs["priority"] = priority
        if is_priority is not None:
            kwargs["is_priority"] = is_priority
        case = update_case(db, case=existing, **kwargs)
        if reported_at and existing.reported_at is None:
            existing.reported_at = reported_at
            db.add(existing)
            db.commit()
            db.refresh(existing)
            case = existing
        return case
    try:
        status_enum = CaseStatusEnum(status)
    except ValueError:
        status_enum = CaseStatusEnum.NEW
    case = Case(
        person_id=person_id,
        status=status_enum,
        priority=priority,
        reported_at=reported_at or datetime.utcnow(),
        is_priority=is_priority,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def update_case(
    db: Session,
    *,
    case: Case,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    resolved_at: Optional[datetime] = None,
    resolution_summary: Optional[str] = None,
    is_priority: Optional[bool] = None,
) -> Case:
    new_status_enum: Optional[CaseStatusEnum] = None
    if status:
        try:
            new_status_enum = CaseStatusEnum(status)
            case.status = new_status_enum
        except ValueError:
            new_status_enum = None
    if priority is not None:
        case.priority = priority
    if resolved_at is not None:
        case.resolved_at = resolved_at
    elif new_status_enum == CaseStatusEnum.RESOLVED and case.resolved_at is None:
        case.resolved_at = datetime.utcnow()
    if resolution_summary is not None:
        case.resolution_summary = resolution_summary
    if is_priority is not None:
        case.is_priority = is_priority
    case.updated_at = datetime.utcnow()
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def create_case_action(
    db: Session,
    *,
    case: Case,
    action_type: str,
    notes: Optional[str],
    actor: Optional[str],
    metadata_json: Optional[str],
) -> CaseAction:
    action = CaseAction(
        case_id=case.case_id,
        action_type=action_type,
        notes=notes,
        actor=actor,
        metadata_json=metadata_json,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def list_case_responsibles(db: Session, *, case_id: int) -> List[CaseResponsibleHistory]:
    return (
        db.query(CaseResponsibleHistory)
        .filter(CaseResponsibleHistory.case_id == case_id)
        .order_by(CaseResponsibleHistory.assigned_at.desc())
        .all()
    )


def create_case_responsible(
    db: Session,
    *,
    case: Case,
    responsible_name: str,
    assigned_by: Optional[str],
    notes: Optional[str],
) -> CaseResponsibleHistory:
    entry = CaseResponsibleHistory(
        case_id=case.case_id,
        responsible_name=responsible_name,
        assigned_by=assigned_by,
        notes=notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_responsible_contacts(db: Session) -> List[ResponsibleContact]:
    return (
        db.query(ResponsibleContact)
        .order_by(ResponsibleContact.role.asc(), ResponsibleContact.full_name.asc())
        .all()
    )


def list_case_actions(db: Session, *, case_id: int) -> List[CaseAction]:
    return (
        db.query(CaseAction)
        .filter(CaseAction.case_id == case_id)
        .order_by(CaseAction.created_at.desc())
        .all()
    )


def get_cases_summary(db: Session) -> dict:
    counts = dict(
        db.query(Case.status, func.count(Case.case_id)).group_by(Case.status).all()
    )
    new_count = int(counts.get(CaseStatusEnum.NEW, 0))
    in_progress_count = int(counts.get(CaseStatusEnum.IN_PROGRESS, 0))
    resolved_count = int(counts.get(CaseStatusEnum.RESOLVED, 0))
    cancelled_count = int(counts.get(CaseStatusEnum.CANCELLED, 0))
    archived_count = int(counts.get(CaseStatusEnum.ARCHIVED, 0))
    total_cases = new_count + in_progress_count + resolved_count + cancelled_count + archived_count

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
        "new_cases": new_count,
        "in_progress_cases": in_progress_count,
        "resolved_cases": resolved_count,
        "cancelled_cases": cancelled_count,
        "archived_cases": archived_count,
        "average_response_hours": avg_hours,
    }


def get_time_series(db: Session, *, days: int) -> List[dict]:
    start_date = datetime.utcnow() - timedelta(days=days)
    reported_data = (
        db.query(func.date(Case.reported_at).label("day"), func.count(Case.case_id))
        .filter(Case.reported_at >= start_date)
        .group_by(func.date(Case.reported_at))
        .order_by(func.date(Case.reported_at))
        .all()
    )
    resolved_data = (
        db.query(func.date(Case.resolved_at).label("day"), func.count(Case.case_id))
        .filter(Case.resolved_at.isnot(None))
        .filter(Case.resolved_at >= start_date)
        .filter(Case.status == CaseStatusEnum.RESOLVED)
        .group_by(func.date(Case.resolved_at))
        .order_by(func.date(Case.resolved_at))
        .all()
    )

    reported_lookup = {row[0]: row[1] for row in reported_data}
    resolved_lookup = {row[0]: row[1] for row in resolved_data}

    points = []
    current = start_date.date()
    today = datetime.utcnow().date()
    while current <= today:
        points.append(
            {
                "date": current,
                "reported": reported_lookup.get(current, 0),
                "resolved": resolved_lookup.get(current, 0),
            }
        )
        current += timedelta(days=1)
    return points
