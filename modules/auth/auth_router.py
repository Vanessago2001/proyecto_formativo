from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.auth.auth_service import AuthService
from modules.auth.mail_service import MailService
from modules.auth.auth_schema import LoginRequest, CodigoRequest

router = APIRouter(prefix="/auth", tags=["Autenticación"])

@router.post("/login", status_code=status.HTTP_200_OK)
async def sign_in(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )

    service = AuthService(db)

    token = await service.login(
        payload.correo,
        payload.password,
        client_ip=client_ip
    )

    return {
        "access_token": token,
        "token_type": "bearer"
    }

@router.get("/test-mail")
async def test_mail():

    await MailService.enviar_codigo(
        destinatario="marlontaborda12@gmail.com",
        codigo="123456"
    )

    return {
        "mensaje": "Correo enviado correctamente"
    }

@router.post("/verificar-codigo")
async def verificar_codigo(
    datos: CodigoRequest,
    db: AsyncSession = Depends(get_db)
):
    service = AuthService(db)

    return await service.verificar_codigo(
        datos.correo,
        datos.codigo
    )