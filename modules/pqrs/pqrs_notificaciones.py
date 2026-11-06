"""
Correos automáticos del módulo PQRS (PQR-002 y PQR-009).

Se envían al radicar (con el número de radicado), al solicitar información y
al registrar la respuesta. Un fallo del correo nunca deshace la operación: se
registra en el log y la función devuelve False.
"""

from __future__ import annotations

import asyncio
from html import escape

from core.config import settings
from core.logger import logger

TIEMPO_MAXIMO_ENVIO = 20  # segundos


def _plantilla(titulo: str, parrafos: list[str], radicado: str) -> str:
    cuerpo = "".join(
        f'<p style="margin:0 0 14px;line-height:1.6;color:#374151">{p}</p>' for p in parrafos
    )
    enlace = f"{settings.APP_BASE_URL.rstrip('/')}/pqrs#consultar"
    return f"""<!DOCTYPE html><html lang="es"><body style="margin:0;background:#f2f4f7;font-family:Arial,Helvetica,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:28px 0">
 <div style="background:#39A900;color:#fff;padding:18px 26px;border-radius:12px 12px 0 0">
  <strong style="font-size:20px">CertiSENA</strong><br><span style="font-size:13px">PQRS · Servicio Nacional de Aprendizaje</span>
 </div>
 <div style="background:#fff;padding:26px;border-radius:0 0 12px 12px">
  <h2 style="margin:0 0 16px;color:#256D00;font-size:20px">{escape(titulo)}</h2>
  <p style="margin:0 0 16px;font-size:15px">Radicado: <strong>{escape(radicado)}</strong></p>
  {cuerpo}
  <p style="margin:18px 0 0;font-size:13px;color:#6b7280">Consulta el estado en <a href="{escape(enlace)}">{escape(enlace)}</a>
  con tu número de radicado y el correo con el que radicaste.</p>
 </div>
 <p style="text-align:center;font-size:12px;color:#9ca3af">Mensaje automático de CertiSENA; no respondas a este correo.</p>
</div></body></html>"""


async def _enviar(destinatario: str, asunto: str, html: str) -> bool:
    if not destinatario:
        return False
    if not settings.MAIL_SERVER or not settings.MAIL_FROM:
        logger.warning("PQRS: correo no configurado; no se envió «%s».", asunto)
        return False
    try:
        from fastapi_mail import FastMail, MessageSchema, MessageType

        from core.mail import conf

        mensaje = MessageSchema(
            subject=asunto, recipients=[destinatario], body=html, subtype=MessageType.html
        )
        await asyncio.wait_for(FastMail(conf).send_message(mensaje), timeout=TIEMPO_MAXIMO_ENVIO)
        return True
    except Exception as error:  # el correo nunca rompe la operación
        logger.error("PQRS: no se pudo enviar el correo «%s»: %s", asunto, error)
        return False


async def notificar_radicacion(pqrs: dict) -> bool:
    return await _enviar(
        pqrs.get("correo"),
        f"PQRS radicada {pqrs['radicado']} - CertiSENA",
        _plantilla(
            "Recibimos tu PQRS",
            [
                f"Hola {escape(pqrs.get('nombre_peticionario') or '')}, tu {escape(str(pqrs.get('tipo', '')).lower())} "
                f"«{escape(pqrs.get('asunto') or '')}» quedó radicada.",
                f"La fecha límite de respuesta es el <strong>{escape(str(pqrs.get('fecha_limite')))}</strong>.",
            ],
            pqrs["radicado"],
        ),
    )


async def notificar_solicitud_informacion(pqrs: dict, solicitud: str) -> bool:
    return await _enviar(
        pqrs.get("correo"),
        f"Necesitamos información para tu PQRS {pqrs['radicado']}",
        _plantilla(
            "Información adicional requerida",
            [
                "Para continuar con el trámite necesitamos lo siguiente:",
                f"<em>{escape(solicitud)}</em>",
                "Puedes responder y adjuntar documentos desde la consulta de tu PQRS.",
            ],
            pqrs["radicado"],
        ),
    )


async def notificar_respuesta(pqrs: dict) -> bool:
    return await _enviar(
        pqrs.get("correo"),
        f"Respuesta a tu PQRS {pqrs['radicado']} - CertiSENA",
        _plantilla(
            "Tu PQRS fue respondida",
            [escape(pqrs.get("respuesta") or "").replace("\n", "<br>")],
            pqrs["radicado"],
        ),
    )
