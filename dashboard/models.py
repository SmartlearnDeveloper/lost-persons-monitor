from pydantic import BaseModel
from typing import List

class StatItem(BaseModel):
    label: str
    value: int

class StatsResponse(BaseModel):
    data: List[StatItem]
