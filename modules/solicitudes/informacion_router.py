"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 2 (información general, SOL-011 a SOL-020).

Cada ruta declara el código de permiso de la matriz del Excel mediante
`requiere_permiso(...)`, que además entrega el usuario autenticado.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.solicitudes.informacion_schema import (
    AlcanceCrear,
    AlcanceEditar,
    AlcanceRespuesta,
    InformacionGeneral,
    NormaAsignar,
    NumeroEmpleados,
    NumeroSedes,
    ProcesoCrear,
    ProcesoEditar,
    ProcesoRespuesta,
)
from modules.solicitudes.informacion_service import InformacionService
from modules.solicitudes.solicitud_permissions import requiere_permiso
from modules.solicitudes.solicitud_schema import SolicitudRespuesta

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Información general de la solicitud"],
)


# ============================================================
# SOL-011 / SOL-012 — NORMA ISO
# ============================================================

@router.post(
    "/{id_solicitud}/norma",
    response_model=SolicitudRespuesta,
    summary="SOL-011 · Registrar norma ISO solicitada",
)
async def registrar_norma(
    id_solicitud: UUID,
    data: NormaAsignar,
    usuario: dict = Depends(requiere_permiso("SOL-011")),
    db: AsyncSession = Depends(get_db),
):
    """Asigna la norma a una solicitud que todavía no tiene una."""
    return await InformacionService(db).registrar_norma(
        id_solicitud, data.id_norma, usuario
    )


@router.patch(
    "/{id_solicitud}/norma",
    response_model=SolicitudRespuesta,
    summary="SOL-012 · Editar norma ISO",
)
async def editar_norma(
    id_solicitud: UUID,
    data: NormaAsignar,
    usuario: dict = Depends(requiere_permiso("SOL-012")),
    db: AsyncSession = Depends(get_db),
):
    """Cambia la norma ya registrada."""
    return await InformacionService(db).editar_norma(
        id_solicitud, data.id_norma, usuario
    )


# ============================================================
# SOL-013 / SOL-014 — ALCANCE TÉCNICO
# ============================================================

@router.post(
    "/{id_solicitud}/alcances",
    response_model=AlcanceRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-013 · Registrar alcance técnico",
)
async def registrar_alcance(
    id_solicitud: UUID,
    data: AlcanceCrear,
    usuario: dict = Depends(requiere_permiso("SOL-013")),
    db: AsyncSession = Depends(get_db),
):
    """Añade una línea al alcance técnico."""
    return await InformacionService(db).registrar_alcance(id_solicitud, data, usuario)


@router.patch(
    "/{id_solicitud}/alcances/{id_alcance}",
    response_model=AlcanceRespuesta,
    summary="SOL-014 · Editar alcance",
)
async def editar_alcance(
    id_solicitud: UUID,
    id_alcance: UUID,
    data: AlcanceEditar,
    usuario: dict = Depends(requiere_permiso("SOL-014")),
    db: AsyncSession = Depends(get_db),
):
    """Cambia la descripción o pasa la línea a 'Inactivo'."""
    return await InformacionService(db).editar_alcance(
        id_solicitud, id_alcance, data, usuario
    )


# ============================================================
# SOL-015 / SOL-016 — PROCESOS CLAVE
# ============================================================

@router.post(
    "/{id_solicitud}/procesos",
    response_model=ProcesoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-015 · Registrar procesos clave",
)
async def registrar_proceso(
    id_solicitud: UUID,
    data: ProcesoCrear,
    usuario: dict = Depends(requiere_permiso("SOL-015")),
    db: AsyncSession = Depends(get_db),
):
    """Registra un proceso clave; el nombre no puede repetirse entre activos."""
    return await InformacionService(db).registrar_proceso(id_solicitud, data, usuario)


@router.patch(
    "/{id_solicitud}/procesos/{id_proceso}",
    response_model=ProcesoRespuesta,
    summary="SOL-016 · Editar procesos",
)
async def editar_proceso(
    id_solicitud: UUID,
    id_proceso: UUID,
    data: ProcesoEditar,
    usuario: dict = Depends(requiere_permiso("SOL-016")),
    db: AsyncSession = Depends(get_db),
):
    """Cambia nombre o descripción, o pasa el proceso a 'Inactivo'."""
    return await InformacionService(db).editar_proceso(
        id_solicitud, id_proceso, data, usuario
    )


# ============================================================
# SOL-017 / SOL-018 — NÚMERO DE EMPLEADOS
# ============================================================

@router.post(
    "/{id_solicitud}/numero-empleados",
    response_model=SolicitudRespuesta,
    summary="SOL-017 · Registrar número de empleados",
)
async def registrar_numero_empleados(
    id_solicitud: UUID,
    data: NumeroEmpleados,
    usuario: dict = Depends(requiere_permiso("SOL-017")),
    db: AsyncSession = Depends(get_db),
):
    return await InformacionService(db).registrar_numero_empleados(
        id_solicitud, data.numero_empleados, usuario
    )


@router.patch(
    "/{id_solicitud}/numero-empleados",
    response_model=SolicitudRespuesta,
    summary="SOL-018 · Editar número de empleados",
)
async def editar_numero_empleados(
    id_solicitud: UUID,
    data: NumeroEmpleados,
    usuario: dict = Depends(requiere_permiso("SOL-018")),
    db: AsyncSession = Depends(get_db),
):
    return await InformacionService(db).editar_numero_empleados(
        id_solicitud, data.numero_empleados, usuario
    )


# ============================================================
# SOL-019 — NÚMERO DE SEDES
# ============================================================

@router.post(
    "/{id_solicitud}/numero-sedes",
    response_model=SolicitudRespuesta,
    summary="SOL-019 · Registrar número de sedes",
)
async def registrar_numero_sedes(
    id_solicitud: UUID,
    data: NumeroSedes,
    usuario: dict = Depends(requiere_permiso("SOL-019")),
    db: AsyncSession = Depends(get_db),
):
    """Número de sedes declarado. Las sedes concretas se agregan en el Bloque 3."""
    return await InformacionService(db).registrar_numero_sedes(
        id_solicitud, data.numero_sedes, usuario
    )


# ============================================================
# SOL-020 — CONSULTAR INFORMACIÓN GENERAL
# ============================================================

@router.get(
    "/{id_solicitud}/informacion-general",
    response_model=InformacionGeneral,
    summary="SOL-020 · Consultar información general",
)
async def informacion_general(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-020")),
    db: AsyncSession = Depends(get_db),
):
    """Empresa, norma, alcances, procesos, sedes y lo que falta para radicar."""
    return await InformacionService(db).informacion_general(id_solicitud, usuario)
