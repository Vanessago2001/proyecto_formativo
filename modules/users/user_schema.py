from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


class UserBase(BaseModel):
    nombre: str = Field(..., min_length=4, max_length=50)
    correo: EmailStr
    tipo_doc: str = Field(..., max_length=20)
    num_doc: str = Field(..., max_length=30)


class UserCreate(UserBase):
    contrasena: str = Field(..., min_length=6, max_length=100)
    rol: int = Field(..., gt=0)


class UserResponse(UserBase):
    id: UUID
    estado: Literal["Activo", "Inactivo", "Bloqueado"]
    rol_id: int
    # Estos campos pueden ser NULL en la base de datos
    tipo_doc: Optional[str] = None
    num_doc: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    @field_serializer("id")
    def serialize_id(self, value):
        """Convierte UUID a string para evitar errores de serialización"""
        return str(value) if value is not None else None


class UserUpdate(BaseModel):
    correo: Optional[EmailStr] = None
    contrasena: Optional[str] = Field(None, min_length=6, max_length=100)
    rol: Optional[int] = Field(None, gt=0)
    estado: Optional[Literal["Activo", "Inactivo", "Bloqueado"]] = None
    tipo_doc: Optional[str] = Field(None, max_length=20)
    num_doc: Optional[str] = Field(None, max_length=30)
