from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class CaseStatus(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class CaseBase(BaseModel):
    person_id: int
    status: CaseStatus = CaseStatus.NEW
    priority: Optional[str] = None
    reported_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolution_summary: Optional[str] = Field(None, max_length=1000)
    is_priority: Optional[bool] = False


class CaseCreate(CaseBase):
    person_id: int


class CaseUpdate(BaseModel):
    status: Optional[CaseStatus] = None
    priority: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_summary: Optional[str] = Field(None, max_length=1000)
    is_priority: Optional[bool] = None


class CaseActionCreate(BaseModel):
    action_type: str = Field(..., max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)
    actor: Optional[str] = Field(None, max_length=200)
    metadata_json: Optional[str] = Field(None, max_length=2000)


class CaseAction(BaseModel):
    action_id: int
    case_id: int
    action_type: str
    notes: Optional[str]
    actor: Optional[str]
    metadata_json: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class Case(CaseBase):
    case_id: int
    created_at: datetime
    updated_at: datetime
    match_terms: Optional[List[str]] = None

    class Config:
        from_attributes = True


class CaseListResponse(BaseModel):
    items: List[Case]
    total: int


class CaseResponsibleBase(BaseModel):
    responsible_name: str = Field(..., max_length=200)
    assigned_by: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000)


class CaseResponsibleCreate(CaseResponsibleBase):
    pass


class CaseResponsible(CaseResponsibleBase):
    assignment_id: int
    case_id: int
    assigned_at: datetime

    class Config:
        from_attributes = True


class CaseSummary(BaseModel):
    total_cases: int
    new_cases: int
    in_progress_cases: int
    resolved_cases: int
    cancelled_cases: int
    archived_cases: int
    average_response_hours: Optional[float]


class TimeSeriesDataPoint(BaseModel):
    date: datetime
    reported: int
    resolved: int


class TimeSeriesResponse(BaseModel):
    range: str
    points: List[TimeSeriesDataPoint]
