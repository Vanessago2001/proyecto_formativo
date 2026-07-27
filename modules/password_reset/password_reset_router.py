from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.password_reset.password_reset_schema import (
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetVerify,
)
from modules.password_reset.password_reset_service import (
    PasswordResetService,
)

router = APIRouter(
    prefix="/password-reset",
    tags=["Recuperación de contraseña"],
)


@router.post("/request")
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    service = PasswordResetService(db)
    return await service.request_reset(data.correo)

# Verifica el código de verificación
@router.post("/verify")
async def verify_password_code(
    data: PasswordResetVerify,
    db: AsyncSession = Depends(get_db),
):
    service = PasswordResetService(db)
    return await service.verify_code(
data.correo,
data.codigo,
)

# Confirma el cambio de contraseña
@router.post("/reset")
async def reset_password(
    data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    service = PasswordResetService(db)

    return await service.reset_password(
        data.correo,
        data.codigo,
        data.nueva_password,
)