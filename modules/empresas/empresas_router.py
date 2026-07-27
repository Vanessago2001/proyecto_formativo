from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.empresas.empresas_service import EmpresasService

router = APIRouter(prefix="/empresas", tags=["Empresas"])


@router.get("/all")
async def read_empresas(
    db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    if current_user.get("role_name") != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso exclusivo para administradores.")
    return await EmpresasService(db).get_all_empresas()
