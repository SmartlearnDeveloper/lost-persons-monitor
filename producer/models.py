from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import Optional

class ReportPersonPayload(BaseModel):
    first_name: str
    last_name: str
    gender: str  # 'M', 'F', 'O'
    birth_date: date
    lost_location: Optional[str] = None
    details: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ReportPersonResponse(ReportPersonPayload):
    person_id: int
    age: Optional[int]
    lost_timestamp: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)
