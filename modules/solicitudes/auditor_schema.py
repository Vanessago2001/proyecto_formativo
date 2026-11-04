"""
M5 — GESTIÓN DE SOLICITUDES
Esquemas del Bloque 5 (asignación de auditores, SOL-041 a SOL-050).
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PropuestaAuditor(BaseModel):
    """Cuerpo de SOL-047 (proponer auditor para el servicio)."""

    id_auditor: UUID
    especialidad: Optional[str] = Field(default=None, max_length=120)
    fecha_inicio_planificada: Optional[date] = None
    fecha_fin_planificada: Optional[date] = None


class MotivoAsignacion(BaseModel):
    """Cuerpo de SOL-050 (cancelar asignación)."""

    motivo: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Por qué se cancela. Queda en la bitácora y en el historial.",
    )


class ReasignacionAuditor(BaseModel):
    """Cuerpo de SOL-049 (reasignar auditor)."""

    id_nuevo_auditor: UUID
    motivo: str = Field(..., min_length=5, max_length=500)


class CandidatoAuditor(BaseModel):
    """Un auditor del banco, visto desde la solicitud."""

    id_usuario: UUID
    nombre: Optional[str] = None
    correo: Optional[str] = None
    ciudad_residencia: Optional[str] = None
    departamento_residencia: Optional[str] = None
    calificacion_promedio: Optional[float] = None
    competente_en_norma: bool
    competente_en_sector: bool
    tiene_conflicto: bool
    tiene_disponibilidad: bool
    ya_en_la_solicitud: bool
    apto: bool
    motivos: list[str]


class AsignacionRespuesta(BaseModel):
    """Una fila de `auditores_solicitud` vista desde M5."""

    id: UUID
    id_solicitud: UUID
    id_auditor: Optional[UUID] = None
    especialidad: Optional[str] = None
    estado_asignacion: str
    fecha_inicio_planificada: Optional[date] = None
    fecha_fin_planificada: Optional[date] = None
    fecha_propuesta: Optional[datetime] = None
    fecha_asignacion: Optional[datetime] = None
    fecha_aprobacion: Optional[datetime] = None
    fecha_cancelacion: Optional[datetime] = None
    motivo_cancelacion: Optional[str] = None
    motivo_reasignacion: Optional[str] = None
    usuario_asigna: Optional[UUID] = None
    usuario_aprueba: Optional[UUID] = None
    usuario_cancela: Optional[UUID] = None
