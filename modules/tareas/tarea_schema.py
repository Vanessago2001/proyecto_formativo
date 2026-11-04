"""
MODULO HEREDADO - NO ESTA EN USO

Este modulo viene de otro proyecto y su tabla `tareas` NO EXISTE en la base
de datos de CertiSENA, asi que todas sus consultas fallan con
`relation "tareas" does not exist`.

Se conserva el codigo por si el equipo quiere reaprovecharlo, pero su router
NO se registra en main.py: mientras la tabla no exista, exponerlo solo
produce errores 500.

Para reactivarlo hacen falta dos cosas:
  1. Crear la tabla `tareas` en la base de datos.
  2. Descomentar el import y el `include_router` en main.py.
"""

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
