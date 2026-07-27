from pydantic import BaseModel, Field
from pydantic import BaseModel, EmailStr

class LoginRequest(BaseModel):
    """Esquema para recibir credenciales de login vía JSON."""

    correo: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=100)


class CodigoRequest(BaseModel):
<<<<<<< HEAD
    correo: str = Field(..., min_length=3, max_length=255)
    codigo: str = Field(..., min_length=6, max_length=6)




class CambiarPasswordRequest(BaseModel):
    password_actual: str = Field(..., min_length=8)
    password_nueva: str = Field(..., min_length=8)


class CambiarPasswordExpiradaRequest(BaseModel):
    correo: EmailStr
    password_actual: str
    password_nueva: str
=======
    correo: str = Field(..., min_length=3)
    codigo: str = Field(..., min_length=1, max_length=20)
>>>>>>> 7a57d0a0b84edb6fdae895569d1fb8bf0d01495d
