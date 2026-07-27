from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    correo: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class CodigoRequest(BaseModel):
    correo: str = Field(..., min_length=3)
    codigo: str = Field(..., min_length=6, max_length=6)