"""
M5 — GESTIÓN DE SOLICITUDES
Esquemas del Bloque 2 (información general, SOL-011 a SOL-020).

Los nombres de campo siguen las columnas reales de `solicitud`,
`alcance_solicitud` y `proceso_solicitud`.
"""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EstadoRegistro(str, Enum):
    """
    Estado de un alcance o de un proceso clave.

    La hoja no tiene permiso para eliminarlos, así que se desactivan con el
    permiso de edición (SOL-014 / SOL-016) y el registro no se pierde.
    """

    activo = "Activo"
    inactivo = "Inactivo"


class _Cuerpo(BaseModel):
    """Base de los cuerpos de entrada: recorta espacios en los textos."""

    model_config = ConfigDict(str_strip_whitespace=True)


# ============================================================
# SOL-011 / SOL-012 — NORMA ISO
# ============================================================

class NormaAsignar(_Cuerpo):
    """Cuerpo de SOL-011 (registrar) y SOL-012 (editar) la norma ISO."""

    id_norma: UUID = Field(..., description="Norma de la tabla `norma`.")


# ============================================================
# SOL-013 / SOL-014 — ALCANCE TÉCNICO
# ============================================================

class AlcanceCrear(_Cuerpo):
    """Cuerpo de SOL-013 (registrar alcance técnico)."""

    descripcion: str = Field(..., min_length=5, max_length=2000)


class AlcanceEditar(_Cuerpo):
    """Cuerpo de SOL-014 (editar alcance). Solo se cambia lo que llegue."""

    descripcion: str | None = Field(default=None, min_length=5, max_length=2000)
    estado: EstadoRegistro | None = None


class AlcanceRespuesta(BaseModel):
    id_alcance: UUID
    id_solicitud: UUID
    descripcion: str
    estado: str | None
    fecha_registro: datetime | None


# ============================================================
# SOL-015 / SOL-016 — PROCESOS CLAVE
# ============================================================

class ProcesoCrear(_Cuerpo):
    """Cuerpo de SOL-015 (registrar proceso clave)."""

    nombre: str = Field(..., min_length=3, max_length=150)
    descripcion: str | None = Field(default=None, max_length=2000)


class ProcesoEditar(_Cuerpo):
    """Cuerpo de SOL-016 (editar proceso). Solo se cambia lo que llegue."""

    nombre: str | None = Field(default=None, min_length=3, max_length=150)
    descripcion: str | None = Field(default=None, max_length=2000)
    estado: EstadoRegistro | None = None


class ProcesoRespuesta(BaseModel):
    id_proceso: UUID
    id_solicitud: UUID
    nombre: str
    descripcion: str | None
    estado: str | None
    fecha_registro: datetime | None


# ============================================================
# SOL-017 / SOL-018 / SOL-019 — TAMAÑO DE LA EMPRESA
# ============================================================

class NumeroEmpleados(_Cuerpo):
    """Cuerpo de SOL-017 (registrar) y SOL-018 (editar)."""

    numero_empleados: int = Field(..., ge=1, le=1_000_000)


class NumeroSedes(_Cuerpo):
    """Cuerpo de SOL-019 (registrar número de sedes)."""

    numero_sedes: int = Field(..., ge=1, le=10_000)


# ============================================================
# SOL-020 — CONSULTAR INFORMACIÓN GENERAL
# ============================================================

class InformacionGeneral(BaseModel):
    """
    Todo lo que la empresa declaró en la solicitud, en una sola respuesta.

    `estado` es texto libre y no el enum del Bloque 1: la consulta es de solo
    lectura y debe funcionar también con las solicitudes antiguas de la base.
    """

    id_solicitud: UUID
    numero_radicado: str | None
    estado: str | None
    fecha: date | None = None
    fecha_creacion: datetime | None = None
    fecha_radicacion: datetime | None = None

    id_empresa: UUID | None
    empresa_nombre: str | None = None
    empresa_nit: str | None = None

    id_norma: UUID | None
    norma_codigo: str | None = None
    norma_nombre: str | None = None
    norma_version: str | None = None

    alcance_certificacion: str | None
    numero_empleados: int | None
    numero_sedes: int | None
    persona_contacto: str | None
    observaciones: str | None

    alcances: list[AlcanceRespuesta]
    procesos: list[ProcesoRespuesta]
    sedes_incluidas: int = Field(
        description="Sedes agregadas en el Bloque 3 (sin contar las retiradas).",
    )
    campos_pendientes: list[str] = Field(
        description="Campos obligatorios que faltan para poder radicar (SOL-005).",
    )
