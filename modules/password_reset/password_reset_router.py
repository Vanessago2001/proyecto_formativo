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


# ============================================================
# 1. SOLICITAR RECUPERACIÓN
# ============================================================

@router.post("/request")
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    service = PasswordResetService(db)

    return await service.request_reset(
data.correo
)


# ============================================================
# 2. VERIFICAR CÓDIGO
# ============================================================

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


# ============================================================
# 3. CAMBIAR CONTRASEÑA
# ============================================================

@router.post("/reset")
async def reset_password(
    data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    service = PasswordResetService(db)

    return await service.reset_password(
data.token,
data.nueva_password,
)