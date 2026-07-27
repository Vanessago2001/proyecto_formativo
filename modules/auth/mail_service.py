from fastapi_mail import FastMail
from fastapi_mail import MessageSchema
from fastapi_mail import MessageType

from core.mail import conf


class MailService:

    @staticmethod
    async def enviar_codigo(destinatario: str, codigo: str):

        mensaje = MessageSchema(

            subject="Código de verificación - CertiSENA ISO",

            recipients=[destinatario],

            body=f"""
Buen dia.

Detectamos múltiples intentos fallidos de inicio de sesión.

Tu código de verificación es:

{codigo}

Este código estará disponible durante cinco (5) minutos.

Si no solicitaste este código puedes ignorar este correo.

Equipo CertiSENA ISO.
""",

            subtype=MessageType.plain
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)