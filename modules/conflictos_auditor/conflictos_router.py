from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.conflictos_auditor.conflictos_service import ConflictoAuditorService

router = APIRouter(prefix="/conflictos-auditor", tags=["Conflictos de interés del auditor"])


@router.get("/usuario/{id_usuario}")
async def listar(id_usuario: UUID, db: AsyncSession = Depends(get_db)):
    return {"conflictos": await ConflictoAuditorService(db).listar_por_usuario(id_usuario)}


@router.delete("/{id_conflicto}")
async def eliminar(id_conflicto: UUID, id_usuario: UUID, db: AsyncSession = Depends(get_db)):
    return await ConflictoAuditorService(db).eliminar(id_usuario, id_conflicto)


@router.get("/empresas-restringidas")
async def empresas_restringidas(db: AsyncSession = Depends(get_db)):
    return {"empresas": await ConflictoAuditorService(db).empresas_restringidas()}


@router.post("/validar-asignacion")
async def validar_asignacion(data: dict, db: AsyncSession = Depends(get_db)):
    return await ConflictoAuditorService(db).validar_antes_asignacion(
        id_usuario=UUID(str(data.get("id_usuario"))),
        id_empresa=UUID(str(data.get("id_empresa"))),
    )
