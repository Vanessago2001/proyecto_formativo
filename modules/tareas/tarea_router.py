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

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

from modules.tareas.tarea_service import TareaService
from modules.tareas.tarea_schema import (
    TareaCreate,
    TareaEstadoUpdate
)

router = APIRouter(
    prefix="/tareas",
    tags=["Tareas"]
)


@router.post("/")
async def crear_tarea(
    data: TareaCreate,
    db: AsyncSession = Depends(get_db)
):
    service = TareaService(db)
    return await service.crear_tarea(data)


@router.patch("/{tarea_id}/estado")
async def cambiar_estado(
    tarea_id: int,
    data: TareaEstadoUpdate,
    db: AsyncSession = Depends(get_db)
):
    service = TareaService(db)
    return await service.cambiar_estado(
        tarea_id,
        data
    )


@router.get("/")
async def listar_tareas(
    db: AsyncSession = Depends(get_db)
):
    service = TareaService(db)
    return await service.listar_tareas()


@router.get("/usuario/{user_id}")
async def listar_tareas_usuario(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    service = TareaService(db)
    return await service.listar_tareas_usuario(
        user_id
    )
