
from datetime import datetime, timedelta, timezone
from random import randint

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auth.mail_service import MailService


class MFAService:

    def __init__(self, db: AsyncSession):
        self.db = db

        # ============================================================
        # ACTIVAR MFA
        # ============================================================

    async def enable(self, current_user: dict):

        # --------------------------------------------------------
        # Obtener correo del usuario autenticado
        # --------------------------------------------------------

        correo = current_user["correo"]

        # --------------------------------------------------------
        # Buscar usuario en la base de datos
        # --------------------------------------------------------

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

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )
     # --------------------------------------------------------
        # Generar código MFA de 6 dígitos
        # --------------------------------------------------------
    
        codigo = str(randint(100000, 999999))
    
        # Código válido durante 10 minutos
        # --------------------------------------------------------
    
        expira = (
                datetime.now(timezone.utc)
                + timedelta(minutes=10)
            )
    
        # --------------------------------------------------------
        # Guardar código y expiración en la base de datos
        # --------------------------------------------------------
    
        await self.db.execute(
                text("""
                UPDATE usuario
                SET
                mfa_codigo = :codigo,
                mfa_expira = :expira,
                mfa_verificado = FALSE
                WHERE id = :id
                """),
                {
                    "codigo": codigo,
                    "expira": expira,
                    "id": usuario["id"],
                },
            )
    
        await self.db.commit()
    
        # --------------------------------------------------------
        # Enviar código al correo
        # --------------------------------------------------------
    
        await MailService.enviar_codigo_activar_mfa(
            destinatario=correo,
            codigo=codigo,
         )
    
        # --------------------------------------------------------
        # IMPORTANTE:
            # No devolver el código al frontend.
            # --------------------------------------------------------
    
        return {
            "message": "Código MFA enviado correctamente al correo."
        }  





    # ============================================================
    # LOGIN CON MFA
    # Genera un código y lo envía al correo
    # ============================================================

    async def login_request(self, correo: str):

        # --------------------------------------------------------
        # Buscar usuario
        # --------------------------------------------------------

        result = await self.db.execute(
            text("""
            SELECT id
            FROM usuario
            WHERE LOWER(correo)=LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado."
            )

        # --------------------------------------------------------
        # Generar código
        # --------------------------------------------------------

        codigo = str(randint(100000, 999999))

        expira = (
            datetime.now(timezone.utc)
            + timedelta(minutes=5)
        )

        # --------------------------------------------------------
        # Guardar código
        # --------------------------------------------------------

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
                "id": usuario["id"]
            },
        )
        print("UPDATE ejecutado")
        await self.db.commit()
        print("COMMIT realizado")

        # --------------------------------------------------------
        # Enviar correo
        # --------------------------------------------------------

        await MailService.enviar_codigo_login_mfa(
            destinatario=correo,
            codigo=codigo
        )

        return {
            "message": "Código MFA enviado."
        }

    



   

    # ============================================================
    # VERIFICAR CÓDIGO Y ACTIVAR MFA
    # ============================================================

    async def verify_enable(
        self,
        current_user: dict,
        codigo: str
    ):

        # --------------------------------------------------------
        # Obtener correo del usuario autenticado
        # --------------------------------------------------------

        correo = current_user["correo"]

        # --------------------------------------------------------
        # Buscar usuario y código pendiente
        # --------------------------------------------------------

        result = await self.db.execute(
            text("""
            SELECT
            id,
            mfa_codigo,
            mfa_expira,
            mfa_verificado
            FROM usuario
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

    # --------------------------------------------------------
    # Verificar que exista un código pendiente
    # --------------------------------------------------------

        if usuario["mfa_codigo"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No existe un código MFA pendiente."
        )

        # --------------------------------------------------------
        # Verificar que el código coincida
        # --------------------------------------------------------

        if usuario["mfa_codigo"] != codigo:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código incorrecto."
        )

        # --------------------------------------------------------
        # Verificar que exista fecha de expiración
        # --------------------------------------------------------

        if usuario["mfa_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA no tiene fecha de expiración."
        )

        # --------------------------------------------------------
        # Verificar que el código no haya expirado
        # --------------------------------------------------------

        if usuario["mfa_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA expiró."
        )

        # --------------------------------------------------------
        # Evitar reutilización del código
        # --------------------------------------------------------

        if usuario["mfa_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA ya fue utilizado."
        )

        # --------------------------------------------------------
        # Activar MFA
        # --------------------------------------------------------

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
            {
                "id": usuario["id"]
            },
        )

        await self.db.commit()

        return {
        "message": (
            "Autenticación en dos pasos "
            "activada correctamente."
        )
        }

    async def get_status(self, current_user: dict):

        correo = current_user["correo"]

        result = await self.db.execute(
            text("""
            SELECT mfa_activado
            FROM usuario
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

        return {
            "mfa_activado": bool(usuario["mfa_activado"])
        }


        # ============================================================
    # SOLICITAR DESACTIVACIÓN DE MFA
    # ============================================================

    async def disable(self, current_user: dict):
        print("===== ENTRÓ A DISABLE =====")
        print(current_user)

        # --------------------------------------------------------
        # Obtener correo del usuario autenticado
        # --------------------------------------------------------

        correo = current_user["correo"]

        # --------------------------------------------------------
        # Buscar usuario y comprobar que MFA esté activo
        # --------------------------------------------------------

        result = await self.db.execute(
            text("""
            SELECT
            id,
            mfa_activado
            FROM usuario
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

    # --------------------------------------------------------
    # Comprobar que MFA esté actualmente activado
    # --------------------------------------------------------

        if not usuario["mfa_activado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="La autenticación en dos pasos ya está desactivada."
        )

        # --------------------------------------------------------
        # Generar código de 6 dígitos
        # --------------------------------------------------------

        codigo = str(randint(100000, 999999))

        # --------------------------------------------------------
        # Código válido durante 10 minutos
        # --------------------------------------------------------

        expira = (
            datetime.now(timezone.utc)
            + timedelta(minutes=10)
        )

        # --------------------------------------------------------
        # Guardar código en la base de datos
        # --------------------------------------------------------

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            mfa_codigo = :codigo,
            mfa_expira = :expira,
            mfa_verificado = FALSE
            WHERE id = :id
            """),
            {
                "codigo": codigo,
                "expira": expira,
                "id": usuario["id"],
            },
        )

        await self.db.commit()

        # --------------------------------------------------------
        # Enviar código al correo del usuario
        # --------------------------------------------------------
        print("Generando correo para:", correo)
        await MailService.enviar_codigo_desactivar_mfa(
            destinatario=correo,
            codigo=codigo,
        )
        print("Correo enviado")

        return {
        "message": "Código para desactivar MFA enviado correctamente al correo."
        } 

        # ============================================================
    # VERIFICAR CÓDIGO Y DESACTIVAR MFA
    # ============================================================

    async def verify_disable(
        self,
        current_user: dict,
        codigo: str
    ):

        # --------------------------------------------------------
        # Obtener correo del usuario autenticado
        # --------------------------------------------------------

        correo = current_user["correo"]

        # --------------------------------------------------------
        # Buscar usuario y código pendiente
        # --------------------------------------------------------

        result = await self.db.execute(
            text("""
            SELECT
            id,
            mfa_activado,
            mfa_codigo,
            mfa_expira,
            mfa_verificado
            FROM usuario
            WHERE LOWER(correo) = LOWER(:correo)
            """),
            {
                "correo": correo
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Usuario no encontrado."
    )

    # --------------------------------------------------------
    # Comprobar que MFA esté activo
    # --------------------------------------------------------

        if not usuario["mfa_activado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="La autenticación en dos pasos ya está desactivada."
        )

        # --------------------------------------------------------
        # Comprobar que exista código
        # --------------------------------------------------------

        if usuario["mfa_codigo"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No existe un código MFA pendiente."
        )

        # --------------------------------------------------------
        # Verificar código
        # --------------------------------------------------------

        if usuario["mfa_codigo"] != codigo:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código incorrecto."
        )

        # --------------------------------------------------------
        # Comprobar fecha de expiración
        # --------------------------------------------------------

        if usuario["mfa_expira"] is None:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA no tiene fecha de expiración."
        )

        # --------------------------------------------------------
        # Comprobar que el código no haya expirado
        # --------------------------------------------------------

        if usuario["mfa_expira"] < datetime.now(timezone.utc):
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA expiró."
        )

        # --------------------------------------------------------
        # Evitar reutilización del código
        # --------------------------------------------------------

        if usuario["mfa_verificado"]:
            raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código MFA ya fue utilizado."
        )

        # --------------------------------------------------------
        # DESACTIVAR MFA
        # --------------------------------------------------------

        await self.db.execute(
            text("""
            UPDATE usuario
            SET
            mfa_activado = FALSE,
            mfa_verificado = FALSE,
            mfa_codigo = NULL,
            mfa_expira = NULL
            WHERE id = :id
            """),
            {
                "id": usuario["id"]
            },
        )

        await self.db.commit()

        return {
        "message": (
            "Autenticación en dos pasos "
            "desactivada correctamente."
        )
        }