"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 1 (SOL-001 a SOL-010).

Cada ruta declara el código de permiso de la matriz del Excel mediante
`requiere_permiso(...)`, que además entrega el usuario autenticado.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.solicitudes.solicitud_pdf import generar_pdf_solicitud
from modules.solicitudes.solicitud_permissions import requiere_permiso
from modules.solicitudes.solicitud_schema import (
    EstadoSolicitud,
    SolicitudCancelar,
    SolicitudCrear,
    SolicitudEditar,
    SolicitudEstadoRespuesta,
    SolicitudRespuesta,
)
from modules.solicitudes.solicitud_service import SolicitudService

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Gestión de Solicitudes"],
)


# ============================================================
# SOL-001 / SOL-002 — CREAR Y GUARDAR BORRADOR
# ============================================================

@router.post(
    "/",
    response_model=SolicitudRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-001 · Crear solicitud",
)
async def crear_solicitud(
    data: SolicitudCrear,
    usuario: dict = Depends(requiere_permiso("SOL-001")),
    db: AsyncSession = Depends(get_db),
):
    """Crea la solicitud en estado BORRADOR."""
    service = SolicitudService(db)
    return await service.crear_borrador(data, usuario)


@router.post(
    "/borradores",
    response_model=SolicitudRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-002 · Guardar borrador",
)
async def guardar_borrador(
    data: SolicitudCrear,
    usuario: dict = Depends(requiere_permiso("SOL-002")),
    db: AsyncSession = Depends(get_db),
):
    """
    Guarda un borrador sin intención de radicarlo todavía.

    Comparte la operación con SOL-001; se expone aparte porque la matriz de
    permisos los trata como dos permisos distintos.
    """
    service = SolicitudService(db)
    return await service.crear_borrador(data, usuario)


# ============================================================
# SOL-006 — CONSULTAR (listado)
# ============================================================

@router.get(
    "/",
    response_model=list[SolicitudRespuesta],
    summary="SOL-006 · Consultar solicitudes",
)
async def listar_solicitudes(
    estado: EstadoSolicitud | None = Query(
        default=None,
        description="Filtra por estado del ciclo de vida.",
    ),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista las solicitudes visibles para el rol autenticado.

    La empresa recibe únicamente las suyas.
    """
    service = SolicitudService(db)
    return await service.listar(usuario, estado, limite, desplazamiento)


# ============================================================
# CATÁLOGO DE NORMAS
# ============================================================
# Debe declararse ANTES de "/{id_solicitud}": si no, el enrutador intentaría
# interpretar "normas" como un UUID y respondería 422.

@router.get(
    "/normas",
    summary="Consultar las normas ISO disponibles",
)
async def listar_normas(
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    """
    Normas de la tabla `norma`, para poblar el selector del formulario.

    Es una consulta de catálogo, no una acción sobre una solicitud, así que
    se protege con el mismo permiso de consulta (SOL-006).
    """
    resultado = await db.execute(
        text("""
            SELECT id_norma, codigo, nombre, version
            FROM norma
            ORDER BY codigo, nombre;
        """)
    )
    return [dict(fila) for fila in resultado.mappings().all()]


@router.get(
    "/{id_solicitud}",
    response_model=SolicitudRespuesta,
    summary="SOL-006 · Consultar solicitud radicada",
)
async def consultar_solicitud(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    """Detalle completo de una solicitud."""
    service = SolicitudService(db)
    return await service.consultar(id_solicitud, usuario)


# ============================================================
# SOL-010 — CONSULTAR ESTADO
# ============================================================

@router.get(
    "/{id_solicitud}/estado",
    response_model=SolicitudEstadoRespuesta,
    summary="SOL-010 · Consultar estado de solicitud",
)
async def consultar_estado(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-010")),
    db: AsyncSession = Depends(get_db),
):
    """Vista reducida: estado actual y fechas del trámite."""
    service = SolicitudService(db)
    return await service.consultar_estado(id_solicitud, usuario)


# ============================================================
# SOL-007 — DESCARGAR EN PDF
# ============================================================

@router.get(
    "/{id_solicitud}/pdf",
    summary="SOL-007 · Descargar solicitud en PDF",
    response_class=Response,
)
async def descargar_pdf(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-007")),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve la solicitud como archivo PDF descargable."""
    service = SolicitudService(db)
    # Se usa la consulta ampliada para que el PDF muestre el nombre y el NIT
    # de la empresa y el codigo de la norma, no sus identificadores internos.
    solicitud = await service.consultar_ampliada(id_solicitud, usuario)

    pdf = generar_pdf_solicitud(solicitud)
    nombre = solicitud.get("numero_radicado") or f"borrador-{id_solicitud}"

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}.pdf"',
        },
    )


# ============================================================
# SOL-003 — EDITAR BORRADOR
# ============================================================

@router.patch(
    "/{id_solicitud}",
    response_model=SolicitudRespuesta,
    summary="SOL-003 · Editar borrador",
)
async def editar_borrador(
    id_solicitud: UUID,
    data: SolicitudEditar,
    usuario: dict = Depends(requiere_permiso("SOL-003")),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza los campos enviados mientras la solicitud siga en BORRADOR."""
    service = SolicitudService(db)
    return await service.editar_borrador(id_solicitud, data, usuario)


# ============================================================
# SOL-004 — ELIMINAR BORRADOR
# ============================================================

@router.delete(
    "/{id_solicitud}",
    summary="SOL-004 · Eliminar borrador",
)
async def eliminar_borrador(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-004")),
    db: AsyncSession = Depends(get_db),
):
    """Borrado lógico del borrador; el expediente queda auditable."""
    service = SolicitudService(db)
    return await service.eliminar_borrador(id_solicitud, usuario)


# ============================================================
# SOL-005 — RADICAR FORMALMENTE
# ============================================================

@router.post(
    "/{id_solicitud}/radicar",
    response_model=SolicitudRespuesta,
    summary="SOL-005 · Radicar solicitud formalmente",
)
async def radicar_solicitud(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-005")),
    db: AsyncSession = Depends(get_db),
):
    """Asigna número de radicado y congela la edición."""
    service = SolicitudService(db)
    return await service.radicar(id_solicitud, usuario)


# ============================================================
# SOL-008 — DUPLICAR
# ============================================================

@router.post(
    "/{id_solicitud}/duplicar",
    response_model=SolicitudRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-008 · Duplicar solicitud",
)
async def duplicar_solicitud(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-008")),
    db: AsyncSession = Depends(get_db),
):
    """Crea un borrador nuevo con los mismos datos técnicos."""
    service = SolicitudService(db)
    return await service.duplicar(id_solicitud, usuario)


# ============================================================
# SOL-009 — CANCELAR ANTES DE REVISIÓN
# ============================================================

@router.post(
    "/{id_solicitud}/cancelar",
    response_model=SolicitudRespuesta,
    summary="SOL-009 · Cancelar solicitud antes de revisión",
)
async def cancelar_solicitud(
    id_solicitud: UUID,
    data: SolicitudCancelar,
    usuario: dict = Depends(requiere_permiso("SOL-009")),
    db: AsyncSession = Depends(get_db),
):
    """Retira la solicitud mientras no haya entrado en revisión."""
    service = SolicitudService(db)
    return await service.cancelar(id_solicitud, data, usuario)
