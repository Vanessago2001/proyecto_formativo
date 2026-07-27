from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Esquema para recibir credenciales de login vía JSON."""

    correo: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=100)


class CodigoRequest(BaseModel):
    correo: str = Field(..., min_length=3, max_length=255)
    codigo: str = Field(..., min_length=6, max_length=6)
