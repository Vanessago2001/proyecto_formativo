from pydantic import BaseModel
from datetime import date
from enum import Enum


class EstadoTarea(str, Enum):
    pendiente = "Pendiente"
    en_progreso = "En progreso"
    finalizada = "Finalizada"
    eliminada = "Eliminada"


class TareaCreate(BaseModel):
    nombre: str
    descripcion: str
    fecha_vencimiento: date
    responsable_hizo: str


class TareaEstadoUpdate(BaseModel):
    estado: EstadoTarea


class TareaResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str
    fecha_vencimiento: date
    responsable_hizo: str
    estado: str
