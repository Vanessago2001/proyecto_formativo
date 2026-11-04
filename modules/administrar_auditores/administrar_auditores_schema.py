from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SolicitudAuditorItem(BaseModel):
    id_postulacion: UUID
    id_usuario: UUID
    nombre: str
    correo: str
    estado_postulacion: str
    estado_auditor: str
    fecha_postulacion: datetime | None = None
    fecha_revision: datetime | None = None


class SolicitudAuditorDetalle(BaseModel):
    id_postulacion: UUID
    id_usuario: UUID
    nombre: str
    correo: str
    tipo_doc: str
    num_doc: str
    estado_postulacion: str
    estado_auditor: str
    observaciones_tecnicas: str | None = None
    fecha_postulacion: datetime | None = None
    fecha_revision: datetime | None = None

    perfil: dict | None = None
    competencias: list[dict] = []
    conflictos: list[dict] = []
    documentos: list[dict] = []


class CambioEstadoAuditor(BaseModel):
    observaciones: str | None = Field(
        default=None,
        max_length=5000,
    )