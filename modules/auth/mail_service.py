from pathlib import Path

from fastapi_mail import FastMail
from fastapi_mail import MessageSchema
from fastapi_mail import MessageType

from core.mail import conf


class MailService:

    # la ruta del logo del SENA para adjuntarlo en los correos
    LOGO_PATH = (
        Path(__file__).resolve().parents[2]
        / "static"
        / "sena_blanco.png"
    )


    # ============================================================
    # PLANTILLA GENERAL DE CORREOS
    # ============================================================

    @staticmethod
    def _crear_html(
        titulo: str,
        mensaje: str,
        codigo: str | None = None,
    ):

        codigo_html = ""

        if codigo:
            codigo_html = f"""
            <div style="
                margin: 25px 0;
                padding: 20px;
                background-color: #f4f6f8;
                border-radius: 10px;
                text-align: center;
            ">
                <p style="
                    margin: 0 0 10px 0;
                    font-size: 14px;
                    color: #555555;
                ">
                    Tu código de verificación es:
                </p>

                <div style="
                    font-size: 32px;
                    font-weight: bold;
                    letter-spacing: 8px;
                    color: #111111;
                ">
                    {codigo}
                </div>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html lang="es">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{titulo}</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f2f4f7;
            font-family: Arial, Helvetica, sans-serif;
        ">

            <div style="
                width: 100%;
                padding: 35px 0;
            ">

                <div style="
                    max-width: 600px;
                    margin: 0 auto;
                    background-color: #ffffff;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 3px 12px rgba(0,0,0,0.08);
                ">

                    <!-- ENCABEZADO -->

                    <div style="
                        padding: 25px;
                        text-align: center;
                        background-color: #ffffff;
                        border-bottom: 1px solid #eeeeee;
                    ">

                         <img
                                src="cid:sena_logo"
                                alt="SENA"
                                style="
                                    width: 85px;
                                    max-width: 100%;
                                    height: auto;
                                "
                            >

                        <h1 style="
                            margin: 18px 0 0 0;
                            font-size: 24px;
                            color: #333333;
                        ">
                            CertiSENA ISO
                        </h1>

                    </div>


                    <!-- CONTENIDO -->

                    <div style="
                        padding: 35px;
                        color: #333333;
                    ">

                        <h2 style="
                            margin-top: 0;
                            font-size: 22px;
                            color: #222222;
                        ">
                            {titulo}
                        </h2>

                        <div style="
                            font-size: 15px;
                            line-height: 1.7;
                            color: #555555;
                        ">
                            {mensaje}
                        </div>

                        {codigo_html}

                    </div>


                    <!-- PIE -->

                    <div style="
                        padding: 20px;
                        text-align: center;
                        background-color: #f7f7f7;
                        border-top: 1px solid #eeeeee;
                    ">

                        <p style="
                            margin: 0;
                            font-size: 13px;
                            color: #777777;
                        ">
                            Este mensaje fue enviado automáticamente por CertiSENA ISO.
                        </p>

                        <p style="
                            margin: 8px 0 0 0;
                            font-size: 12px;
                            color: #999999;
                        ">
                            Si no realizaste esta solicitud, puedes ignorar este correo.
                        </p>

                    </div>

                </div>

            </div>

        </body>
        </html>
        """

        
    # ============================================================
    # ACTIVAR MFA
    # ============================================================

    @staticmethod
    async def enviar_codigo_activar_mfa(
        destinatario: str,
        codigo: str,
    ):

        html = f"""
        <!DOCTYPE html>
        <html lang="es">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Activación de autenticación en dos pasos</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
        ">

            <div style="
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            ">

                <!-- ENCABEZADO -->
                <div style="
                    background-color: #198754;
                    padding: 25px;
                    text-align: center;
                ">

                    <img
                        src="cid:sena_logo"
                        alt="SENA"
                        style="
                            width: 85px;
                            max-width: 100%;
                            height: auto;
                        "
                    >

                    <h1 style="
                        color: #ffffff;
                        margin: 15px 0 0 0;
                        font-size: 24px;
                    ">
                        CertiSENA ISO
                    </h1>

                </div>

                <!-- CONTENIDO -->
                <div style="padding: 35px;">

                    <h2 style="
                        color: #333333;
                        margin-top: 0;
                    ">
                        Activación de autenticación en dos pasos
                    </h2>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Buen día.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Has solicitado activar la autenticación en dos pasos
                        para tu cuenta de <strong>CertiSENA ISO</strong>.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Utiliza el siguiente código para confirmar
                        la activación:
                    </p>

                    <!-- CÓDIGO -->
                    <div style="
                        margin: 30px 0;
                        padding: 20px;
                        background-color: #f4f6f8;
                        border-radius: 10px;
                        text-align: center;
                    ">

                        <p style="
                            margin: 0 0 10px 0;
                            color: #777777;
                            font-size: 14px;
                        ">
                            Código de verificación
                        </p>

                        <div style="
                            font-size: 32px;
                            font-weight: bold;
                            letter-spacing: 8px;
                            color: #198754;
                        ">
                            {codigo}
                        </div>

                    </div>

                    <p style="
                        color: #777777;
                        font-size: 14px;
                        line-height: 1.6;
                    ">
                        Este código estará disponible durante
                        <strong>10 minutos</strong>.
                    </p>

                    <hr style="
                        border: none;
                        border-top: 1px solid #eeeeee;
                        margin: 25px 0;
                    ">

                    <p style="
                        color: #777777;
                        font-size: 13px;
                        line-height: 1.6;
                    ">
                        Si no solicitaste activar la autenticación en dos pasos,
                        puedes ignorar este correo.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 14px;
                        margin-top: 30px;
                    ">
                        Atentamente,<br>
                        <strong>Equipo CertiSENA ISO</strong>
                    </p>

                </div>

                <!-- PIE -->
                <div style="
                    background-color: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                ">

                    <p style="
                        margin: 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        Este es un mensaje automático.
                        Por favor, no respondas a este correo.
                    </p>

                    <p style="
                        margin: 8px 0 0 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        CertiSENA ISO
                    </p>

                </div>

            </div>

        </body>
        </html>
        """

        mensaje = MessageSchema(
            subject="Activación de autenticación en dos pasos - CertiSENA ISO",
            recipients=[destinatario],
            body=html,
            subtype=MessageType.html,
            attachments=[
                {
                    "file": str(MailService.LOGO_PATH),
                    "headers": {
                        "Content-ID": "<sena_logo>",
                        "Content-Disposition": 'inline; filename="sena_blanco.png"',
                    },
                    "mime_type": "image",
                    "mime_subtype": "png",
                }
            ],
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)


    # ============================================================
    # LOGIN MFA
    # ============================================================

    @staticmethod
    async def enviar_codigo_login_mfa(
        destinatario: str,
        codigo: str,
    ):

        html = f"""
        <!DOCTYPE html>
        <html lang="es">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Código para iniciar sesión</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
        ">

            <div style="
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            ">

                <!-- ENCABEZADO -->
                <div style="
                    background-color: #198754;
                    padding: 25px;
                    text-align: center;
                ">

                    <img
                        src="cid:sena_logo"
                        alt="SENA"
                        style="
                            width: 85px;
                            max-width: 100%;
                            height: auto;
                        "
                    >

                    <h1 style="
                        color: #ffffff;
                        margin: 15px 0 0 0;
                        font-size: 24px;
                    ">
                        CertiSENA ISO
                    </h1>

                </div>

                <!-- CONTENIDO -->
                <div style="padding: 35px;">

                    <h2 style="
                        color: #333333;
                        margin-top: 0;
                    ">
                        Código para iniciar sesión
                    </h2>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Buen día.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Se ha solicitado iniciar sesión en tu cuenta de
                        <strong>CertiSENA ISO</strong>.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Para continuar con el inicio de sesión,
                        introduce el siguiente código de verificación:
                    </p>

                    <!-- CÓDIGO -->
                    <div style="
                        margin: 30px 0;
                        padding: 20px;
                        background-color: #f4f6f8;
                        border-radius: 10px;
                        text-align: center;
                    ">

                        <p style="
                            margin: 0 0 10px 0;
                            color: #777777;
                            font-size: 14px;
                        ">
                            Código de verificación
                        </p>

                        <div style="
                            font-size: 32px;
                            font-weight: bold;
                            letter-spacing: 8px;
                            color: #198754;
                        ">
                            {codigo}
                        </div>

                    </div>

                    <p style="
                        color: #777777;
                        font-size: 14px;
                        line-height: 1.6;
                    ">
                        Este código estará disponible durante
                        <strong>5 minutos</strong>.
                    </p>

                    <hr style="
                        border: none;
                        border-top: 1px solid #eeeeee;
                        margin: 25px 0;
                    ">

                    <p style="
                        color: #777777;
                        font-size: 13px;
                        line-height: 1.6;
                    ">
                        Si no intentaste iniciar sesión en CertiSENA ISO,
                        puedes ignorar este correo.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 14px;
                        margin-top: 30px;
                    ">
                        Atentamente,<br>
                        <strong>Equipo CertiSENA ISO</strong>
                    </p>

                </div>

                <!-- PIE -->
                <div style="
                    background-color: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                ">

                    <p style="
                        margin: 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        Este es un mensaje automático.
                        Por favor, no respondas a este correo.
                    </p>

                    <p style="
                        margin: 8px 0 0 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        CertiSENA ISO
                    </p>

                </div>

            </div>

        </body>
        </html>
        """

        mensaje = MessageSchema(
            subject="Código para iniciar sesión - CertiSENA ISO",
            recipients=[destinatario],
            body=html,
            subtype=MessageType.html,
            attachments=[
                {
                    "file": str(MailService.LOGO_PATH),
                    "headers": {
                        "Content-ID": "<sena_logo>",
                        "Content-Disposition": 'inline; filename="sena_blanco.png"',
                    },
                    "mime_type": "image",
                    "mime_subtype": "png",
                }
            ],
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)


    # ============================================================
    # DESACTIVAR MFA
    # ============================================================

    @staticmethod
    async def enviar_codigo_desactivar_mfa(
        destinatario: str,
        codigo: str,
    ):

        html = f"""
        <!DOCTYPE html>
        <html lang="es">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Desactivación de autenticación en dos pasos</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
        ">

            <div style="
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            ">

                <!-- ENCABEZADO -->
                <div style="
                    background-color: #198754;
                    padding: 25px;
                    text-align: center;
                ">

                    <img
                        src="cid:sena_logo"
                        alt="SENA"
                        style="
                            width: 85px;
                            max-width: 100%;
                            height: auto;
                        "
                    >

                    <h1 style="
                        color: #ffffff;
                        margin: 15px 0 0 0;
                        font-size: 24px;
                    ">
                        CertiSENA ISO
                    </h1>

                </div>

                <!-- CONTENIDO -->
                <div style="padding: 35px;">

                    <h2 style="
                        color: #333333;
                        margin-top: 0;
                    ">
                        Desactivación de autenticación en dos pasos
                    </h2>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Buen día.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Se ha solicitado desactivar la autenticación
                        en dos pasos de tu cuenta de
                        <strong>CertiSENA ISO</strong>.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Utiliza el siguiente código para confirmar
                        la desactivación:
                    </p>

                    <!-- CÓDIGO -->
                    <div style="
                        margin: 30px 0;
                        padding: 20px;
                        background-color: #f4f6f8;
                        border-radius: 10px;
                        text-align: center;
                    ">

                        <p style="
                            margin: 0 0 10px 0;
                            color: #777777;
                            font-size: 14px;
                        ">
                            Código de verificación
                        </p>

                        <div style="
                            font-size: 32px;
                            font-weight: bold;
                            letter-spacing: 8px;
                            color: #198754;
                        ">
                            {codigo}
                        </div>

                    </div>

                    <p style="
                        color: #777777;
                        font-size: 14px;
                        line-height: 1.6;
                    ">
                        Este código estará disponible durante
                        <strong>10 minutos</strong>.
                    </p>

                    <hr style="
                        border: none;
                        border-top: 1px solid #eeeeee;
                        margin: 25px 0;
                    ">

                    <p style="
                        color: #777777;
                        font-size: 13px;
                        line-height: 1.6;
                    ">
                        Si no solicitaste desactivar la autenticación
                        en dos pasos, puedes ignorar este correo.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 14px;
                        margin-top: 30px;
                    ">
                        Atentamente,<br>
                        <strong>Equipo CertiSENA ISO</strong>
                    </p>

                </div>

                <!-- PIE -->
                <div style="
                    background-color: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                ">

                    <p style="
                        margin: 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        Este es un mensaje automático.
                        Por favor, no respondas a este correo.
                    </p>

                    <p style="
                        margin: 8px 0 0 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        CertiSENA ISO
                    </p>

                </div>

            </div>

        </body>
        </html>
        """

        mensaje = MessageSchema(
            subject="Desactivación de autenticación en dos pasos - CertiSENA ISO",
            recipients=[destinatario],
            body=html,
            subtype=MessageType.html,
            attachments=[
                {
                    "file": str(MailService.LOGO_PATH),
                    "headers": {
                        "Content-ID": "<sena_logo>",
                        "Content-Disposition": 'inline; filename="sena_blanco.png"',
                    },
                    "mime_type": "image",
                    "mime_subtype": "png",
                }
            ],
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)

    # ============================================================
    # RESTABLECER CONTRASEÑA
    # ============================================================
    
    @staticmethod
    async def enviar_enlace_reset(destinatario: str, enlace: str):

        html = f"""
        <!DOCTYPE html>
        <html lang="es">

        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Recuperación de contraseña</title>
        </head>

        <body style="
            margin: 0;
            padding: 0;
            background-color: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
        ">

            <div style="
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            ">

                <!-- ENCABEZADO -->
                <div style="
                    background-color: #198754;
                    padding: 25px;
                    text-align: center;
                ">

                    <img
                        src="cid:sena_logo"
                        alt="SENA"
                        style="
                            width: 85px;
                            max-width: 100%;
                            height: auto;
                        "
                    >

                    <h1 style="
                        color: #ffffff;
                        margin: 15px 0 0 0;
                        font-size: 24px;
                    ">
                        CertiSENA ISO
                    </h1>

                </div>

                <!-- CONTENIDO -->
                <div style="padding: 35px;">

                    <h2 style="
                        color: #333333;
                        margin-top: 0;
                    ">
                        Recuperación de contraseña
                    </h2>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Buen día.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Hemos recibido una solicitud para restablecer
                        la contraseña de tu cuenta en
                        <strong>CertiSENA ISO</strong>.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 16px;
                        line-height: 1.6;
                    ">
                        Para crear una nueva contraseña, haz clic en
                        el siguiente botón:
                    </p>

                    <!-- BOTÓN -->
                    <div style="
                        text-align: center;
                        margin: 30px 0;
                    ">

                        <a
                            href="{enlace}"
                            style="
                                display: inline-block;
                                background-color: #198754;
                                color: #ffffff;
                                text-decoration: none;
                                padding: 14px 30px;
                                border-radius: 8px;
                                font-size: 16px;
                                font-weight: bold;
                            "
                        >
                            Restablecer contraseña
                        </a>

                    </div>

                    <p style="
                        color: #777777;
                        font-size: 14px;
                        line-height: 1.6;
                    ">
                        Este enlace estará disponible durante
                        <strong>30 minutos</strong> y solo podrá
                        utilizarse una vez.
                    </p>

                    <hr style="
                        border: none;
                        border-top: 1px solid #eeeeee;
                        margin: 25px 0;
                    ">

                    <p style="
                        color: #777777;
                        font-size: 13px;
                        line-height: 1.6;
                    ">
                        Si no solicitaste restablecer tu contraseña,
                        puedes ignorar este correo. Tu contraseña
                        actual permanecerá sin cambios.
                    </p>

                    <p style="
                        color: #555555;
                        font-size: 14px;
                        margin-top: 30px;
                    ">
                        Atentamente,<br>
                        <strong>Equipo CertiSENA ISO</strong>
                    </p>

                </div>

                <!-- PIE -->
                <div style="
                    background-color: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                ">

                    <p style="
                        margin: 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        Este es un mensaje automático.
                        Por favor, no respondas a este correo.
                    </p>

                    <p style="
                        margin: 8px 0 0 0;
                        color: #888888;
                        font-size: 12px;
                    ">
                        CertiSENA ISO
                    </p>

                </div>

            </div>

        </body>
        </html>
        """

        mensaje = MessageSchema(
            subject="Recuperación de contraseña - CertiSENA ISO",
            recipients=[destinatario],
            body=html,
            subtype=MessageType.html,
            attachments=[
                {
                    "file": str(MailService.LOGO_PATH),
                    "headers": {
                        "Content-ID": "<sena_logo>",
                        "Content-Disposition": 'inline; filename="sena_blanco.png"',
                    },
                    "mime_type": "image",
                    "mime_subtype": "png",
                }
            ],
        )

        fm = FastMail(conf)

        await fm.send_message(mensaje)

