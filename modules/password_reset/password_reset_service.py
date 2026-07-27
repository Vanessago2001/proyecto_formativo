import random
from datetime import datetime, timedelta, timezone
from core.security import hash_password
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PasswordResetService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def request_reset(self, correo: str):
        # Aquí iría la lógica para generar un código de verificación y enviarlo al correo del usuario
        codigo = str(random.randint(100000, 999999))  # Genera un código de 6 dígitos
        expira = datetime.now() + timedelta(minutes=10)  # Código válido por 10 minutos

        usuario = await self.db.execute(
            text(""" SELECT id FROM usuario 
              WHERE LOWER(correo)=LOWER(:correo)"""),
            {"correo": correo},
        )

        usuario = usuario.mappings().first()

        # Siempre respondemos igual por seguridad
        if not usuario:
            return {"message": "Si el correo existe, se enviará un código de verificación."}

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
        #solo para pruebas
        return {"message": "Si el correo existe, se enviará un código de verificación.", "codigo": codigo}

        
    # Verifica el código de verificación proporcionado por el usuario
    async def verify_code(self, correo: str, codigo: str):

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

        print("Hora actual:", datetime.now(timezone.utc))
        print("Expira:", usuario["codigo_expira"])
        print("Tipo:", type(usuario["codigo_expira"]))

        if usuario["codigo_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ha expirado."
        )

        if usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ya fue utilizado."
        )

        await self.db.execute(
            text("""
            UPDATE usuario
            SET codigo_verificado = TRUE
            WHERE id = :id
            """),
            {
                "id": usuario["id"]
            },
        )

        await self.db.commit()

        return {
        "message": "Código válido."
        }

    # Cambia la contraseña del usuario
    
    async def reset_password(
        self,
        correo: str,
        codigo: str,
        password: str,
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

        if usuario["codigo_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código ha expirado."
        )

        if not usuario["codigo_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Debe verificar primero el código."
        )

        nueva_contrasena = hash_password(password)

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            contrasena = :contrasena,
            codigo_verificacion = NULL,
            codigo_expira = NULL,
            codigo_verificado = FALSE
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
