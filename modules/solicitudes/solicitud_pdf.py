"""
M5 — GESTIÓN DE SOLICITUDES
Generación del PDF de la solicitud (SOL-007).

El documento sale de la aplicación y puede acabar en manos de terceros, así
que muestra nombres legibles (empresa con su NIT, norma con su código) y no
los identificadores internos de la base de datos.

La mecánica del formato PDF vive en `core/pdf.py`.
"""

from core.pdf import construir_pdf


def _empresa(solicitud: dict) -> str:
    """Nombre y NIT de la empresa titular, no su identificador interno."""
    nombre = solicitud.get("empresa_nombre")
    nit = solicitud.get("empresa_nit")

    if nombre and nit:
        return f"{nombre} (NIT {nit})"

    return nombre or "No registrada"


def _norma(solicitud: dict) -> str:
    """Código, nombre y versión de la norma solicitada."""
    partes = [
        solicitud.get("norma_codigo"),
        solicitud.get("norma_nombre"),
        solicitud.get("norma_version"),
    ]
    legible = " ".join(str(p) for p in partes if p)

    return legible or "No registrada"


def generar_pdf_solicitud(solicitud: dict) -> bytes:
    """Devuelve el PDF de la solicitud como bytes listos para descargar."""
    campos = [
        ("Radicado", solicitud.get("numero_radicado") or "Sin radicar (borrador)"),
        ("Estado", solicitud.get("estado")),
        ("Empresa titular", _empresa(solicitud)),
        ("Norma ISO solicitada", _norma(solicitud)),
        ("Alcance de certificacion", solicitud.get("alcance_certificacion")),
        ("Numero de empleados", solicitud.get("numero_empleados")),
        ("Numero de sedes", solicitud.get("numero_sedes")),
        ("Persona de contacto", solicitud.get("persona_contacto")),
        ("Observaciones", solicitud.get("observaciones")),
        ("Fecha de creacion", solicitud.get("fecha_creacion")),
        ("Fecha de radicacion", solicitud.get("fecha_radicacion")),
        ("Fecha de cancelacion", solicitud.get("fecha_cancelacion")),
        ("Motivo de cancelacion", solicitud.get("motivo_cancelacion")),
    ]

    return construir_pdf(
        titulo="CertiSENA - Solicitud de certificacion",
        subtitulo=_empresa(solicitud),
        campos=campos,
    )
