from pydantic import BaseModel, EmailStr, Field


class PasswordResetRequest(BaseModel):
    correo: EmailStr = Field(
        ...,
        description="Correo del usuario"
    )


class PasswordResetVerify(BaseModel):
    correo: EmailStr

    codigo: str = Field(
        ...,
        min_length=6,
        max_length=6
    )


class PasswordResetConfirm(BaseModel):
    token: str

    nueva_password: str = Field(
        ...,
        min_length=8
    )