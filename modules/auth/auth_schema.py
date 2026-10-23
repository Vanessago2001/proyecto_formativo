from pydantic import BaseModel, Field
from pydantic import BaseModel, EmailStr

class LoginRequest(BaseModel):
    """Esquema para recibir credenciales de login vía JSON."""

    correo: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=100)


class CodigoRequest(BaseModel):
    correo: str = Field(..., min_length=3, max_length=255)
    codigo: str = Field(..., min_length=6, max_length=6)


class CambiarPasswordRequest(BaseModel):
    password_actual: str = Field(..., min_length=8)
    password_nueva: str = Field(..., min_length=8)


class CambiarPasswordExpiradaRequest(BaseModel):
    correo: EmailStr
    password_actual: str
    password_nueva: str


class ResetPasswordRequest(BaseModel):
    """Esquema para restablecer la contraseña usando el token enviado al correo."""

    token: str = Field(..., min_length=10)
    nueva_password: str = Field(..., min_length=8, max_length=100)


class ForgotPasswordRequest(BaseModel):
    """Esquema para solicitar el enlace de restablecimiento (¿olvidó su contraseña?)."""

    correo: str = Field(..., min_length=3, max_length=255)

# nuevo Sneider
class LoginMFARequest(BaseModel):
    """Solicitud para finalizar el inicio de sesión mediante MFA."""

    correo: str = Field(..., min_length=3, max_length=255)
    codigo: str = Field(..., min_length=6, max_length=6)
