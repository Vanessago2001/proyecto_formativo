"""REQ-AUD-001 — Router de Asignación de Auditores."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.asignacion_auditores.asignacion_schema import (
    AsignacionAuditorCrear,
    AuditoresElegiblesPagina,
    SolicitudCambioAsignacionCrear,
    SolicitudCambioAsignacionResolver,
)
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.solicitudes.solicitud_permissions import (
    ROL_ADM,
    ROL_AUX,
    ROL_EMP,
    normalizar_rol,
)

router = APIRouter(prefix="/asignacion-auditores", tags=["Asignación de Auditores"])

# Quién gestiona asignaciones (consultar, proponer, asignar).
ROLES_GESTION = {ROL_ADM, ROL_AUX}
# Cancelar una asignación o resolver una solicitud de cambio: solo el administrador.
ROLES_ADMINISTRADOR = {ROL_ADM}


async def requiere_gestion_asignaciones(usuario: dict = Depends(get_current_user)) -> dict:
    if normalizar_rol(usuario.get("role_name")) not in ROLES_GESTION:
        raise HTTPException(status_code=403, detail="No tiene permisos para gestionar asignaciones de auditores.")
    return usuario


async def requiere_administrador(usuario: dict = Depends(get_current_user)) -> dict:
    if normalizar_rol(usuario.get("role_name")) not in ROLES_ADMINISTRADOR:
        raise HTTPException(
            status_code=403,
            detail="Solo el Coordinador puede cancelar asignaciones o resolver solicitudes de cambio.",
        )
    return usuario


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
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    if desde and hasta and desde > hasta:
        raise HTTPException(
            status_code=422,
            detail="La fecha inicio no puede ser posterior a la fecha fin.",
        )
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
    usuario: dict = Depends(requiere_gestion_asignaciones),
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
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).asignar(data=data, usuario=usuario)


@router.get("/", summary="Consultar auditores asignados")
async def listar_asignaciones(
    id_solicitud: UUID | None = Query(default=None),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    servicio = AsignacionAuditorService(db)
    rol = normalizar_rol(usuario.get("role_name"))
    if rol in ROLES_GESTION:
        return await servicio.listar_asignaciones(id_solicitud=id_solicitud)
    if rol == ROL_EMP:
        # La empresa solo ve los auditores asignados a sus propias solicitudes.
        return await servicio.listar_asignaciones(
            id_solicitud=id_solicitud,
            empresas=await servicio.empresas_del_usuario(usuario),
        )
    raise HTTPException(status_code=403, detail="No tiene permisos para consultar asignaciones.")


@router.delete("/{id_asignacion}", summary="Cancelar asignación de auditor (solo Coordinador)")
async def cancelar_asignacion(
    id_asignacion: UUID,
    usuario: dict = Depends(requiere_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).cancelar_asignacion(id_asignacion, usuario=usuario)


# ------------------------------------------------------------
# Solicitudes de cambio: la empresa pide, el administrador decide
# ------------------------------------------------------------

@router.post(
    "/{id_asignacion}/solicitar-cambio",
    status_code=201,
    summary="La empresa solicita cambiar un auditor asignado, con razón justificada",
)
async def solicitar_cambio_asignacion(
    id_asignacion: UUID,
    data: SolicitudCambioAsignacionCrear,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if normalizar_rol(usuario.get("role_name")) != ROL_EMP:
        raise HTTPException(
            status_code=403,
            detail="Solo la empresa puede solicitar el cambio de un auditor asignado.",
        )
    return await AsignacionAuditorService(db).solicitar_cambio(id_asignacion, data.motivo, usuario)


@router.get("/solicitudes-cambio", summary="Consultar solicitudes de cambio de auditor")
async def listar_solicitudes_cambio(
    estado: str | None = Query(None, pattern="^(Pendiente|Aprobada|Rechazada)$"),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    servicio = AsignacionAuditorService(db)
    rol = normalizar_rol(usuario.get("role_name"))
    if rol in ROLES_GESTION:
        return await servicio.listar_solicitudes_cambio(estado=estado)
    if rol == ROL_EMP:
        return await servicio.listar_solicitudes_cambio(
            empresas=await servicio.empresas_del_usuario(usuario),
            estado=estado,
        )
    raise HTTPException(status_code=403, detail="No tiene permisos para consultar solicitudes de cambio.")


@router.post(
    "/solicitudes-cambio/{id_solicitud_cambio}/resolver",
    summary="El Coordinador aprueba o rechaza una solicitud de cambio",
)
async def resolver_solicitud_cambio(
    id_solicitud_cambio: UUID,
    data: SolicitudCambioAsignacionResolver,
    usuario: dict = Depends(requiere_administrador),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).resolver_solicitud_cambio(
        id_solicitud_cambio, data.aprobar, data.respuesta, usuario
    )
