"""
Endpoints para revisar las acciones que quedaron pendientes de aprobación
(permisos marcados REQ en permisos.xlsx).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_role
from modules.aprobaciones.aprobacion_service import AprobacionService

router = APIRouter(prefix="/api/aprobaciones", tags=["Aprobaciones (permisos REQ)"])

# Quién revisa cada acción lo decide su registro; aquí solo se filtra quién
# puede entrar a estas rutas.
ROLES_REVISION = ["superadmin", "admin"]
ROLES_CONSULTA = ROLES_REVISION + ["auxiliar"]


class Rechazo(BaseModel):
    observacion: str = Field(..., min_length=5, max_length=500)


@router.get("/", summary="Consultar solicitudes de aprobación")
async def listar_aprobaciones(
    estado: Optional[str] = Query(default=None, pattern="^(Pendiente|Aprobada|Rechazada)$"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_CONSULTA)),
):
    """Administración ve todas; el Auxiliar solo las que él pidió."""
    return await AprobacionService(db).listar(current_user, estado)


@router.post("/{id_aprobacion}/aprobar", summary="Aprobar y ejecutar la acción")
async def aprobar(
    id_aprobacion: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION)),
):
    return await AprobacionService(db).aprobar(id_aprobacion, current_user)


@router.post("/{id_aprobacion}/rechazar", summary="Rechazar la acción con un motivo")
async def rechazar(
    id_aprobacion: UUID,
    data: Rechazo,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(ROLES_REVISION)),
):
    return await AprobacionService(db).rechazar(id_aprobacion, current_user, data.observacion)
