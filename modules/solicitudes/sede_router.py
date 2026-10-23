"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 3 (sedes de la solicitud, SOL-021 a SOL-030).

SOL-026 (ciudad) y SOL-027 (departamento) no tienen ruta propia: esos datos
solo se indican al registrar la sede (SOL-024), que verifica ambos permisos.
Para corregirlos, la sede se inactiva y se registra otra.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.solicitudes.sede_excel import TIPO_XLSX
from modules.solicitudes.sede_schema import (
    DireccionSede,
    SedeEditar,
    SedeEmpresaRespuesta,
    SedeIncluir,
    SedeNueva,
    SedeSolicitudRespuesta,
    ValidacionSedes,
)
from modules.solicitudes.sede_service import SedeService
from modules.solicitudes.solicitud_permissions import requiere_permiso

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Sedes de la solicitud"],
)


# ============================================================
# SOL-028 — CONSULTAR SEDES AÑADIDAS
# ============================================================

@router.get(
    "/{id_solicitud}/sedes",
    response_model=list[SedeSolicitudRespuesta],
    summary="SOL-028 · Consultar sedes añadidas",
)
async def listar_sedes(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-028")),
    db: AsyncSession = Depends(get_db),
):
    return await SedeService(db).listar(id_solicitud, usuario)


# ============================================================
# SOL-021 — INCLUIR UNA SEDE YA REGISTRADA
# ============================================================

@router.get(
    "/{id_solicitud}/sedes/disponibles",
    response_model=list[SedeEmpresaRespuesta],
    summary="SOL-021 · Sedes de la empresa que se pueden agregar",
)
async def sedes_disponibles(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-021")),
    db: AsyncSession = Depends(get_db),
):
    """Sedes activas de la empresa que todavía no están en la solicitud."""
    return await SedeService(db).disponibles(id_solicitud, usuario)


@router.post(
    "/{id_solicitud}/sedes",
    response_model=SedeSolicitudRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-021 · Agregar sede a la solicitud",
)
async def agregar_sede(
    id_solicitud: UUID,
    data: SedeIncluir,
    usuario: dict = Depends(requiere_permiso("SOL-021")),
    db: AsyncSession = Depends(get_db),
):
    """Incluye una sede activa que la empresa ya tiene registrada."""
    return await SedeService(db).incluir_existente(id_solicitud, data.id_sede, usuario)


# ============================================================
# SOL-024 — REGISTRAR SEDE NUEVA CON SU DIRECCIÓN
# ============================================================

@router.post(
    "/{id_solicitud}/sedes/nueva",
    response_model=SedeSolicitudRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-024 · Registrar dirección de sede",
)
async def registrar_sede_nueva(
    id_solicitud: UUID,
    data: SedeNueva,
    usuario: dict = Depends(requiere_permiso("SOL-024")),
    db: AsyncSession = Depends(get_db),
):
    """
    Registra la sede con su dirección, ciudad (SOL-026), departamento
    (SOL-027) y país, y la incluye en la solicitud. Ciudad, departamento y
    país no se pueden cambiar después.
    """
    return await SedeService(db).registrar_nueva(id_solicitud, data, usuario)


# ============================================================
# SOL-030 — EXPORTAR A EXCEL
# ============================================================

@router.get(
    "/{id_solicitud}/sedes/excel",
    summary="SOL-030 · Exportar sedes a Excel",
    response_class=Response,
)
async def exportar_sedes_excel(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-030")),
    db: AsyncSession = Depends(get_db),
):
    """Descarga un .xlsx con las sedes incluidas en la solicitud."""
    contenido, nombre = await SedeService(db).exportar_excel(id_solicitud, usuario)

    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ============================================================
# SOL-029 — VALIDAR SEDES (ADMINISTRACIÓN)
# ============================================================

@router.post(
    "/{id_solicitud}/sedes/validar",
    response_model=ValidacionSedes,
    summary="SOL-029 · Validar sedes (Administración)",
)
async def validar_sedes(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-029")),
    db: AsyncSession = Depends(get_db),
):
    """Marca cada sede como 'Validada' o 'Con observaciones' y lista las inconsistencias."""
    return await SedeService(db).validar(id_solicitud, usuario)


# ============================================================
# SOL-022 / SOL-025 — EDICIONES PERMITIDAS
# ============================================================

@router.patch(
    "/{id_solicitud}/sedes/{id_sede}",
    response_model=SedeSolicitudRespuesta,
    summary="SOL-022 · Editar sede en solicitud",
)
async def editar_sede(
    id_solicitud: UUID,
    id_sede: UUID,
    data: SedeEditar,
    usuario: dict = Depends(requiere_permiso("SOL-022")),
    db: AsyncSession = Depends(get_db),
):
    """Nombre o si es la sede principal."""
    return await SedeService(db).editar(id_solicitud, id_sede, data, usuario)


@router.patch(
    "/{id_solicitud}/sedes/{id_sede}/direccion",
    response_model=SedeSolicitudRespuesta,
    summary="SOL-025 · Editar dirección de sede",
)
async def editar_direccion(
    id_solicitud: UUID,
    id_sede: UUID,
    data: DireccionSede,
    usuario: dict = Depends(requiere_permiso("SOL-025")),
    db: AsyncSession = Depends(get_db),
):
    return await SedeService(db).editar_direccion(
        id_solicitud, id_sede, data.direccion, usuario
    )


# ============================================================
# SOL-023 — QUITAR O INACTIVAR
# ============================================================

@router.delete(
    "/{id_solicitud}/sedes/{id_sede}",
    summary="SOL-023 · Eliminar sede de la solicitud",
)
async def eliminar_sede(
    id_solicitud: UUID,
    id_sede: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-023")),
    db: AsyncSession = Depends(get_db),
):
    """Quita la sede de la solicitud; sigue activa en la empresa."""
    return await SedeService(db).eliminar(id_solicitud, id_sede, usuario)


@router.post(
    "/{id_solicitud}/sedes/{id_sede}/inactivar",
    summary="SOL-023 · Inactivar sede",
)
async def inactivar_sede(
    id_solicitud: UUID,
    id_sede: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-023")),
    db: AsyncSession = Depends(get_db),
):
    """
    Quita la sede de la solicitud y la marca 'Inactiva' en la empresa.
    Así se corrige una ciudad, departamento o país errados: se registra otra.
    """
    return await SedeService(db).inactivar(id_solicitud, id_sede, usuario)
