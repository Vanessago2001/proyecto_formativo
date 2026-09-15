"""
M5 — GESTIÓN DE SOLICITUDES
Esquemas del Bloque 3 (sedes de la solicitud, SOL-021 a SOL-030).

Las sedes viven en `sede_empresa` (son de la empresa) y la tabla
`solicitud_sede` guarda qué sedes entran en cada solicitud.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Estados que admite `sede_empresa` (restricción chk_estado_sede).
ESTADO_SEDE_ACTIVA = "Activa"
ESTADO_SEDE_INACTIVA = "Inactiva"


class EstadoSedeSolicitud(str, Enum):
    """
    Estado del vínculo sede-solicitud (`solicitud_sede.estado`).

        Incluida           -> la empresa la agregó (SOL-021 / SOL-024)
        Validada           -> Administración la revisó sin observaciones (SOL-029)
        Con observaciones  -> Administración encontró algo por corregir (SOL-029)
        Excluida           -> la empresa la quitó o la inactivó (SOL-023)
    """

    incluida = "Incluida"
    validada = "Validada"
    con_observaciones = "Con observaciones"
    excluida = "Excluida"


class _Cuerpo(BaseModel):
    """Base de los cuerpos de entrada: recorta espacios en los textos."""

    model_config = ConfigDict(str_strip_whitespace=True)


# ============================================================
# SOL-021 / SOL-024 — INCLUIR O REGISTRAR
# ============================================================

class SedeIncluir(_Cuerpo):
    """Cuerpo de SOL-021: incluir una sede que la empresa ya tiene registrada."""

    id_sede: UUID


class SedeNueva(_Cuerpo):
    """
    Cuerpo de SOL-024: registrar una sede nueva con su dirección.

    Ciudad, departamento y país SOLO se indican aquí (SOL-026 y SOL-027): no
    se pueden cambiar después. Si están mal, la sede se inactiva y se registra
    otra.
    """

    nombre_sede: str = Field(..., min_length=2, max_length=100)
    direccion: str = Field(..., min_length=5, max_length=255)
    ciudad: str = Field(..., min_length=2, max_length=100)
    departamento: str = Field(..., min_length=2, max_length=100)
    pais: str | None = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Si no llega se guarda 'Colombia'.",
    )
    es_principal: bool = False


# ============================================================
# SOL-022 / SOL-025 — EDICIONES PERMITIDAS
# ============================================================

class SedeEditar(_Cuerpo):
    """
    Cuerpo de SOL-022 (editar sede en solicitud): nombre y sede principal.

    La dirección tiene su propio permiso (SOL-025). Ciudad, departamento y
    país no se editan.
    """

    nombre_sede: str | None = Field(default=None, min_length=2, max_length=100)
    es_principal: bool | None = None


class DireccionSede(_Cuerpo):
    """Cuerpo de SOL-025 (editar dirección de sede)."""

    direccion: str = Field(..., min_length=5, max_length=255)


# ============================================================
# RESPUESTAS
# ============================================================

class SedeEmpresaRespuesta(BaseModel):
    """Una sede del catálogo de la empresa (para elegirla en SOL-021)."""

    id_sede: UUID
    nombre_sede: str
    direccion: str | None
    ciudad: str | None
    departamento: str | None
    pais: str | None
    es_principal: bool | None
    estado: str | None


class SedeSolicitudRespuesta(BaseModel):
    """Una sede incluida en la solicitud, con su estado dentro de ella."""

    id_solicitud_sede: UUID
    id_solicitud: UUID
    id_sede: UUID
    nombre_sede: str
    direccion: str | None
    ciudad: str | None
    departamento: str | None
    pais: str | None
    es_principal: bool | None
    estado_sede: str | None
    estado_en_solicitud: str
    fecha_inclusion: datetime | None


class SedeValidada(BaseModel):
    id_sede: UUID
    nombre_sede: str
    estado_en_solicitud: str
    faltantes: list[str]


class ValidacionSedes(BaseModel):
    """Resultado de SOL-029 (validar sedes)."""

    id_solicitud: UUID
    valida: bool
    numero_sedes_declarado: int | None
    sedes_incluidas: int
    inconsistencias: list[str]
    sedes: list[SedeValidada]
