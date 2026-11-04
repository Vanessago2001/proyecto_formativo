"""
Módulo de Asignación de Auditores.

REQ-AUD-001 — Asignación de Auditores.

Las asignaciones se almacenan en las tablas existentes:
- auditores_solicitud
- detalle_programacion_auditor
- programacion_visita
- bitacora_validacion_agenda
"""

from dataclasses import dataclass
from uuid import UUID
from datetime import datetime


@dataclass
class AuditorElegible:
    """Resultado de las validaciones de elegibilidad de un auditor."""

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


@dataclass
class AsignacionAuditor:
    """Representación interna de una asignación."""

    id: UUID
    id_solicitud: UUID
    id_auditor: UUID
    rol_auditor: str

    fecha_inicio_planificada: datetime | None
    fecha_fin_planificada: datetime | None

    estado_asignacion: str