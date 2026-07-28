from datetime import datetime, timedelta, timezone
from random import randint

from fastapi import HTTPException, status
from sqlalchemy import text

class MFAService:

    def __init__(self, db):
        self.db = db
    # generar un código MFA y guardarlo en la base de datos para el usuario especificado
    async def enable(self, current_user: dict):
        print("Usuario autenticado:", current_user)
        correo = current_user["correo"]
       

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
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

        codigo = f"{randint(100000,999999)}"

        expira = datetime.now(timezone.utc) + timedelta(minutes=10)

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            mfa_codigo=:codigo,
            mfa_expira=:expira,
            mfa_verificado=FALSE
            WHERE id=:id
            """),
            {
                "codigo": codigo,
                "expira": expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        return {
            "message": "Código MFA generado.",
            "codigo": codigo
        }
    #verificar el código MFA y activar la autenticación en dos pasos 
    async def verify_enable(self, current_user: dict, codigo: str):
        correo = current_user["correo"]
        result = await self.db.execute(
            text("""
            SELECT
            id,
            mfa_codigo,
            mfa_expira,
            mfa_verificado
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

        if usuario["mfa_codigo"] != codigo:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código incorrecto."
        )

        if usuario["mfa_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No existe un código pendiente."
        )

        if usuario["mfa_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código expiró."
        )

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            mfa_activado = TRUE,
            mfa_verificado = TRUE,
            mfa_codigo = NULL,
            mfa_expira = NULL
            WHERE id = :id
            """),
            {"id": usuario["id"]},
        )

        await self.db.commit()

        return {
        "message": "Autenticación en dos pasos activada correctamente."
        }