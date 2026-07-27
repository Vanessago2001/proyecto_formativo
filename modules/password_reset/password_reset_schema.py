from pydantic import BaseModel, EmailStr, Field, model_validator

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
    correo: EmailStr
    codigo: str = Field(
        ...,
        min_length=6,
        max_length=6
    )
    nueva_password: str = Field(
        ...,
        min_length=8
    )
    confirmar_password: str = Field(
        ...,
        min_length=8
    )

    @model_validator(mode="after")
    def validar_passwords(self):
        if self.nueva_password != self.confirmar_password:
            raise ValueError("Las contraseñas no coinciden.")
        return self