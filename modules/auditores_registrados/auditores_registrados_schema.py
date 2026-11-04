from typing import Literal

from pydantic import BaseModel, Field


class CambioEstadoAuditor(BaseModel):
    """Solicitud para activar o inactivar la cuenta de un auditor."""

    estado: Literal["Activo", "Inactivo"] = Field(
        ...,
        description="Nuevo estado de la cuenta del auditor.",
    )
