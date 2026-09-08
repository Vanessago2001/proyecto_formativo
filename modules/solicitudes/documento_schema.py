"""
M5 — GESTIÓN DE SOLICITUDES
Esquemas del Bloque 4 (documentos adjuntos, SOL-031 a SOL-040).
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class EstadoDocumento(str, Enum):
    """
    Estados por los que pasa un documento adjunto.

        Pendiente   -> subido por la empresa, a la espera de revisión
        Aprobado    -> la administración lo dio por válido (SOL-038)
        Rechazado   -> la administración lo rechazó (SOL-037)
        Correccion  -> se pidió corregirlo y volver a subirlo (SOL-039)
    """

    pendiente = "Pendiente"
    aprobado = "Aprobado"
    rechazado = "Rechazado"
    correccion = "Correccion"


# Estados en los que la empresa todavía puede reemplazar o borrar el archivo.
ESTADOS_MODIFICABLES = {
    EstadoDocumento.pendiente,
    EstadoDocumento.rechazado,
    EstadoDocumento.correccion,
}


class RevisionDocumento(BaseModel):
    """Cuerpo de SOL-037 (rechazar) y SOL-039 (solicitar corrección)."""

    observaciones: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Motivo del rechazo o corrección pedida. Lo ve la empresa.",
    )


class AprobacionDocumento(BaseModel):
    """Cuerpo de SOL-038 (aprobar). Las observaciones son opcionales."""

    observaciones: str | None = Field(default=None, max_length=1000)


class DocumentoRespuesta(BaseModel):
    """Un documento adjunto de la solicitud."""

    id_documento: UUID
    id_solicitud: UUID
    tipo_documento: str
    nombre_archivo: str
    version: int
    estado: EstadoDocumento
    observaciones: str | None
    usuario_subida: UUID | None
    usuario_revision: UUID | None
    fecha_subida: datetime | None
    fecha_revision: datetime | None


class VersionDocumento(BaseModel):
    """Una versión anterior, guardada al reemplazar el archivo (SOL-040)."""

    id_historial: UUID
    id_documento: UUID
    version: int
    nombre_archivo: str
    estado: str
    observaciones: str | None
    usuario_subida: UUID | None
    fecha_subida: datetime | None
    fecha_reemplazo: datetime | None


class ReglasFormato(BaseModel):
    """Reglas que aplica la validación automática de formato (SOL-036)."""

    extensiones_permitidas: list[str]
    tamano_maximo_mb: float
    tipos_documento_sugeridos: list[str]
