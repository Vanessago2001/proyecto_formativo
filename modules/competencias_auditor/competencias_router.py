from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.auth.dependencies import require_auditor_aprobado, require_self_or_admin_con
from modules.competencias_auditor.competencias_service import CompetenciaAuditorService

router = APIRouter(prefix="/competencias-auditor", tags=["Competencias del auditor"])


@router.get("/catalogo")
async def catalogo(db: AsyncSession = Depends(get_db)):
    return {"catalogo": await CompetenciaAuditorService(db).consultar_catalogo()}


@router.get("/sectores-iaf")
async def sectores_iaf(db: AsyncSession = Depends(get_db)):
    return {"sectores": await CompetenciaAuditorService(db).consultar_sectores_iaf()}


@router.get("/historial-academico/{id_usuario}")
async def historial_academico(
    id_usuario: UUID,
    usuario: dict = Depends(require_self_or_admin_con("AUD-029")),
    db: AsyncSession = Depends(get_db),
):
    return await CompetenciaAuditorService(db).consultar_historial_academico(id_usuario)


# Pantalla "Catálogo de competencias": solo para el auditor ya aprobado. El
# catálogo de normas (/catalogo), que usa el formulario de registro, sigue abierto.
@router.get("/usuario/{id_usuario}")
async def listar_competencias_usuario(
    id_usuario: UUID,
    usuario: dict = Depends(require_self_or_admin_con("AUD-018", "AUD-024")),
    db: AsyncSession = Depends(get_db),
):
    return {"competencias": await CompetenciaAuditorService(db).listar_competencias(id_usuario)}
