from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


DiaSemana = Literal[
    "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo"
]
ModalidadAuditoria = Literal["Presencial", "Remota", "Híbrida"]


class AuditorProgramacion(BaseModel):
    """Auditor seleccionado para una programación de visita."""
    model_config = ConfigDict(extra="forbid")

    id_usuario: UUID
    rol_auditor: str | None = Field(default=None, max_length=80)


class ProgramacionAuditoriaCrear(BaseModel):
    """Datos para programar una visita de una solicitud ya aprobada."""

    model_config = ConfigDict(extra="forbid")

    id_solicitud: UUID
    id_usuario: UUID | None = None
    auditores: list[AuditorProgramacion] | None = None
    id_sede: UUID | None = None
    direccion_servicio: str = Field(min_length=5, max_length=500)
    ciudad_servicio: str = Field(min_length=2, max_length=100)
    modalidad: ModalidadAuditoria = "Presencial"
    fecha_inicio: datetime
    fecha_fin: datetime
    # Flujo "Mostrar más auditores disponibles": permite incorporar al equipo
    # de una sede concreta auditores que aún no estaban asignados a la
    # solicitud. No modifica las asignaciones ni las sedes ya programadas.
    asignar_auditores_adicionales: bool = False

    @model_validator(mode="after")
    def normalizar_auditores(self):
        if not self.auditores:
            if self.id_usuario is None:
                raise ValueError("Debe indicar al menos un auditor.")
            self.auditores = [AuditorProgramacion(id_usuario=self.id_usuario)]
        vistos = set()
        for a in self.auditores:
            if str(a.id_usuario) in vistos:
                raise ValueError("No se puede asignar el mismo auditor dos veces.")
            vistos.add(str(a.id_usuario))
        return self

    @model_validator(mode="after")
    def validar_intervalo(self):
        if self.fecha_fin <= self.fecha_inicio:
            raise ValueError("La fecha/hora final debe ser posterior a la inicial.")
        if self.fecha_inicio.date() != self.fecha_fin.date():
            raise ValueError("La visita debe comenzar y terminar en la misma fecha.")
        return self


class DisponibilidadSemanalDia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dia_semana: DiaSemana
    hora_inicio: time
    hora_fin: time

    @model_validator(mode="after")
    def validar_horas(self):
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("La hora final debe ser posterior a la inicial.")
        return self


class DisponibilidadSemanalCrear(BaseModel):
    """Configura días/horas recurrentes durante un rango de vigencia."""

    model_config = ConfigDict(extra="forbid")

    fecha_inicio: date
    fecha_fin: date | None = None
    dias: list[DisponibilidadSemanalDia] = Field(min_length=1, max_length=7)
    motivo: str = Field(default="Disponibilidad semanal", max_length=255)

    @model_validator(mode="after")
    def validar_vigencia(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final de vigencia no puede ser anterior a la inicial.")
        normalizados = [normalizar_dia(d.dia_semana) for d in self.dias]
        if len(normalizados) != len(set(normalizados)):
            raise ValueError("No se puede repetir un día de la semana en la misma configuración.")
        return self


class FechaNoDisponibleCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fecha_inicio: date
    fecha_fin: date | None = None
    motivo: str = Field(min_length=3, max_length=255)
    # Programación relacionada con el bloqueo (opcional): permite referenciar
    # la auditoría programada que originó la fecha a bloquear.
    id_programacion: UUID | None = None
    # Si es True y existe una auditoría programada en el periodo, esa
    # programación se cancela (notificando a los auditores) y el bloqueo se registra.
    cancelar_programacion: bool = False

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        return self


class DisponibilidadEditar(BaseModel):
    """Reemplaza los datos futuros de un registro de disponibilidad activo."""

    model_config = ConfigDict(extra="forbid")

    fecha_inicio: date
    fecha_fin: date | None = None
    dia_semana: DiaSemana | None = None
    hora_inicio: time | None = None
    hora_fin: time | None = None
    motivo: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def validar_datos(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final de vigencia no puede ser anterior a la inicial.")
        if (self.hora_inicio is None) != (self.hora_fin is None):
            raise ValueError("Debe indicar ambas horas o dejar ambas vacías.")
        if self.hora_inicio is not None and self.hora_fin is not None and self.hora_fin <= self.hora_inicio:
            raise ValueError("La hora final debe ser posterior a la inicial.")
        return self


class DisponibilidadExtraordinariaCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fecha_inicio: date
    fecha_fin: date | None = None
    motivo: str = Field(default="Disponibilidad extraordinaria", max_length=255)

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        return self


class CancelarProgramacion(BaseModel):
    motivo: str = Field(min_length=3, max_length=1000)


class ReprogramarProgramacion(BaseModel):
    fecha_inicio: datetime
    fecha_fin: datetime
    motivo: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validar_intervalo(self):
        if self.fecha_fin <= self.fecha_inicio:
            raise ValueError("La fecha/hora final debe ser posterior a la inicial.")
        if self.fecha_inicio.date() != self.fecha_fin.date():
            raise ValueError("La auditoría debe comenzar y terminar en la misma fecha.")
        return self


def normalizar_dia(dia: str) -> str:
    """Devuelve el nombre de día en español, sin tildes y en minúsculas."""
    return {
        "miércoles": "miercoles",
        "miercoles": "miercoles",
        "sábado": "sabado",
        "sabado": "sabado",
    }.get(dia.strip().lower(), dia.strip().lower())
