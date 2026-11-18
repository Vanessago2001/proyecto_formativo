"""Endpoints de la calificación de visitas (auditor califica, Comité consulta)."""

from uuid import UUID

from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.auth.dependencies import require_auditor_aprobado
from modules.calificacion_visitas.calificacion_service import CalificacionVisitaService

# Solo el auditor ya aprobado califica visitas (ver require_auditor_aprobado).
router = APIRouter(
    prefix="/calificacion-visitas",
    tags=["Calificación de visitas"],
    dependencies=[Depends(require_auditor_aprobado)],
)


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


@router.get("/expediente/{id_solicitud}/visita/{id_programacion}/excel/{id_auditor}")
async def descargar_excel_evaluacion(
    id_solicitud: UUID,
    id_programacion: UUID,
    id_auditor: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Excel de la evaluación de la visita (Comité y Coordinador, con imparcialidad)."""
    contenido, nombre, tipo = await CalificacionVisitaService(db).descargar_excel(
        id_solicitud, id_programacion, id_auditor, current_user
    )
    ascii_nombre = nombre.encode("ascii", "ignore").decode() or "evaluacion_visita"
    return Response(
        content=contenido,
        media_type=tipo,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_nombre}\"; filename*=UTF-8''{quote(nombre)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
