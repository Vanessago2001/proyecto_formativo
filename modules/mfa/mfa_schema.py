from pydantic import BaseModel, Field

# esta clase representa la solicitud para verificar el código MFA
class MFAVerifyRequest(BaseModel):
    codigo: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Código de verificación MFA"
    )
# esta clase representa la solicitud para verificar el código MFA al desactivar MFA
class MFADisableVerifyRequest(BaseModel):
    codigo: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Código para desactivar MFA"
    )