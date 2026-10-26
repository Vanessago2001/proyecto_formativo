from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.auth.dependencies import require_admin_access
from modules.administrar_auditores.administrar_auditores_service import AdministrarAuditoresService

router = APIRouter(prefix="/administradores/auditores", tags=["Administración de Auditores"])


@router.get("/conflictos")
async def listar_conflictos_general(
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return {
        "conflictos": await AdministrarAuditoresService(db).listar_conflictos_general()
    }

@router.get("/solicitudes")
async def listar_solicitudes(
    estado: str | None = Query(None),
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await AdministrarAuditoresService(db).listar_solicitudes(estado)

@router.get("/solicitudes/{id_postulacion}")
async def obtener_solicitud(
    id_postulacion: UUID,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await AdministrarAuditoresService(db).obtener_solicitud(id_postulacion)

@router.post("/documentos/{id_documento}/revision")
async def revisar_documento(
    id_documento: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    estado = str(data.get("estado_revision", "")).strip()
    observacion = str(data.get("observacion", "") or "")
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al administrador.")
    return await AdministrarAuditoresService(db).revisar_documento(
        id_documento=id_documento,
        estado_revision=estado,
        observacion=observacion,
        id_usuario_actor=UUID(str(actor)),
    )

@router.post("/competencias/{id_competencia}/revision")
async def revisar_competencia(
    id_competencia: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al administrador.")
    estado = str(data.get("estado_validacion", "")).strip()
    observacion = str(data.get("observacion", "") or "")
    return await AdministrarAuditoresService(db).revisar_validacion_competencia(
        id_competencia=id_competencia,
        estado_validacion=estado,
        observacion=observacion,
        id_usuario_actor=UUID(str(actor)),
    )

@router.patch("/solicitudes/{id_postulacion}/revision")
async def pasar_revision_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="En Revisión",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/correcciones")
async def solicitar_correcciones_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Correcciones",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/aprobar")
async def aprobar_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Aprobado",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/rechazar")
async def rechazar_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Rechazado",
        data=data,
        usuario=usuario,
        db=db,
    )

async def _ejecutar_alias_estado(
    id_postulacion: UUID,
    nuevo_estado: str,
    data: dict,
    usuario: dict,
    db: AsyncSession,
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al administrador.")
    observaciones = str(data.get("observaciones") or "")
    return await AdministrarAuditoresService(db).cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado=nuevo_estado,
        observaciones=observaciones,
        id_usuario_actor=UUID(str(actor)),
    )

@router.post("/solicitudes/{id_postulacion}/estado")
async def cambiar_estado(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al administrador.")
    return await AdministrarAuditoresService(db).cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado=str(data.get("nuevo_estado", "")).strip(),
        observaciones=str(data.get("observaciones", "") or ""),
        id_usuario_actor=UUID(str(actor)),
    )
