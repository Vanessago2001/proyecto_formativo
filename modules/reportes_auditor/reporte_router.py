from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.reportes_auditor.reporte_service import ReporteAuditorService

router = APIRouter(prefix="/reportes-auditor", tags=["Reportes del auditor"])


@router.get("/conflictos")
async def reporte_conflictos(db: AsyncSession = Depends(get_db)):
    return {
        "reporte": await ReporteAuditorService(db).reporte_conflictos()
    }


@router.get("/historial-academico/{id_usuario}")
async def reporte_historial(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ReporteAuditorService(db).reporte_historial_academico(id_usuario)
