from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user, require_role
from modules.apelaciones.apelaciones_service import ApelacionesService

router = APIRouter(prefix="/api/apelaciones", tags=["Apelaciones"])


class ApelacionCreate(BaseModel):
    id_solicitud: int
    motivo: str
    fallo: Optional[str] = None
    estado: Optional[str] = "RADICADA"


class ApelacionUpdate(BaseModel):
    id_solicitud: Optional[int] = None
    motivo: Optional[str] = None
    fallo: Optional[str] = None
    estado: Optional[str] = None


class EvidenciaCreate(BaseModel):
    id_usuario: int
    nombre_archivo: str
    tipo_evidencia: str
    url_archivo: str
    descripcion: Optional[str] = None


class HiloLegalCreate(BaseModel):
    observaciones: str


class AnalisisJuridicoCreate(BaseModel):
    analisis: str


class RequerimientoCreate(BaseModel):
    requerimiento: str


class DecisionCreate(BaseModel):
    decision: str


class BitacoraCreate(BaseModel):
    detalle: str


class CancelarApelacionRequest(BaseModel):
    estado: str = "CANCELADA"


@router.post("/", status_code=status.HTTP_201_CREATED)
async def registrar_apelacion(
    data: ApelacionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "empresa"]))
):
    return await ApelacionesService(db).create_apelacion(data.model_dump())


@router.post("/{id}/evidencias", status_code=status.HTTP_201_CREATED)
async def adjuntar_evidencias(
    id: int,
    data: EvidenciaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "empresa"]))
):
    updated = await ApelacionesService(db).add_evidence(id, data.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.put("/{id}")
async def editar_apelacion(
    id: int,
    data: ApelacionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "auditor"]))
):
    updated = await ApelacionesService(db).update_apelacion(id, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=400, detail="No se puede editar la apelación o ya fue revisada.")
    return updated


@router.get("/")
async def consultar_apelacion_radicada(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "empresa", "auditor", "auxiliar", "comite"]))
):
    return await ApelacionesService(db).get_all_apelaciones()


@router.get("/{id}/estado")
async def consultar_estado_tramite(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "empresa", "auditor", "auxiliar", "comite"]))
):
    apelacion = await ApelacionesService(db).get_apelacion_by_id(id)
    if not apelacion:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return {"id": apelacion["id"], "estado": apelacion["estado"]}


@router.patch("/{id}/cancelar")
async def cancelar_retirar_apelacion(
    id: int,
    data: Optional[CancelarApelacionRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "auditor"]))
):
    estado = (data.estado if data else CancelarApelacionRequest()).estado
    updated = await ApelacionesService(db).cancelar_apelacion(id, estado)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/hilo-legal", status_code=status.HTTP_201_CREATED)
# async def registrar_observaciones_hilo_legal(
#     id: int,
#     data: HiloLegalCreate,
#     db: AsyncSession = Depends(get_db),
#     current_user: dict = Depends(require_role(["superadmin", "admin", "auditor"]))
# ):
#     return await ApelacionesService(db).registrar_hilo_legal(id, data.observaciones)


@router.get("/{id}/historial")
async def consultar_historial_apelacion(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite"]))
):
    return await ApelacionesService(db).get_historial(id)


@router.get("/{id}/evidencias")
async def consultar_evidencias_previas(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "auditor", "comite"]))
):
    return await ApelacionesService(db).get_evidencias_previas(id)


# @router.post("/{id}/analisis-juridico", status_code=status.HTTP_201_CREATED)
# async def registrar_analisis_juridico(
#     id: int,
#     data: AnalisisJuridicoCreate,
#     db: AsyncSession = Depends(get_db),
#     current_user: dict = Depends(require_role(["superadmin", "admin", "auditor"]))
# ):
#     return await ApelacionesService(db).registrar_analisis_juridico(id, data.analisis)


@router.post("/{id}/solicitar-info", status_code=status.HTTP_201_CREATED)
async def solicitar_info_adicional(
    id: int,
    data: RequerimientoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar"]))
):
    return await ApelacionesService(db).solicitar_info_adicional(id, data.requerimiento)


@router.post("/{id}/decision-final", status_code=status.HTTP_201_CREATED)
async def registrar_decision_final(
    id: int,
    data: DecisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar"]))
):
    return await ApelacionesService(db).registrar_decision_final(id, data.decision)


@router.post("/{id}/aprobar")
async def aprobar_apelacion(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "APROBADA")
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/rechazar")
async def rechazar_apelacion(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "RECHAZADA")
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/notificar")
async def notificar_dictamen_final(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "NOTIFICADA")
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return {"mensaje": "Dictamen notificado exitosamente", "estado": updated["estado"]}


@router.post("/{id}/cerrar")
async def cerrar_apelacion_definitivamente(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "CERRADA")
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


# @router.post("/{id}/bitacora-cierre", status_code=status.HTTP_201_CREATED)
# async def registrar_cierre_bitacora(
#     id: int,
#     data: BitacoraCreate,
#     db: AsyncSession = Depends(get_db),
#     current_user: dict = Depends(require_role(["superadmin", "admin"]))
# ):
#     return await ApelacionesService(db).registrar_bitacora_cierre(id, data.detalle)