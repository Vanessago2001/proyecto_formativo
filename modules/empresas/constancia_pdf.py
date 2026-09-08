"""
Constancia pública de consulta de empresa por NIT.

Genera el PDF descargable desde el portal público `buscar_e.html`.
Solo incluye los datos que se ven en la tarjeta: empresa, NIT,
si está radicada, el número de radicado y si está verificada o en proceso.

La mecánica del formato PDF vive en `core/pdf.py` (sin dependencias nuevas).
"""

from datetime import date

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

    campos = [
        ("Empresa", nombre),
        ("NIT", nit),
        ("Radicada", "Si" if radicado else "No"),
        ("Radicado", radicado or "Sin radicar"),
        ("Estado", estado),
        ("Fecha de consulta", date.today()),
    ]

    return construir_pdf(
        titulo="CertiSENA - Constancia de consulta",
        subtitulo=f"{nombre} (NIT {nit})",
        campos=campos,
    )
