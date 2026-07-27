from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.auth.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", status_code=status.HTTP_200_OK)
async def sign_in(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )

    service = AuthService(db)

    token = await service.login(
        form_data.username,
        form_data.password,
        client_ip=client_ip,
    )

    return {
"access_token": token,
"token_type": "bearer",
}


# ===========================
# SOLO PARA PRUEBAS
# ===========================

@router.get("/diagnostico-db")
async def diagnostico_db(
    db: AsyncSession = Depends(get_db),
):
    query = text("""
    SELECT
    correo,
    codigo_verificacion,
    codigo_expira,
    codigo_verificado
    FROM usuario
    WHERE correo = 'admin@empresa.com';
    """)

    result = await db.execute(query)

    return {
"usuarios": [
    dict(row)
    for row in result.mappings().all()
]
}