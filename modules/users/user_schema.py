from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
  nombre: str = Field(..., min_length=4, max_length=50)
  correo: EmailStr


class UserCreate(UserBase):
  contrasena: str = Field(..., min_length=6, max_length=100)
  rol: int = Field(..., gt=0)


class UserResponse(UserBase):
  id: int
  estado: str
  rol: int

  model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
  correo: Optional[EmailStr] = None
  contrasena: Optional[str] = Field(None, min_length=6, max_length=100)
  rol: Optional[int] = Field(None, gt=0)
  estado: Optional[str] = None