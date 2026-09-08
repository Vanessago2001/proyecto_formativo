"""
Constancia pública de consulta de empresa por NIT.

Genera el PDF descargable desde el portal público `buscar_e.html`.
Solo incluye los datos que se ven en la tarjeta: empresa, NIT,
si está radicada, el número de radicado y si está verificada o en proceso.

La mecánica del formato PDF vive en `core/pdf.py` (sin dependencias nuevas).
"""

from datetime import datetime

from core.datetime_utils import SYSTEM_TIMEZONE
from core.pdf import construir_pdf


def generar_pdf_constancia(empresa: dict) -> bytes:
    """Devuelve la constancia de la empresa como bytes listos para descargar."""
    sol = empresa.get("ultima_solicitud") or {}
    radicado = sol.get("numero_radicado")
    certificada = bool(empresa.get("certificada"))

    if certificada:
        estado = "Verificada"
    elif radicado:
        estado = "En proceso"
    else:
        estado = "No radicada"

    nombre = empresa.get("nombre") or "No registrada"
    nit = empresa.get("nit") or "No registrado"

    fecha_solicitud = sol.get("fecha_radicacion") or sol.get("fecha")

    certs = empresa.get("certificados") or []
    fecha_certificado = certs[0].get("fecha_emision") if certs else None

    campos = [
        ("Empresa", nombre),
        ("NIT", nit),
        ("Radicada", "Si" if radicado else "No"),
        ("Radicado", radicado or "Sin radicar"),
        ("Fecha de solicitud del radicado", fecha_solicitud),
        ("Estado", estado),
        ("Fecha de emision del certificado", fecha_certificado),
        ("Fecha de descarga de la constancia", datetime.now(SYSTEM_TIMEZONE)),
    ]

    return construir_pdf(
        titulo="CertiSENA - Constancia de consulta",
        subtitulo=f"{nombre} (NIT {nit})",
        campos=campos,
    )
