import random
import secrets

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password
from modules.auth.mail_service import MailService


class PasswordResetService:

    def __init__(self, db: AsyncSession):
        self.db = db

        # ============================================================
        # 1. SOLICITAR RECUPERACIÓN
        # ============================================================

    async def request_reset(self, correo: str):

        codigo = str(random.randint(100000, 999999))

        expira = datetime.now(timezone.utc) + timedelta(minutes=10)

        result = await self.db.execute(
            text("""
            SELECT id
            FROM usuario
            WHERE LOWER(correo)=LOWER(:correo)
            """),
            {"correo": correo},
        )

        usuario = result.mappings().first()

        if not usuario:
            return {
        "message": "Si el correo existe, se enviará un código de verificación."
    }

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            codigo_verificacion=:codigo,
            codigo_expira=:expira,
            codigo_verificado=FALSE
            WHERE id=:id
            """),
            {
                "codigo": codigo,
                "expira": expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        await MailService.enviar_codigo_recuperacion(
            destinatario=correo,
            codigo=codigo,
        )

        return {
            "message": "Si el correo existe, se enviará un código de verificación."
        }

    # ============================================================
    # 2. VERIFICAR CÓDIGO
    # ============================================================

    async def verify_code(
        self,
        correo: str,
        codigo: str,
    ):

        result = await self.db.execute(
            text("""
            SELECT
            id,
            codigo_verificacion,
            codigo_expira,
            codigo_verificado
            FROM usuario
            WHERE LOWER(correo)=LOWER(:correo)
            """),
            {"correo": correo},
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

        if usuario["codigo_verificacion"] != codigo:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código incorrecto."
        )

        if usuario["codigo_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código no existe."
        )

        ahora = datetime.now(timezone.utc)

        if usuario["codigo_expira"] < ahora:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ha expirado."
        )

        if usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ya fue utilizado."
        )

    # =====================================================
    # GENERAR TOKEN
    # =====================================================

        token = secrets.token_urlsafe(32)

        token_expira = datetime.now(timezone.utc) + timedelta(minutes=10)

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            codigo_verificado=TRUE,
            token_recuperacion=:token,
            token_expira=:expira
            WHERE id=:id
            """),
            {
                "token": token,
                "expira": token_expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

    # =====================================================
    # ENVIAR LINK (OPCIONAL)
    # =====================================================

        link = (
            f"http://127.0.0.1:8000/password-reset/new?token={token}"
        )

        await MailService.enviar_link_recuperacion(
            destinatario=correo,
            link=link,
        )

        # =====================================================
        # IMPORTANTE:
            # DEVOLVER EL TOKEN AL FRONTEND
            # =====================================================

        return {
        "message": "Código verificado correctamente.",
        "token": token
        }

    # ============================================================
    # 3. CAMBIAR CONTRASEÑA
    # ============================================================

    async def reset_password(
        self,
        token: str,
        password: str,
    ):

        result = await self.db.execute(
            text("""
            SELECT
            id,
            token_recuperacion,
            token_expira,
            codigo_verificado
            FROM usuario
            WHERE token_recuperacion=:token
            """),
            {"token": token},
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación no es válido."
    )

        if usuario["token_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación no es válido."
        )

        if usuario["token_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación ha expirado."
        )

        if not usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Debe verificar primero el código enviado al correo."
        )

        nueva_password = hash_password(password)

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            contrasena=:contrasena,

            codigo_verificacion=NULL,
            codigo_expira=NULL,
            codigo_verificado=FALSE,

            token_recuperacion=NULL,
            token_expira=NULL

            WHERE id=:id
            """),
            {
                "contrasena": nueva_password,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        return {
        "message": "Contraseña actualizada correctamente."
        }