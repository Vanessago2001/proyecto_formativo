from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_role
from modules.apelaciones.apelaciones_service import ApelacionesService

router = APIRouter(prefix="/api/apelaciones", tags=["Apelaciones"])


class ApelacionCreate(BaseModel):
    id_solicitud: UUID
    motivo: str = Field(..., min_length=10)


class ApelacionUpdate(BaseModel):
    motivo: Optional[str] = None


class RequerimientoCreate(BaseModel):
    """Lo que el Comité pide a la empresa para seguir con la apelación."""

    requerimiento: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Qué documentos debe adjuntar la empresa, en detalle.",
    )
    observaciones: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Nota interna opcional sobre el requerimiento.",
    )


class DecisionCreate(BaseModel):
    decision: str = Field(..., pattern=r"^(APROBADA|RECHAZADA|CANCELADA)$")
    observaciones: Optional[str] = None


class ComitéAssignmentRequest(BaseModel):
    miembros_comite: list[UUID] = Field(..., min_length=1)
    id_auditor_evaluador: Optional[UUID] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def registrar_apelacion(
    data: ApelacionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa"]))
):
    return await ApelacionesService(db).create_apelacion(data.model_dump(), current_user)


@router.get("/solicitud/{id_solicitud}/contexto")
async def contexto_de_solicitud(
    id_solicitud: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin", "auxiliar"]))
):
    """Si la solicitud se puede apelar y el motivo del rechazo del Comité."""
    return await ApelacionesService(db).contexto_de_solicitud(id_solicitud, current_user)


@router.get("/{id}")
async def consultar_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"]))
):
    apelacion = await ApelacionesService(db).get_apelacion_by_id(id, current_user)
    if not apelacion:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return apelacion


@router.get("/{id}/expediente")
async def consultar_expediente_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin", "auxiliar"]))
):
    """
    Expediente completo de la apelación: la solicitud original, la evaluación
    previa del Comité, la apelación y sus evidencias. Un miembro del Comité
    solo accede si pertenece al comité asignado a esta apelación.
    """
    return await ApelacionesService(db).expediente_apelacion(id, current_user)


@router.get("/{id}/comite-elegible")
async def consultar_comite_elegible(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin"]))
):
    """
    Miembros del Comité que el Administrador puede asignar a esta apelación.
    Los que ya evaluaron la solicitud original vienen marcados.
    """
    return await ApelacionesService(db).comite_elegible(id)


@router.post("/{id}/evidencias", status_code=status.HTTP_201_CREATED)
async def adjuntar_evidencias(
    id: UUID,
    archivos: list[UploadFile] = File(default=[]),
    archivo: Optional[UploadFile] = File(default=None),
    descripcion: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa"]))
):
    """
    Adjunta uno o varios documentos a la apelación.

    Se acepta `archivos` (varios) y también `archivo` (uno), que es como lo
    enviaba la pantalla anterior. En ningún caso se reemplazan las evidencias
    que ya estaban: cada envío suma.
    """
    recibidos = [a for a in list(archivos or []) if a and a.filename]
    if archivo is not None and archivo.filename:
        recibidos.append(archivo)

    if not recibidos:
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo.")

    resultado = await ApelacionesService(db).add_evidences(id, recibidos, descripcion, current_user)
    if not resultado:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return resultado


@router.put("/{id}")
async def editar_apelacion(
    id: UUID,
    data: ApelacionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa"]))
):
    updated = await ApelacionesService(db).update_apelacion(id, data.model_dump(exclude_unset=True), current_user)
    if not updated:
        raise HTTPException(status_code=400, detail="No se puede editar la apelación o ya fue revisada.")
    return updated


@router.get("/")
async def consultar_apelaciones_radicadas(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"]))
):
    return await ApelacionesService(db).get_all_apelaciones(current_user)


@router.get("/{id}/estado")
async def consultar_estado_tramite(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"]))
):
    apelacion = await ApelacionesService(db).get_apelacion_by_id(id, current_user)
    if not apelacion:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return {"id": apelacion["id"], "estado": apelacion["estado"], "radicado": apelacion.get("radicado")}


@router.patch("/{id}/cancelar")
async def cancelar_retirar_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa"]))
):
    updated = await ApelacionesService(db).cancelar_apelacion(id, current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada o no puede cancelarse en este estado.")
    return updated


@router.post("/{id}/asignar-comite", status_code=status.HTTP_200_OK)
async def asignar_comite_apelacion(
    id: UUID,
    data: ComitéAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    try:
        return await ApelacionesService(db).assign_committee(
            id,
            data.miembros_comite,
            data.id_auditor_evaluador,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{id}/historial")
async def consultar_historial_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"]))
):
    return await ApelacionesService(db).get_historial(id, current_user)


@router.get("/{id}/evidencias")
async def consultar_evidencias_previas(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"]))
):
    return await ApelacionesService(db).get_evidencias_previas(id, current_user)


@router.get("/{id}/evidencias/{id_evidencia}/archivo", response_class=FileResponse)
async def descargar_evidencia(
    id: UUID,
    id_evidencia: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin"])),
):
    archivo = await ApelacionesService(db).obtener_archivo_evidencia(id, id_evidencia, current_user)
    if not archivo:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada.")
    ruta, nombre = archivo
    return FileResponse(ruta, filename=nombre)


@router.get("/{id}/requerimientos")
async def consultar_requerimientos(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["empresa", "comite", "superadmin", "admin", "auxiliar"]))
):
    """Lo que el Comité ha pedido en esta apelación y si ya fue atendido."""
    return await ApelacionesService(db).listar_requerimientos(id, current_user)


@router.post("/{id}/solicitar-info", status_code=status.HTTP_201_CREATED)
async def solicitar_info_adicional(
    id: UUID,
    data: RequerimientoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).solicitar_info_adicional(
        id, data.requerimiento, current_user, data.observaciones
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/resolve", status_code=status.HTTP_200_OK)
async def resolver_apelacion(
    id: UUID,
    data: DecisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).registrar_decision_final(id, data.decision, data.observaciones, current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return {"id": id, "estado": data.decision, "observaciones": data.observaciones}


@router.post("/{id}/aprobar")
async def aprobar_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "APROBADA", current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/rechazar")
async def rechazar_apelacion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "RECHAZADA", current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated


@router.post("/{id}/notificar")
async def notificar_dictamen_final(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "NOTIFICADA", current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return {"mensaje": "Dictamen notificado exitosamente", "estado": updated["estado"]}


@router.post("/{id}/cerrar")
async def cerrar_apelacion_definitivamente(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["comite", "superadmin", "admin"]))
):
    updated = await ApelacionesService(db).cambiar_estado_dictamen(id, "CERRADA", current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Apelación no encontrada.")
    return updated