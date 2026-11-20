"""Endpoints del mÃ³dulo administrativo de auditores registrados."""

from __future__ import annotations

import mimetypes
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import es_coordinador, require_role
from modules.permisos_auxiliar.regla_auxiliar import delegable
from modules.auditores_registrados.auditores_registrados_schema import (
    ActivarAuditor,
    CambioEstadoAuditor,
)
from modules.auditores_registrados.auditores_registrados_service import (
    PERMISO_ACTIVAR_AUDITOR,
    AuditoresRegistradosService,
)

router = APIRouter(
    prefix="/admin/auditores-registrados",
    tags=["Auditores registrados"],
)

# Consultar hojas de vida y documentos: administradores y auxiliares.
# Inactivar o reactivar: solo perfiles con permisos de administraciÃ³n.
# El Auxiliar no tiene permisos propios: cada ruta pide su código delegado.
def require_lectura_con(*codigos: str):
    return require_role(["Coordinador", "Auxiliar"], auxiliar=delegable(*codigos))


require_lectura = require_lectura_con("AUD-056")
require_escritura = require_role(["Coordinador"])


@router.get("")
async def listar_auditores(
    q: str | None = Query(default=None, description="Nombre, documento o correo."),
    estado: str | None = Query(default=None, description="Activo o Inactivo."),
    current_user=Depends(require_lectura_con("AUD-056", "AUD-057", "AUD-058")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    auditores = await servicio.listar(busqueda=q, estado=estado)
    return {
        "total": len(auditores),
        "auditores": auditores,
    }


@router.get("/{id_usuario}")
async def obtener_auditor(
    id_usuario: UUID,
    current_user=Depends(require_lectura_con("AUD-056")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    return await servicio.obtener(id_usuario)


@router.patch("/{id_usuario}/estado")
async def cambiar_estado_auditor(
    id_usuario: UUID,
    payload: CambioEstadoAuditor,
    current_user=Depends(require_escritura),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    actor = current_user.get("id_usuario") or current_user.get("id") or current_user.get("user_id")
    actor_uuid = None
    if actor is not None:
        try:
            actor_uuid = UUID(str(actor))
        except (TypeError, ValueError):
            actor_uuid = None
    return await servicio.cambiar_estado(
        id_usuario,
        payload.estado,
        id_usuario_actor=actor_uuid,
    )


def _id_actor(current_user: dict) -> UUID | None:
    actor = current_user.get("id_usuario") or current_user.get("id") or current_user.get("user_id")
    if actor is None:
        return None
    try:
        return UUID(str(actor))
    except (TypeError, ValueError):
        return None


@router.post("/{id_usuario}/activar")
async def activar_auditor(
    id_usuario: UUID,
    payload: ActivarAuditor,
    current_user=Depends(require_lectura_con("AUD-013")),
    db: AsyncSession = Depends(get_db),
):
    """Activa al auditor cuya postulación vigente ya está aprobada.

    Coordinador siempre; Auxiliar solo con el permiso delegado AUD-013
    ("Aprobar auditor en el sistema"). 409 con el motivo si no aplica.
    """
    from modules.permisos_auxiliar.permisos_auxiliar_service import usar_permiso_delegado

    if not es_coordinador(current_user) and not await usar_permiso_delegado(
        db, current_user, PERMISO_ACTIVAR_AUDITOR,
        f"{PERMISO_ACTIVAR_AUDITOR} activar auditor {id_usuario}",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Esta acción requiere el permiso delegado {PERMISO_ACTIVAR_AUDITOR}. "
                "Solicítelo al Coordinador."
            ),
        )
    actor = _id_actor(current_user)
    if actor is None:
        raise HTTPException(status_code=401, detail="No fue posible identificar al coordinador.")
    return await AuditoresRegistradosService(db).activar_auditor(
        id_usuario, payload.motivo, id_usuario_actor=actor,
    )


@router.get("/{id_usuario}/asignaciones-afectadas")
async def previsualizar_asignaciones_afectadas(
    id_usuario: UUID,
    current_user=Depends(require_escritura),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    return await servicio.previsualizar_desactivacion(id_usuario)


@router.get("/{id_usuario}/historial-asignaciones")
async def historial_asignaciones_auditor(
    id_usuario: UUID,
    current_user=Depends(require_lectura_con("AUD-058")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    historial = await servicio.consultar_historial_asignaciones(id_usuario)
    return {
        "id_usuario": id_usuario,
        "total": len(historial),
        "historial": historial,
    }


# ----------------------------------------------------------------------
# ARCHIVOS PROTEGIDOS
# ----------------------------------------------------------------------


def _respuesta_archivo(
    ruta,
    nombre: str,
    descargar: bool,
) -> FileResponse:
    tipo = mimetypes.guess_type(str(ruta))[0] or "application/octet-stream"
    return FileResponse(
        path=str(ruta),
        media_type=tipo,
        filename=nombre,
        content_disposition_type="attachment" if descargar else "inline",
    )


@router.get("/{id_usuario}/documentos/{id_documento}/archivo")
async def ver_documento_auditor(
    id_usuario: UUID,
    id_documento: UUID,
    descargar: bool = Query(default=False),
    current_user=Depends(require_lectura_con("AUD-057", "AUD-012")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    ruta, nombre = await servicio.ruta_documento(id_usuario, id_documento)
    return _respuesta_archivo(ruta, nombre, descargar)


@router.get("/{id_usuario}/certificaciones/{id_certificacion}/archivo")
async def ver_certificacion_auditor(
    id_usuario: UUID,
    id_certificacion: UUID,
    descargar: bool = Query(default=False),
    current_user=Depends(require_lectura_con("AUD-057", "AUD-018")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    ruta, nombre = await servicio.ruta_certificacion(id_usuario, id_certificacion)
    return _respuesta_archivo(ruta, nombre, descargar)


@router.get("/{id_usuario}/foto")
async def ver_foto_auditor(
    id_usuario: UUID,
    current_user=Depends(require_lectura_con("AUD-056")),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    ruta, nombre = await servicio.ruta_foto(id_usuario)
    tipo = mimetypes.guess_type(str(ruta))[0] or "image/jpeg"
    return FileResponse(path=str(ruta), media_type=tipo, filename=nombre)
