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
    # rol es el id_rol de la tabla `rol`, que es UUID. Se declara como UUID
    # y no como str para que Pydantic valide que sea uno de verdad; por el
    # cable viaja igual, como cadena.
    rol: UUID


class UserResponse(UserBase):
    # La columna de la base se llama id_usuario, pero hacia fuera el campo
    # se sigue llamando "id", que es lo que espera el frontend.
    # `alias` a secas cambiaria tambien la salida, porque FastAPI serializa
    # los response_model con by_alias=True; `validation_alias` solo afecta
    # a la entrada.
    id: UUID = Field(validation_alias="id_usuario")
    estado: Literal["Activo", "Inactivo", "Bloqueado"]
    rol_id: UUID
    rol_nombre: Optional[str] = None
    # Estos campos pueden ser NULL en la base de datos
    tipo_doc: Optional[str] = None
    num_doc: Optional[str] = None

    # populate_by_name deja que el modelo acepte tanto "id_usuario"
    # (el nombre real de la columna) como "id", para que una consulta
    # que use un alias no rompa la validacion de la respuesta.
    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        populate_by_name=True,
    )

    @field_serializer("id")
    def serialize_id(self, value):
        """Convierte UUID a string para evitar errores de serialización"""
        return str(value) if value is not None else None


class UserUpdate(BaseModel):
    correo: Optional[EmailStr] = None
    contrasena: Optional[str] = Field(None, min_length=6, max_length=100)
    rol: Optional[UUID] = None
    estado: Optional[Literal["Activo", "Inactivo", "Bloqueado"]] = None
    tipo_doc: Optional[str] = Field(None, max_length=20)
    num_doc: Optional[str] = Field(None, max_length=30)
