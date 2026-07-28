from pydantic import BaseModel, EmailStr, Field


class PasswordResetRequest(BaseModel):
    correo: EmailStr = Field(
        ...,
        description="Correo electrónico del usuario",
    )


class PasswordResetVerify(BaseModel):
    correo: EmailStr = Field(
        ...,
        description="Correo electrónico del usuario",
    )

    codigo: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Código de verificación de 6 dígitos",
    )


class PasswordResetConfirm(BaseModel):
    token: str = Field(
        ...,
        description="Token de recuperación",
    )

    nueva_password: str = Field(
        ...,
        min_length=8,
        description="Nueva contraseña del usuario",
    )