"""REQ-AUD-001 — Router de Asignación de Auditores."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import es_coordinador, get_current_user
from modules.asignacion_auditores.asignacion_schema import (
    AsignacionAuditorCrear,
    AuditoresElegiblesPagina,
    SolicitudCambioAsignacionCrear,
    SolicitudCambioAsignacionResolver,
)
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.permisos_auxiliar.permisos_auxiliar_service import (
    auxiliar_tiene_permiso,
    registrar_uso,
)
from modules.permisos_auxiliar.regla_auxiliar import exigir_permiso_auxiliar
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


# El Auxiliar no tiene permisos propios (regla_auxiliar): consultar las
# etapas y los candidatos pide SOL-006 o SOL-041..SOL-047 delegado; asignar
# (POST), SOL-047 (proponer) o SOL-048 (aprobar asignación). "Asignar de todas
# formas" sigue pidiendo SOL-048.
PERMISOS_AUXILIAR_CONSULTA = ("SOL-006", "SOL-041", "SOL-042", "SOL-043", "SOL-044", "SOL-045", "SOL-046", "SOL-047")
PERMISOS_AUXILIAR_ASIGNAR = ("SOL-047", "SOL-048")


async def requiere_gestion_asignaciones(request: Request, usuario: dict = Depends(get_current_user)) -> dict:
    if normalizar_rol(usuario.get("role_name")) not in ROLES_GESTION:
        raise HTTPException(status_code=403, detail="No tiene permisos para gestionar asignaciones de auditores.")
    exigir_permiso_auxiliar(
        usuario,
        *(PERMISOS_AUXILIAR_CONSULTA if request.method in ("GET", "HEAD") else PERMISOS_AUXILIAR_ASIGNAR),
    )
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
    departamento: str | None = Query(None, max_length=100),
    pais: str | None = Query(None, max_length=100),
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
        departamento=departamento,
        pais=pais,
    )


@router.get("/ubicaciones", summary="Sugerencias de ciudad, departamento y país para los filtros")
async def sugerencias_ubicacion(
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).sugerencias_ubicacion()


@router.get("/conteo-etapas", summary="Contadores de las etapas de la pantalla Solicitudes")
async def conteo_etapas(
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    """Radicadas, en revisión, por asignar auditor, con auditores y todas (solo lectura)."""
    return await AsignacionAuditorService(db).conteo_etapas()


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
    departamento: str | None = Query(None, max_length=100),
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
        departamento=departamento,
    )


# Permiso delegable al Auxiliar para "Asignar de todas formas" (aprobar una
# asignación que no cumple la elegibilidad).
PERMISO_FORZAR_ASIGNACION = "SOL-048"


@router.get(
    "/solicitudes/{id_solicitud}/auditores/{id_auditor}/elegibilidad",
    summary="Razones de no elegibilidad y si la asignación se puede forzar",
)
async def elegibilidad_auditor(
    id_solicitud: UUID,
    id_auditor: UUID,
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    return await AsignacionAuditorService(db).elegibilidad(id_solicitud, id_auditor)


@router.post("/", summary="Asignar auditor a solicitud (rol único: Auditor)")
async def asignar_auditor(
    data: AsignacionAuditorCrear,
    usuario: dict = Depends(requiere_gestion_asignaciones),
    db: AsyncSession = Depends(get_db),
):
    origen = "Coordinador"
    if data.forzar:
        id_usuario = usuario.get("id_usuario") or usuario.get("user_id")
        if es_coordinador(usuario):
            origen = "Coordinador"
        elif normalizar_rol(usuario.get("role_name")) == ROL_AUX and await auxiliar_tiene_permiso(
            db, id_usuario, PERMISO_FORZAR_ASIGNACION
        ):
            origen = f"Auxiliar (permiso {PERMISO_FORZAR_ASIGNACION})"
        else:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Solo el Coordinador (o un Auxiliar con el permiso delegado "
                    f"{PERMISO_FORZAR_ASIGNACION}) puede asignar un auditor que no es elegible."
                ),
            )
    respuesta = await AsignacionAuditorService(db).asignar(data=data, usuario=usuario, origen_forzado=origen)
    if data.forzar and origen.startswith("Auxiliar"):
        await registrar_uso(
            db, usuario.get("id_usuario"), PERMISO_FORZAR_ASIGNACION,
            detalle=f"Asignación forzada del auditor {data.id_auditor} en la solicitud {data.id_solicitud}",
        )
    return respuesta


@router.get("/", summary="Consultar auditores asignados")
async def listar_asignaciones(
    id_solicitud: UUID | None = Query(default=None),
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    servicio = AsignacionAuditorService(db)
    rol = normalizar_rol(usuario.get("role_name"))
    if rol in ROLES_GESTION:
        exigir_permiso_auxiliar(usuario, *PERMISOS_AUXILIAR_CONSULTA, "SOL-051")
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


class RetiroPorConflicto(BaseModel):
    motivo: str | None = Field(default=None, max_length=1000)


@router.post(
    "/{id_asignacion}/retirar-por-conflicto",
    summary="Cancela la asignación de un auditor con conflicto de interés (solo Coordinador)",
)
async def retirar_por_conflicto(
    id_asignacion: UUID,
    data: RetiroPorConflicto | None = None,
    usuario: dict = Depends(requiere_administrador),
    db: AsyncSession = Depends(get_db),
):
    """Funciona aunque la solicitud tenga visita programada: quita al auditor
    de la visita con las reglas de Agenda y deja la asignación cancelada."""
    return await AsignacionAuditorService(db).retirar_por_conflicto(
        id_asignacion, usuario=usuario, motivo=(data.motivo if data else None)
    )


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
        exigir_permiso_auxiliar(usuario, "SOL-006", "SOL-049", "SOL-050")
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
