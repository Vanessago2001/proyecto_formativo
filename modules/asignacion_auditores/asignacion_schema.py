"""Esquemas Pydantic para REQ-AUD-001 — Asignación de Auditores."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class RolAuditor(str, Enum):
    LIDER = "Auditor líder"
    EXPERTO_TECNICO = "Experto técnicos"
    AUDITOR_INTEGRAL = "Auditor integral"
    OBSERVADOR = "Observador"


class AsignacionAuditorCrear(BaseModel):
    """Datos para relacionar un auditor con una solicitud y asignarle rol."""

    id_solicitud: UUID = Field(..., description="Solicitud de certificación aprobada.")
    id_auditor: UUID = Field(..., description="Usuario auditor que se asignará.")
    rol_auditor: RolAuditor = Field(..., description="Rol individual del auditor en esta solicitud.")


class AuditorElegibleRespuesta(BaseModel):
    id_usuario: UUID
    nombre: str
    correo: str
    tipo_doc: str | None = None
    num_doc: str | None = None
    estado_usuario: str
    estado_auditor: str
    ciudad_residencia: str | None = None
    departamento_residencia: str | None = None
    modalidad_preferida: str | None = None
    competencia_norma: bool
    experiencia_sector: bool | None = None
    conflicto_interes: bool
    disponible: bool | None = None
    sin_cruce_horario: bool | None = None
    ya_asignado: bool = False
    elegible: bool
    motivo: str | None = None


class AuditoresElegiblesPagina(BaseModel):
    items: list[AuditorElegibleRespuesta]
    page: int
    page_size: int
    total: int
    total_pages: int


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
    fecha_auditoria: datetime | None = None


class AsignacionAuditorRespuesta(BaseModel):
    id: UUID
    id_solicitud: UUID
    id_auditor: UUID
    auditor_nombre: str
    auditor_correo: str
    rol_auditor: str
    especialidad: str | None = None
    fecha_inicio_planificada: datetime | None = None
    fecha_fin_planificada: datetime | None = None
    estado_asignacion: str
