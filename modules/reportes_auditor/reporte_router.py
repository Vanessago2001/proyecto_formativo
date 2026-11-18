from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.auth.dependencies import require_auditor_aprobado, require_self_or_admin_con
from modules.reportes_auditor.reporte_service import ReporteAuditorService
from modules.solicitudes.solicitud_permissions import requiere_permiso

# Reportes: un auditor sin registro aprobado no los consulta (require_auditor_aprobado).
router = APIRouter(
    prefix="/reportes-auditor",
    tags=["Reportes del auditor"],
    dependencies=[Depends(require_auditor_aprobado)],
)


@router.get("/conflictos")
async def reporte_conflictos(
    usuario: dict = Depends(requiere_permiso("SOL-006", auxiliar=("AUD-037", "AUD-033"))),
    db: AsyncSession = Depends(get_db),
):
    return {
        "reporte": await ReporteAuditorService(db).reporte_conflictos()
    }


@router.get("/conflictos/{id_usuario}")
async def reporte_conflictos_por_auditor(
    id_usuario: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006", auxiliar=("AUD-037", "AUD-033"))),
    db: AsyncSession = Depends(get_db),
):
    return await ReporteAuditorService(db).reporte_conflictos_por_auditor(id_usuario)


@router.get("/conflictos/{id_usuario}/pdf")
async def reporte_conflictos_por_auditor_pdf(
    id_usuario: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006", auxiliar=("AUD-037", "AUD-033"))),
    db: AsyncSession = Depends(get_db),
):
    pdf = await ReporteAuditorService(db).reporte_conflictos_por_auditor_pdf(id_usuario)
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=conflictos_{id_usuario}.pdf"
    })


@router.get("/historial-academico/{id_usuario}")
async def reporte_historial(
    id_usuario: UUID,
    usuario: dict = Depends(require_self_or_admin_con("AUD-029")),
    db: AsyncSession = Depends(get_db),
):
    return await ReporteAuditorService(db).reporte_historial_academico(id_usuario)
