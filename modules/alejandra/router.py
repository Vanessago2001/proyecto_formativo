from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.security import get_current_user

from .cerrar_sesiones import cerrar_todas_las_sesiones
from .bloquear_usuario import bloquear_usuario_temporalmente
from .desbloquear_usuario import desbloquear_usuario

router = APIRouter(prefix="/alejandra/seguridad", tags=["Seguridad - Alejandra"])

@router.post("/cerrar-sesiones/{user_id}")
async def endpoint_cerrar_sesiones(
    user_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    exito = await cerrar_todas_las_sesiones(user_id, db)
    if not exito:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"message": "Todas las sesiones del usuario han sido cerradas correctamente."}

@router.post("/bloquear/{user_id}")
async def endpoint_bloquear_usuario(
    user_id: str, 
    minutos: int = 15, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    exito = await bloquear_usuario_temporalmente(user_id, db, minutos)
    if not exito:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"message": f"Usuario bloqueado temporalmente por {minutos} minutos."}

@router.post("/desbloquear/{user_id}")
async def endpoint_desbloquear_usuario(
    user_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    exito = await desbloquear_usuario(user_id, db)
    if not exito:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"message": "Usuario desbloqueado correctamente."}