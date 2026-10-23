from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.perfiles_auditor.perfil_service import PerfilAuditorService

router = APIRouter(prefix="/perfiles-auditor", tags=["Perfil del auditor"])


@router.get("/{id_usuario}")
async def obtener_perfil(id_usuario: UUID, db: AsyncSession = Depends(get_db)):
    return await PerfilAuditorService(db).obtener_perfil(id_usuario)
