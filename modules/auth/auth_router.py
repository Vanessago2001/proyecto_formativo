from typing import Optional
from fastapi import APIRouter, Body, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.auth.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Autenticación"])


class LoginRequest(BaseModel):
  correo: str = Field(
      ...,
      min_length=3,
      description="Correo o usuario con el que se intenta ingresar",
  )
  password: str = Field(
      ..., min_length=1, description="Contraseña del usuario"
  )


@router.post("/login", status_code=status.HTTP_200_OK)
async def sign_in(
    request: Request,
    payload: Optional[LoginRequest] = Body(None),
    form_data: Optional[OAuth2PasswordRequestForm] = Depends(
        OAuth2PasswordRequestForm
    ),
    db: AsyncSession = Depends(get_db),
):
  client_ip = request.headers.get("x-forwarded-for") or (
      request.client.host if request.client else "unknown"
  )
  service = AuthService(db)

  user_identifier = None
  user_password = None

  # 1. Si los datos vienen desde el candado de Swagger (OAuth2 Form)
  if form_data and form_data.username:
    user_identifier = form_data.username
    user_password = form_data.password

  # 2. Si vienen mediante JSON directo enviado por el body
  elif payload:
    user_identifier = payload.correo
    user_password = payload.password

  # 3. Fallback por si envían un JSON crudo sin pasar por el parser de Pydantic
  else:
    try:
      body = await request.json()
      user_identifier = body.get("correo") or body.get("username")
      user_password = body.get("password")
    except Exception:
      pass

  # Si no se recibió ningún dato válido
  if not user_identifier or not user_password:
    from fastapi import HTTPException

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Se requieren credenciales válidas (correo/usuario y contraseña).",
    )

  token = await service.login(
      user_identifier, user_password, client_ip=client_ip
  )
  return {"access_token": token, "token_type": "bearer"}