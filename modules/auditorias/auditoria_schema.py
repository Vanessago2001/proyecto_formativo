"""
M7 — AUDITORÍAS
Esquemas de entrada de los siete bloques.
"""

from datetime import date, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from modules.auditorias.evaluacion_service import RESULTADOS
from modules.auditorias.hallazgo_service import CLASIFICACIONES, TIPOS
from modules.auditorias.seguimiento_service import ESTADOS


class InicioAuditoria(BaseModel):
    """AUT-001 · iniciar la auditoría de campo."""

    id_solicitud: UUID
    id_programacion: Optional[UUID] = None
    observaciones_iniciales: Optional[str] = Field(default=None, max_length=2000)


class ConfirmacionInicio(BaseModel):
    """AUT-008 · confirmar el inicio formal."""

    hora_inicio: Optional[time] = None


class Observaciones(BaseModel):
    """AUT-009 y AUT-065 · observaciones iniciales y de cierre."""

    observaciones: str = Field(..., min_length=5, max_length=2000)


class MotivoAuditoria(BaseModel):
    """AUT-010 (suspender) y AUT-058 (reabrir)."""

    motivo: str = Field(..., min_length=10, max_length=1000)


class EvaluacionRequisito(BaseModel):
    """AUT-011 / AUT-012 · evaluación de un requisito."""

    resultado: str = Field(..., description=f"Uno de: {', '.join(RESULTADOS)}")
    observacion: Optional[str] = Field(default=None, max_length=2000)
    comentario_tecnico: Optional[str] = Field(default=None, max_length=2000)
    definitiva: bool = Field(
        default=False,
        description="True la deja Registrada; a partir de ahí no se edita.",
    )


class RequisitoControl(BaseModel):
    """AUT-014 · registrar un requisito de control."""

    numeral: str = Field(..., min_length=1, max_length=30)
    descripcion: str = Field(..., min_length=5, max_length=1000)


class ComentarioTecnico(BaseModel):
    """AUT-019 · comentario técnico sobre una evaluación."""

    comentario: str = Field(..., min_length=5, max_length=2000)


class MejoraEvaluacion(BaseModel):
    """AUT-018 · oportunidad de mejora desde la evaluación."""

    descripcion: str = Field(..., min_length=10, max_length=2000)


class HallazgoNuevo(BaseModel):
    """AUT-021 y AUT-025 a AUT-027 · registrar un hallazgo."""

    tipo: str = Field(..., description=f"Uno de: {', '.join(TIPOS)}")
    titulo: str = Field(..., min_length=5, max_length=200)
    descripcion: str = Field(..., min_length=10, max_length=4000)
    clasificacion: Optional[str] = Field(
        default=None, description=f"Solo para no conformidades: {', '.join(CLASIFICACIONES)}"
    )
    requisito_relacionado: Optional[str] = Field(default=None, max_length=200)
    id_evaluacion: Optional[UUID] = None


class HallazgoEditado(BaseModel):
    """AUT-022 · editar un hallazgo registrado."""

    tipo: Optional[str] = None
    clasificacion: Optional[str] = None
    titulo: Optional[str] = Field(default=None, min_length=5, max_length=200)
    descripcion: Optional[str] = Field(default=None, min_length=10, max_length=4000)
    requisito_relacionado: Optional[str] = Field(default=None, max_length=200)


class ClasificacionHallazgo(BaseModel):
    """AUT-024 · clasificar una no conformidad."""

    clasificacion: str = Field(..., description=f"Uno de: {', '.join(CLASIFICACIONES)}")


class RequisitoRelacionado(BaseModel):
    """AUT-028 · asociar el requisito al hallazgo."""

    requisito: str = Field(..., min_length=1, max_length=200)


class ObservacionEvidencia(BaseModel):
    """AUT-038 · observaciones sobre una evidencia."""

    observaciones: str = Field(..., min_length=5, max_length=2000)
    validar: bool = Field(default=False, description="True la deja Validada.")


class AsociarEvidencia(BaseModel):
    """AUT-036 · asociar la evidencia a un requisito evaluado."""

    id_evaluacion: UUID


class ContenidoInforme(BaseModel):
    """AUT-042 / AUT-043 · editar y guardar el borrador del informe."""

    contenido: dict = Field(..., description="Secciones del informe que se reescriben")


class AccionSeguimiento(BaseModel):
    """AUT-053 y AUT-055 · acciones de seguimiento y correctivas."""

    descripcion: str = Field(..., min_length=10, max_length=2000)
    id_hallazgo: Optional[UUID] = None
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class EstadoAccion(BaseModel):
    """Avance de una acción de seguimiento."""

    estado: str = Field(..., description=f"Uno de: {', '.join(ESTADOS)}")
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class CierreAuditoria(BaseModel):
    """AUT-057 · cerrar la auditoría."""

    observaciones: str = Field(..., min_length=10, max_length=2000)


class CierreHallazgo(BaseModel):
    """Cierre de un hallazgo tras verificar su acción correctiva."""

    observacion: str = Field(..., min_length=10, max_length=2000)


class JornadaInicio(BaseModel):
    """AUT-061 · hora de inicio en campo."""

    fecha: Optional[date] = None
    hora_inicio: Optional[time] = None


class JornadaCierre(BaseModel):
    """AUT-062 · hora de finalización diaria."""

    hora_fin: Optional[time] = None
    incidencias: Optional[str] = Field(default=None, max_length=2000)
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class IncidenciaJornada(BaseModel):
    """AUT-064 · incidencias en sitio."""

    incidencias: str = Field(..., min_length=5, max_length=2000)
