from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CambioEstadoAuditor(BaseModel):
    """Solicitud para activar o inactivar la cuenta de un auditor."""

    estado: Literal["Activo", "Inactivo"] = Field(
        ...,
        description="Nuevo estado de la cuenta del auditor.",
    )


# Motivo obligatorio para activar al auditor (misma longitud mínima que el
# motivo de rechazo del Banco de auditores).
MIN_MOTIVO_ACTIVACION = 10


class ActivarAuditor(BaseModel):
    """Activa al auditor cuya postulación vigente ya está aprobada."""

    motivo: str = Field(
        ...,
        min_length=MIN_MOTIVO_ACTIVACION,
        max_length=1000,
        description="Por qué se activa al auditor (queda en el historial de la postulación).",
    )

    @field_validator("motivo", mode="before")
    @classmethod
    def _recortar(cls, valor):
        # Solo espacios no cuentan como motivo.
        return valor.strip() if isinstance(valor, str) else valor
