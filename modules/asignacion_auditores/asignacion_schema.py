"""Esquemas Pydantic para REQ-AUD-001 — Asignación de Auditores."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RolAuditor(str, Enum):
    """Rol único (17/11/2026): todos los integrantes son 'Auditor'."""

    AUDITOR = "Auditor"


class AsignacionAuditorCrear(BaseModel):
    """Datos para relacionar un auditor con una solicitud (rol único 'Auditor')."""

    id_solicitud: UUID = Field(..., description="Solicitud de certificación aprobada.")
    id_auditor: UUID = Field(..., description="Usuario auditor que se asignará.")
    # Ya no se elige rol: se acepta cualquier valor (pantallas viejas) y se
    # ignora; la asignación se guarda siempre como 'Auditor'.
    rol_auditor: str | None = Field(None, max_length=80, description="Obsoleto: se ignora (rol único 'Auditor').")
    # "Asignar de todas formas": solo Coordinador (o Auxiliar con permiso
    # delegado SOL-048). El conflicto de interés nunca se puede forzar.
    forzar: bool = Field(False, description="Asignar aunque no cumpla la competencia vigente.")
    justificacion: str | None = Field(None, max_length=1000, description="Obligatoria al forzar.")

    @model_validator(mode="after")
    def exigir_justificacion(self):
        if self.forzar and len((self.justificacion or "").strip()) < 10:
            raise ValueError(
                "Para asignar un auditor no elegible escriba una justificación (mínimo 10 caracteres)."
            )
        return self


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


class SolicitudCambioAsignacionCrear(BaseModel):
    """La empresa pide cambiar o cancelar un auditor asignado, con una razón justificada."""

    motivo: str = Field(
        ...,
        max_length=1000,
        # El mínimo de 30 caracteres se valida en el servicio, con mensaje en español.
        description="Razón justificada del cambio (mínimo 30 caracteres).",
    )


class SolicitudCambioAsignacionResolver(BaseModel):
    """El administrador aprueba (cancela la asignación) o rechaza la solicitud."""

    aprobar: bool
    respuesta: str = Field(
        ...,
        max_length=1000,
        # El mínimo de 10 caracteres se valida en el servicio, con mensaje en español.
        description="Respuesta del Coordinador a la empresa (mínimo 10 caracteres).",
    )
