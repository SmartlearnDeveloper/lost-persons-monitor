from typing import List, Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6)
    email: Optional[str] = Field(None, max_length=150)
    full_name: Optional[str] = Field(None, max_length=150)
    roles: List[str] = []


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    permissions: List[str]
    username: str
    user_id: int


class UserRead(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str]
    email: Optional[str]
    permissions: List[str]

    class Config:
        from_attributes = True


class RoleAssignment(BaseModel):
    username: str
    roles: List[str]
