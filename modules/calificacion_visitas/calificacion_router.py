"""Endpoints de la calificación de visitas (auditor califica, Comité consulta)."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.calificacion_visitas.calificacion_service import CalificacionVisitaService

router = APIRouter(prefix="/calificacion-visitas", tags=["Calificación de visitas"])


@router.get("/mias")
async def mis_calificaciones(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calificaciones que el auditor autenticado ya registró (para pintar el botón)."""
    return await CalificacionVisitaService(db).mis_calificaciones(current_user)


@router.put("/programacion/{id_programacion}")
async def guardar_calificacion(
    id_programacion: UUID,
    datos: dict = Body(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Registra o edita la calificación (1 a 100 %) y los comentarios del auditor sobre la visita."""
    return await CalificacionVisitaService(db).guardar(id_programacion, datos, current_user)


@router.get("/expediente/{id_solicitud}")
async def calificaciones_del_expediente(
    id_solicitud: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Calificaciones de todo el equipo auditor del expediente (Comité y Coordinador)."""
    return await CalificacionVisitaService(db).calificaciones_expediente(id_solicitud, current_user)
