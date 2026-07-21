from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.auth.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Autenticación"])


class LoginRequest(BaseModel):
    correo: str = Field(..., min_length=3, description="Correo con el que se intenta ingresar")
    password: str = Field(..., min_length=1, description="Contraseña del usuario")


@router.post("/login", status_code=status.HTTP_200_OK)
async def sign_in(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    service = AuthService(db)
    token = await service.login(payload.correo, payload.password, client_ip=client_ip)
    return {"access_token": token, "token_type": "bearer"}
