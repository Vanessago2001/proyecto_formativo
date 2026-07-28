from fastapi_mail import FastMail
from fastapi_mail import MessageSchema
from fastapi_mail import MessageType

from core.mail import conf


class MailService:

    # ==========================================
    # FUNCIÓN DE TU COMPAÑERO
    # NO LA MODIFICAMOS
    # ==========================================

    @staticmethod
    async def enviar_codigo(destinatario: str, codigo: str):

        mensaje = MessageSchema(

            subject="Código de verificación - CertiSENA ISO",

            recipients=[destinatario],

            body=f"""
            Hola.

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


            # ==========================================
            # RECUPERACIÓN DE CONTRASEÑA
            # NUEVA FUNCIÓN
            # ==========================================

    @staticmethod
    async def enviar_codigo_recuperacion(
        destinatario: str,
        codigo: str
    ):

        mensaje = MessageSchema(

            subject="Recuperación de contraseña - CertiSENA ISO",

            recipients=[destinatario],

            body=f"""
            Hola.

            Recibimos una solicitud para recuperar tu contraseña.

            Tu código de verificación es:

                {codigo}

                Este código estará disponible durante diez (10) minutos.

                Si no solicitaste recuperar tu contraseña,
                puedes ignorar este correo.

                Equipo CertiSENA ISO.
                """,

                subtype=MessageType.plain
            )

        fm = FastMail(conf)

        await fm.send_message(mensaje)


            # ==========================================
            # ENLACE PARA CAMBIAR CONTRASEÑA
            # NUEVA FUNCIÓN
            # ==========================================

    @staticmethod
    async def enviar_link_recuperacion(
        destinatario: str,
        link: str
    ):

        mensaje = MessageSchema(

            subject="Restablecer contraseña - CertiSENA ISO",

            recipients=[destinatario],

            body=f"""
            Hola.

            Tu código de recuperación fue verificado correctamente.

            Para establecer una nueva contraseña,
            haz clic en el siguiente enlace:

                {link}

                Este enlace estará disponible durante diez (10) minutos.

                Si no solicitaste recuperar tu contraseña,
                puedes ignorar este correo.

                Equipo CertiSENA ISO.
                """,

                subtype=MessageType.plain
            )

        fm = FastMail(conf)

        await fm.send_message(mensaje)