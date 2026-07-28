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
        # 1. SOLICITAR RECUPERACIÓN DE CONTRASEÑA
        # ============================================================

    async def request_reset(self, correo: str):

        # Generar código de 6 dígitos
        codigo = str(random.randint(100000, 999999))

        # El código será válido durante 10 minutos
        expira = (
            datetime.now(timezone.utc)
            + timedelta(minutes=10)
        )

        # Buscar usuario
        result = await self.db.execute(
            text("""
            SELECT id
            FROM usuario
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        # Por seguridad, no indicamos si el correo existe
        if not usuario:
            return {
        "message": (
            "Si el correo existe, se enviará "
            "un código de verificación."
        )
    }

        # Guardar código en la base de datos
        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            codigo_verificacion = :codigo,
            codigo_expira = :expira,
            codigo_verificado = FALSE
            WHERE id = :id
            """),
            {
                "codigo": codigo,
                "expira": expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        # Enviar código al correo
        await MailService.enviar_codigo_recuperacion(
            destinatario=correo,
            codigo=codigo,
        )

        return {
            "message": (
                "Si el correo existe, se enviará "
                "un código de verificación."
            )
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
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        # Usuario no encontrado
        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

        # Código incorrecto
        if usuario["codigo_verificacion"] != codigo:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código incorrecto."
        )

        # No existe fecha de expiración
        if usuario["codigo_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código no existe."
        )

        # Verificar expiración
        ahora = datetime.now(timezone.utc)

        if usuario["codigo_expira"] < ahora:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ha expirado."
        )

        # Evitar reutilización
        if usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ya fue utilizado."
        )

        # ========================================================
        # GENERAR TOKEN SEGURO
        # ========================================================

        token = secrets.token_urlsafe(32)

        # Token válido durante 10 minutos
        token_expira = (
            datetime.now(timezone.utc)
            + timedelta(minutes=10)
        )

        # Guardar token en BD
        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            codigo_verificado = TRUE,
            token_recuperacion = :token,
            token_expira = :expira
            WHERE id = :id
            """),
            {
                "token": token,
                "expira": token_expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        # ========================================================
        # CREAR LINK DE RECUPERACIÓN
        # ========================================================

        link = (
            "http://127.0.0.1:8000/password-reset/new"
            f"?token={token}"
        )

        # ========================================================
        # ENVIAR LINK AL CORREO
        # ========================================================

        await MailService.enviar_link_recuperacion(
            destinatario=correo,
            link=link,
        )

        # No devolvemos el token directamente en la API
        return {
        "message": (
            "Código verificado correctamente. "
            "Se ha enviado un enlace de recuperación "
            "a tu correo."
        )
        }

    # ============================================================
    # 3. CAMBIAR CONTRASEÑA
    # ============================================================

    async def reset_password(
        self,
        token: str,
        password: str,
    ):

        # Buscar token
        result = await self.db.execute(
            text("""
            SELECT
            id,
            token_recuperacion,
            token_expira,
            codigo_verificado
            FROM usuario
            WHERE token_recuperacion = :token
            """),
            {
                "token": token
            },
        )

        usuario = result.mappings().first()

        # Token inexistente
        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación no es válido."
    )

        # Token sin expiración
        if usuario["token_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación no es válido."
        )

        # Verificar expiración
        ahora = datetime.now(timezone.utc)

        if usuario["token_expira"] < ahora:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El enlace de recuperación ha expirado."
        )

        # El código debe haberse verificado previamente
        if not usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Debe verificar primero el código "
            "enviado al correo."
        )
        )

        # ========================================================
        # GENERAR HASH DE LA NUEVA CONTRASEÑA
        # ========================================================

        nueva_contrasena = hash_password(password)

        # ========================================================
        # ACTUALIZAR CONTRASEÑA E INVALIDAR RECUPERACIÓN
        # ========================================================

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            contrasena = :contrasena,

            -- Limpiar código de recuperación
            codigo_verificacion = NULL,
            codigo_expira = NULL,
            codigo_verificado = FALSE,

            -- Invalidar token
            token_recuperacion = NULL,
            token_expira = NULL

            WHERE id = :id
            """),
            {
                "contrasena": nueva_contrasena,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        return {
        "message": "Contraseña actualizada correctamente."
        }