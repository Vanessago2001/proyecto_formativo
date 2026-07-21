from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional


class UserBase(BaseModel):
    username: str = Field(..., min_length=4, max_length=50)
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=100)
    role_id: int = Field(..., gt=0)

class UserResponse(UserBase):
    id: int
    is_active: bool
    role_id: int

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6, max_length=100)
    role_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

