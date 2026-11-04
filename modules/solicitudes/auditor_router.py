"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 5 (asignación de auditores, SOL-041 a SOL-050).

SOL-042 a SOL-046 no tienen ruta propia: son los filtros de la búsqueda
(SOL-041), y cada uno se verifica solo cuando se pide, igual que SOL-024
hace con la ciudad y el departamento de una sede.

Donde la hoja marca REQ para el Auxiliar, la acción no se ejecuta: queda
registrada como pendiente de aprobación y la respuesta es 202.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.solicitudes import auditor_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.solicitudes.auditor_schema import (
    AsignacionRespuesta,
    MotivoAsignacion,
    PropuestaAuditor,
    ReasignacionAuditor,
)
from modules.solicitudes.auditor_service import AuditorSolicitudService
from modules.solicitudes.solicitud_permissions import (
    NivelPermiso,
    requiere_permiso,
)
from modules.solicitudes.solicitud_service import SolicitudService

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Asignación de auditores"],
)


def _requiere_aprobacion(usuario: dict) -> bool:
    """La hoja marcó REQ para el rol de quien pide la acción."""
    return usuario.get("permiso_nivel") == NivelPermiso.REQUIERE_APROBACION.value


async def _dejar_pendiente(
    db: AsyncSession, usuario: dict, codigo: str, id_solicitud: UUID, datos: dict, detalle: str
) -> JSONResponse:
    solicitud = await SolicitudService(db).consultar(id_solicitud, usuario)
    datos = {**datos, "id_solicitud": str(id_solicitud)}
    aprobacion = await AprobacionService(db).solicitar(
        codigo, str(solicitud["id_empresa"]), datos, detalle, usuario
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder({
            "mensaje": "La acción requiere aprobación de un superior. Quedó registrada como pendiente.",
            "aprobacion": aprobacion,
        }),
    )


# ============================================================
# SOL-041 — BUSCAR AUDITORES COMPETENTES (y SOL-042 a SOL-046)
# ============================================================

@router.get(
    "/{id_solicitud}/auditores/candidatos",
    summary="SOL-041 · Buscar auditores competentes (filtros SOL-042 a SOL-046)",
)
async def buscar_candidatos(
    id_solicitud: UUID,
    texto: Optional[str] = Query(default=None, description="Busca por nombre o correo"),
    norma: bool = Query(default=True, description="SOL-042 · exigir competencia en la norma"),
    sector_iaf: Optional[str] = Query(default=None, description="SOL-043 · sector IAF"),
    ciudad: Optional[str] = Query(default=None, description="SOL-044 · ciudad del auditor"),
    solo_disponibles: bool = Query(default=False, description="SOL-045 · con disponibilidad registrada"),
    excluir_conflictos: bool = Query(default=True, description="SOL-046 · descartar conflictos de interés"),
    usuario: dict = Depends(requiere_permiso("SOL-041")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorSolicitudService(db).buscar_candidatos(
        id_solicitud,
        usuario,
        texto=texto,
        filtrar_por_norma=norma,
        sector_iaf=sector_iaf,
        ciudad=ciudad,
        solo_disponibles=solo_disponibles,
        excluir_conflictos=excluir_conflictos,
    )


# ============================================================
# SOL-047 — PROPONER AUDITOR
# ============================================================

@router.get(
    "/{id_solicitud}/auditores",
    response_model=list[AsignacionRespuesta],
    summary="SOL-047 · Consultar los auditores propuestos y asignados",
)
async def listar_auditores(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-047")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorSolicitudService(db).listar(id_solicitud, usuario)


@router.post(
    "/{id_solicitud}/auditores",
    status_code=status.HTTP_201_CREATED,
    response_model=AsignacionRespuesta,
    summary="SOL-047 · Proponer auditor para el servicio",
)
async def proponer_auditor(
    id_solicitud: UUID,
    datos: PropuestaAuditor,
    usuario: dict = Depends(requiere_permiso("SOL-047")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorSolicitudService(db).proponer(
        id_solicitud,
        datos.id_auditor,
        usuario,
        especialidad=datos.especialidad,
        fecha_inicio=datos.fecha_inicio_planificada,
        fecha_fin=datos.fecha_fin_planificada,
    )


# ============================================================
# SOL-048 — APROBAR LA ASIGNACIÓN
# ============================================================

@router.post(
    "/{id_solicitud}/auditores/{id_asignacion}/aprobar",
    summary="SOL-048 · Aprobar asignación de auditor",
)
async def aprobar_asignacion(
    id_solicitud: UUID,
    id_asignacion: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-048")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-048", id_solicitud,
            {"id_asignacion": str(id_asignacion)},
            "Aprobar la asignación del auditor propuesto.",
        )
    return await AuditorSolicitudService(db).aprobar(id_solicitud, id_asignacion, usuario)


# ============================================================
# SOL-049 — REASIGNAR AUDITOR
# ============================================================

@router.post(
    "/{id_solicitud}/auditores/{id_asignacion}/reasignar",
    summary="SOL-049 · Reasignar auditor",
)
async def reasignar_auditor(
    id_solicitud: UUID,
    id_asignacion: UUID,
    datos: ReasignacionAuditor,
    usuario: dict = Depends(requiere_permiso("SOL-049")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-049", id_solicitud,
            {"id_asignacion": str(id_asignacion), "id_nuevo_auditor": str(datos.id_nuevo_auditor),
             "motivo": datos.motivo},
            f"Reasignar el auditor de la solicitud: {datos.motivo}",
        )
    return await AuditorSolicitudService(db).reasignar(
        id_solicitud, id_asignacion, datos.id_nuevo_auditor, datos.motivo, usuario
    )


# ============================================================
# SOL-050 — CANCELAR LA ASIGNACIÓN
# ============================================================

@router.post(
    "/{id_solicitud}/auditores/{id_asignacion}/cancelar",
    summary="SOL-050 · Cancelar asignación",
)
async def cancelar_asignacion(
    id_solicitud: UUID,
    id_asignacion: UUID,
    datos: MotivoAsignacion,
    usuario: dict = Depends(requiere_permiso("SOL-050")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-050", id_solicitud,
            {"id_asignacion": str(id_asignacion), "motivo": datos.motivo},
            f"Cancelar la asignación del auditor: {datos.motivo}",
        )
    return await AuditorSolicitudService(db).cancelar(
        id_solicitud, id_asignacion, datos.motivo, usuario
    )


# ============================================================
# HISTORIAL DE LAS ASIGNACIONES
# ============================================================

@router.get(
    "/{id_solicitud}/auditores/historial",
    summary="SOL-047 · Historial de propuestas, aprobaciones y cancelaciones",
)
async def historial_asignaciones(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-047")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorSolicitudService(db).historial(id_solicitud, usuario)
