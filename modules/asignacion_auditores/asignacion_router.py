"""
REQ-AUD-001 — Router de Asignación de Auditores.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user

from modules.asignacion_auditores.asignacion_schema import (
    AsignacionAuditorCrear,
)
from modules.asignacion_auditores.asignacion_service import (
    AsignacionAuditorService,
)


router = APIRouter(
    prefix="/asignacion-auditores",
    tags=["Asignación de Auditores"],
)


# ============================================================
# SOLICITUDES APROBADAS
# ============================================================

@router.get(
    "/solicitudes",
    summary="Consultar solicitudes aprobadas para asignación",
)
async def listar_solicitudes_aprobadas(
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AsignacionAuditorService(db)

    return await service.listar_solicitudes_aprobadas()


# ============================================================
# AUDITORES ELEGIBLES
# ============================================================

@router.get(
    "/solicitudes/{id_solicitud}/auditores",
    summary="Consultar auditores elegibles",
)
async def listar_auditores_elegibles(
    id_solicitud: UUID,
    fecha_inicio: datetime,
    fecha_fin: datetime,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AsignacionAuditorService(db)

    return await service.listar_auditores_elegibles(
        id_solicitud=id_solicitud,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )


# ============================================================
# CREAR ASIGNACIÓN
# ============================================================

@router.post(
    "/",
    summary="Asignar auditor",
)
async def asignar_auditor(
    data: AsignacionAuditorCrear,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AsignacionAuditorService(db)

    return await service.asignar(
        data=data,
        usuario=usuario,
    )


# ============================================================
# LISTAR ASIGNACIONES
# ============================================================

@router.get(
    "/",
    summary="Consultar auditores asignados",
)
async def listar_asignaciones(
    id_solicitud: UUID | None = Query(
        default=None,
    ),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AsignacionAuditorService(db)

    return await service.listar_asignaciones(
        id_solicitud=id_solicitud,
    )