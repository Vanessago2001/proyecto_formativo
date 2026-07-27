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

    @staticmethod
    async def enviar_enlace_reset(destinatario: str, enlace: str):

        mensaje = MessageSchema(

            subject="Restablecimiento de contraseña - CertiSENA ISO",

            recipients=[destinatario],

            body=f"""
Buen dia.

Se superó el número máximo de intentos de inicio de sesión.

Para poder volver a ingresar debe restablecer su contraseña.
Ingrese al siguiente enlace para crear una nueva contraseña:

{enlace}

Este enlace estará disponible durante treinta (30) minutos y solo puede usarse una vez.

Si no solicitó este cambio, ignore este correo y su contraseña seguirá siendo la misma.

Equipo CertiSENA ISO.
""",

            subtype=MessageType.plain
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)