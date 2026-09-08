"""
M5 — GESTIÓN DE SOLICITUDES
Esquemas Pydantic del Bloque 1 (ciclo de vida de la solicitud).

Los nombres de campo siguen las columnas reales de la tabla `solicitud`
que ya existe en la base de datos del proyecto.
"""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class EstadoSolicitud(str, Enum):
    """
    Estados del ciclo de vida cubiertos por el Bloque 1.

        Borrador     -> creada, editable y eliminable por la empresa (SOL-001..004)
        Radicada     -> enviada formalmente, ya no se edita (SOL-005)
        En revision  -> la administración la tomó; deja de ser cancelable (SOL-009)
        Cancelada    -> retirada por la empresa antes de la revisión (SOL-009)

    Los estados posteriores (aprobación y cierre) llegan con los bloques 6 y 7.
    Se escriben capitalizados y sin tilde, como el resto de estados del
    proyecto ('Activo', 'Inactivo', 'Bloqueado').
    """

    borrador = "Borrador"
    radicada = "Radicada"
    en_revision = "En revision"
    cancelada = "Cancelada"


# Estados en los que la solicitud todavía es un borrador editable.
ESTADOS_EDITABLES = {EstadoSolicitud.borrador}

# Estados desde los que la empresa aún puede cancelar (SOL-009: "antes de revisión").
ESTADOS_CANCELABLES = {EstadoSolicitud.borrador, EstadoSolicitud.radicada}


class SolicitudCrear(BaseModel):
    """
    Cuerpo de SOL-001 (crear solicitud) y SOL-002 (guardar borrador).

    Todos los datos técnicos son opcionales al crear: la solicitud nace como
    borrador y se completa antes de radicarla. El detalle de la norma, el
    alcance y los procesos se trabaja a fondo en el Bloque 2.
    """

    id_empresa: UUID | None = Field(
        default=None,
        description=(
            "Empresa titular. Solo hace falta si el usuario está asociado a "
            "más de una empresa; en otro caso se deduce de su vinculación."
        ),
    )
    id_norma: UUID | None = Field(
        default=None,
        description="Norma ISO solicitada (tabla `norma`). Obligatoria al radicar.",
    )
    alcance_certificacion: str | None = Field(
        default=None,
        max_length=2000,
        description="Alcance técnico de la certificación. Obligatorio al radicar.",
    )
    numero_empleados: int | None = Field(default=None, ge=0)
    numero_sedes: int | None = Field(default=None, ge=0)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = Field(default=None, max_length=2000)


class SolicitudEditar(BaseModel):
    """
    Cuerpo de SOL-003 (editar borrador).

    Todos los campos son opcionales: solo se actualiza lo que llegue.
    """

    id_norma: UUID | None = None
    alcance_certificacion: str | None = Field(default=None, max_length=2000)
    numero_empleados: int | None = Field(default=None, ge=0)
    numero_sedes: int | None = Field(default=None, ge=0)
    persona_contacto: str | None = Field(default=None, max_length=150)
    observaciones: str | None = Field(default=None, max_length=2000)


class SolicitudCancelar(BaseModel):
    """Cuerpo de SOL-009 (cancelar antes de revisión)."""

    motivo: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Motivo de la cancelación; queda en el historial de estados.",
    )


class SolicitudRespuesta(BaseModel):
    """Representación completa de una solicitud."""

    id_solicitud: UUID
    numero_radicado: str | None
    estado: EstadoSolicitud
    id_empresa: UUID | None
    id_norma: UUID | None
    alcance_certificacion: str | None
    numero_empleados: int | None
    numero_sedes: int | None
    persona_contacto: str | None
    observaciones: str | None
    motivo_cancelacion: str | None
    ciclo_renovacion: int | None
    usuario_creador: UUID | None
    fecha: date | None
    fecha_creacion: datetime | None
    fecha_radicacion: datetime | None
    fecha_cancelacion: datetime | None


class SolicitudEstadoRespuesta(BaseModel):
    """Respuesta reducida de SOL-010 (consultar estado)."""

    id_solicitud: UUID
    numero_radicado: str | None
    estado: EstadoSolicitud
    fecha_creacion: datetime | None
    fecha_radicacion: datetime | None
    fecha_cancelacion: datetime | None
