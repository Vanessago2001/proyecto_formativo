"""REQ-AUD-001 — Router de Asignación de Auditores."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.asignacion_auditores.asignacion_schema import (
    AsignacionAuditorCrear,
    AuditoresElegiblesPagina,
)
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService

router = APIRouter(prefix="/asignacion-auditores", tags=["Asignación de Auditores"])


@router.get("/solicitudes", summary="Consultar solicitudes aprobadas para asignación")
async def listar_solicitudes_aprobadas(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    buscar: str | None = Query(None, max_length=120),
    ciudad: str | None = Query(None, max_length=100),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    norma: str | None = Query(None, max_length=80),
    sector: str | None = Query(None, max_length=80),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).listar_solicitudes_aprobadas(
        page=page,
        page_size=page_size,
        buscar=buscar,
        ciudad=ciudad,
        desde=desde,
        hasta=hasta,
        norma=norma,
        sector=sector,
    )


@router.get(
    "/solicitudes/{id_solicitud}/auditores",
    summary="Consultar y filtrar auditores candidatos con paginación",
    response_model=AuditoresElegiblesPagina,
)
async def listar_auditores_elegibles(
    id_solicitud: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    buscar: str | None = Query(None, max_length=120, description="Nombre, correo o documento"),
    ciudad: str | None = Query(None, max_length=100),
    modalidad: str | None = Query(None, max_length=40),
    competencia: str | None = Query(None, pattern="^(si|no)$"),
    conflicto: str | None = Query(None, pattern="^(si|no)$"),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).listar_auditores_elegibles(
        id_solicitud=id_solicitud,
        page=page,
        page_size=page_size,
        buscar=buscar,
        ciudad=ciudad,
        modalidad=modalidad,
        competencia=competencia,
        conflicto=conflicto,
    )


@router.post("/", summary="Asignar auditor a solicitud con un rol individual")
async def asignar_auditor(
    data: AsignacionAuditorCrear,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).asignar(data=data, usuario=usuario)


@router.get("/", summary="Consultar auditores asignados")
async def listar_asignaciones(
    id_solicitud: UUID | None = Query(default=None),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).listar_asignaciones(id_solicitud=id_solicitud)


@router.delete("/{id_asignacion}", summary="Cancelar asignación de auditor")
async def cancelar_asignacion(
    id_asignacion: UUID,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).cancelar_asignacion(id_asignacion)
