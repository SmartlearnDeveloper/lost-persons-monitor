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
    roles: List[str] = []
    is_active: bool = True

    class Config:
        from_attributes = True


class RoleAssignment(BaseModel):
    username: str
    roles: List[str]


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=150)
    email: Optional[str] = Field(None, max_length=150)
    password: Optional[str] = Field(None, min_length=6)
    roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class SelfRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=6)
    email: Optional[str] = Field(None, max_length=150)
    full_name: Optional[str] = Field(None, max_length=150)
