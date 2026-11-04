from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user

from modules.mfa.mfa_service import MFAService
from modules.mfa.mfa_schema import (
    MFAVerifyRequest,
    MFADisableVerifyRequest
)


router = APIRouter(
    prefix="/mfa",
    tags=["Autenticación en dos pasos (MFA)"]
)


# ==========================================================
# Activar MFA (genera el código)
# ==========================================================
@router.post("/enable")
async def enable_mfa(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MFAService(db)

    return await service.enable(current_user)


# ==========================================================
# Verificar código y activar MFA
# ==========================================================
@router.post("/verify-enable")
async def verify_enable(
    data: MFAVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MFAService(db)

    return await service.verify_enable(
current_user,
data.codigo,
)

# ==========================================================
# Consultar estado de MFA
# ==========================================================
@router.get("/status")
async def mfa_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MFAService(db)

    return await service.get_status(current_user)


# ==========================================================
# Solicitar desactivación de MFA
# Genera y envía un código al correo
# ==========================================================
@router.post("/disable")
async def disable_mfa(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MFAService(db)

    return await service.disable(current_user)


# ==========================================================
# Verificar código y desactivar MFA
# ==========================================================
@router.post("/verify-disable")
async def verify_disable(
    data: MFADisableVerifyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = MFAService(db)

    return await service.verify_disable(
current_user,
data.codigo,
)