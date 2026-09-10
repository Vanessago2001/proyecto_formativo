"""
Esquemas Pydantic para REQ-AUD-001 — Asignación de Auditores.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RolAuditor(str, Enum):
    LIDER = "Auditor líder"
    APOYO = "Auditor de apoyo"


class AsignacionAuditorCrear(BaseModel):
    """
    Datos necesarios para asignar un auditor a una solicitud.
    """

    id_solicitud: UUID = Field(
        ...,
        description="Solicitud de certificación que será auditada.",
    )

    id_auditor: UUID = Field(
        ...,
        description="Usuario que será asignado como auditor.",
    )

    rol_auditor: RolAuditor = Field(
        ...,
        description="Rol del auditor dentro de la auditoría.",
    )

    fecha_inicio_planificada: datetime = Field(
        ...,
        description="Fecha y hora de inicio de la auditoría.",
    )

    fecha_fin_planificada: datetime = Field(
        ...,
        description="Fecha y hora de finalización de la auditoría.",
    )

    especialidad: str | None = Field(
        default=None,
        max_length=80,
    )

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin_planificada <= self.fecha_inicio_planificada:
            raise ValueError(
                "La fecha de finalización debe ser posterior "
                "a la fecha de inicio."
            )

        return self


class AuditorElegibleRespuesta(BaseModel):
    id_usuario: UUID
    nombre: str
    correo: str

    estado_usuario: str
    estado_auditor: str

    competencia_norma: bool
    experiencia_sector: bool
    conflicto_interes: bool
    disponible: bool
    sin_cruce_horario: bool

    elegible: bool
    motivo: str | None = None


class SolicitudAsignacionRespuesta(BaseModel):
    id_solicitud: UUID
    numero_radicado: str | None
    estado: str

    id_empresa: UUID | None
    empresa_nombre: str | None

    id_norma: UUID | None
    norma_codigo: str | None
    norma_nombre: str | None
    norma_version: str | None

    fecha_auditoria: datetime | None


class AsignacionAuditorRespuesta(BaseModel):
    id: UUID
    id_solicitud: UUID
    id_auditor: UUID

    auditor_nombre: str
    auditor_correo: str

    rol_auditor: str
    especialidad: str | None

    fecha_inicio_planificada: datetime | None
    fecha_fin_planificada: datetime | None

    estado_asignacion: str