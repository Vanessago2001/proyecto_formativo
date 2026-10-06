from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    HTTPException,
    status,
)
from sqlalchemy import text

from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

from modules.administrar_auditores.administrar_auditores_service import (
    AdministrarAuditoresService,
)


router = APIRouter(
    prefix="/administrar-auditores",
    tags=["Administrar Auditores"],
)


# ========================================================
# ESQUEMA PARA CAMBIO DE ESTADO
# ========================================================

class CambioEstadoAuditor(BaseModel):
    id_usuario_actor: UUID
    observaciones: str | None = None


# ========================================================
# BANCO DE AUDITORES
# LISTAR SOLICITUDES
# ========================================================

@router.get("/solicitudes")
async def listar_solicitudes_auditores(
    estado: str | None = Query(
        default=None,
        description="Filtrar por estado de la postulación",
    ),
    db: AsyncSession = Depends(get_db),
):
    service = AdministrarAuditoresService(db)

    return await service.listar_solicitudes(
        estado=estado,
    )


# ========================================================
# DETALLE DE UNA SOLICITUD
# ========================================================

@router.get("/solicitudes/{id_postulacion}")
async def obtener_solicitud_auditor(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AdministrarAuditoresService(db)

    return await service.obtener_solicitud(
        id_postulacion=id_postulacion,
    )


# ========================================================
# PASAR A EN REVISIÓN
# ========================================================

@router.patch(
    "/solicitudes/{id_postulacion}/revision"
)
async def pasar_a_revision(
    id_postulacion: UUID,
    data: CambioEstadoAuditor,
    db: AsyncSession = Depends(get_db),
):
    service = AdministrarAuditoresService(db)

    return await service.cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="En Revisión",
        observaciones=data.observaciones,
        id_usuario_actor=data.id_usuario_actor,
    )


# ========================================================
# SOLICITAR CORRECCIONES
# ========================================================

@router.patch(
    "/solicitudes/{id_postulacion}/correcciones"
)
async def solicitar_correcciones(
    id_postulacion: UUID,
    data: CambioEstadoAuditor,
    db: AsyncSession = Depends(get_db),
):
    if not data.observaciones or not data.observaciones.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Debe registrar las observaciones "
                "que debe corregir el auditor."
            ),
        )

    service = AdministrarAuditoresService(db)

    return await service.cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Correcciones",
        observaciones=data.observaciones.strip(),
        id_usuario_actor=data.id_usuario_actor,
    )

  


# ========================================================
# APROBAR AUDITOR
# ========================================================

@router.patch(
    "/solicitudes/{id_postulacion}/aprobar"
)
async def aprobar_auditor(
    id_postulacion: UUID,
    data: CambioEstadoAuditor,
    db: AsyncSession = Depends(get_db),
):
    service = AdministrarAuditoresService(db)

    return await service.cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Aprobado",
        observaciones=data.observaciones,
        id_usuario_actor=data.id_usuario_actor,
    )


# ========================================================
# RECHAZAR AUDITOR
# ========================================================

@router.patch(
    "/solicitudes/{id_postulacion}/rechazar"
)
async def rechazar_auditor(
    id_postulacion: UUID,
    data: CambioEstadoAuditor,
    db: AsyncSession = Depends(get_db),
):
    if not data.observaciones or not data.observaciones.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Debe registrar las observaciones "
                "que justifican el rechazo."
            ),
        )

    service = AdministrarAuditoresService(db)

    return await service.cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Rechazado",
        observaciones=data.observaciones.strip(),
        id_usuario_actor=data.id_usuario_actor,
    )


   

# consulta de historial de cambios de estado de una solicitud de auditor
@router.get(
    "/solicitudes/{id_postulacion}/historial"
)
async def obtener_historial_solicitud(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AdministrarAuditoresService(db)

    return await service.obtener_historial(
        id_postulacion=id_postulacion,
    )





@router.delete("/solicitudes/borradores-duplicados/{id_usuario}")
async def eliminar_borradores_duplicados(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        # Verificar que existan borradores para el usuario
        result = await db.execute(
            text("""
                SELECT id_postulacion
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                  AND estado = 'Borrador'
            """),
            {"id_usuario": id_usuario},
        )
        borradores = result.mappings().all()

        if not borradores:
            return {
                "ok": True,
                "mensaje": "No hay borradores para eliminar.",
                "documentos_eliminados": 0,
                "borradores_eliminados": 0,
            }

        # Eliminar documentos relacionados con los borradores
        result_documentos = await db.execute(
            text("""
                DELETE FROM documento_auditor
                WHERE id_postulacion IN (
                    SELECT id_postulacion
                    FROM postulacion_auditor
                    WHERE id_usuario = :id_usuario
                      AND estado = 'Borrador'
                )
            """),
            {"id_usuario": id_usuario},
        )
        documentos_eliminados = result_documentos.rowcount or 0

        # Eliminar los borradores
        result_borradores = await db.execute(
            text("""
                DELETE FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                  AND estado = 'Borrador'
            """),
            {"id_usuario": id_usuario},
        )
        borradores_eliminados = result_borradores.rowcount or 0

        await db.commit()

        return {
            "ok": True,
            "mensaje": "Los borradores y sus documentos relacionados fueron eliminados correctamente.",
            "documentos_eliminados": documentos_eliminados,
            "borradores_eliminados": borradores_eliminados,
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar los borradores: {str(e)}",
        )





