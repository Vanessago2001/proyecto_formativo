"""Endpoints del mÃ³dulo administrativo de auditores registrados."""

from __future__ import annotations

import mimetypes
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_role
from modules.auditores_registrados.auditores_registrados_schema import (
    CambioEstadoAuditor,
)
from modules.auditores_registrados.auditores_registrados_service import (
    AuditoresRegistradosService,
)

router = APIRouter(
    prefix="/admin/auditores-registrados",
    tags=["Auditores registrados"],
)

# Consultar hojas de vida y documentos: administradores y auxiliares.
# Inactivar o reactivar: solo perfiles con permisos de administraciÃ³n.
require_lectura = require_role(["Administrador", "Super Administrador", "Auxiliar"])
require_escritura = require_role(["Administrador", "Super Administrador"])


@router.get("")
async def listar_auditores(
    q: str | None = Query(default=None, description="Nombre, documento o correo."),
    estado: str | None = Query(default=None, description="Activo o Inactivo."),
    current_user=Depends(require_lectura),
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
    current_user=Depends(require_lectura),
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
    current_user=Depends(require_lectura),
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
    current_user=Depends(require_lectura),
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
    current_user=Depends(require_lectura),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    ruta, nombre = await servicio.ruta_certificacion(id_usuario, id_certificacion)
    return _respuesta_archivo(ruta, nombre, descargar)


@router.get("/{id_usuario}/foto")
async def ver_foto_auditor(
    id_usuario: UUID,
    current_user=Depends(require_lectura),
    db: AsyncSession = Depends(get_db),
):
    servicio = AuditoresRegistradosService(db)
    ruta, nombre = await servicio.ruta_foto(id_usuario)
    tipo = mimetypes.guess_type(str(ruta))[0] or "image/jpeg"
    return FileResponse(path=str(ruta), media_type=tipo, filename=nombre)
