"""
Constancia pública de consulta de empresa por NIT (M11).

Genera el PDF descargable desde el portal público con la identidad visual del
SENA: franja superior verde con el isotipo en blanco, textos y recuadros en los
verdes institucionales y un bloque destacado con la norma bajo la cual se
evaluó el trámite.

Solo incluye los datos que se ven en la tarjeta pública: empresa, NIT, ciudad,
radicado, estado, certificado y norma. No lleva `correo` ni `direccion`,
coherente con lo que publica este módulo.

El PDF genérico de la solicitud (SOL-007) sigue viviendo en `core/pdf.py`; este
usa reportlab, que ya es dependencia del proyecto, porque necesita incrustar el
logo y manejar colores.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.datetime_utils import SYSTEM_TIMEZONE
from core.pdf import formatear_valor

# Identidad visual del SENA, la misma que usa la cabecera del sitio.
VERDE_SENA = colors.HexColor("#39A900")
VERDE_OSCURO = colors.HexColor("#256D00")
VERDE_SUAVE = colors.HexColor("#F1F9EE")
GRIS_TEXTO = colors.HexColor("#4B5563")
GRIS_LINEA = colors.HexColor("#DCE3D9")

ALTO_FRANJA = 30 * mm
MARGEN_LATERAL = 16 * mm

# Fondo y texto del recuadro de estado, según el resultado de la consulta.
COLORES_ESTADO = {
    "Verificada": (VERDE_SUAVE, VERDE_OSCURO),
    "En proceso": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "No radicada": (colors.HexColor("#EEF1F4"), GRIS_TEXTO),
}


def _estilos() -> dict[str, ParagraphStyle]:
    return {
        "titulo": ParagraphStyle(
            "TituloConstancia",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=VERDE_OSCURO,
            spaceAfter=1 * mm,
        ),
        "subtitulo": ParagraphStyle(
            "SubtituloConstancia",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=GRIS_TEXTO,
        ),
        "chip": ParagraphStyle(
            "ChipConstancia",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
        ),
        "etiqueta": ParagraphStyle(
            "EtiquetaConstancia",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=VERDE_OSCURO,
        ),
        "valor": ParagraphStyle(
            "ValorConstancia",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#1F2937"),
        ),
        "kicker": ParagraphStyle(
            "KickerConstancia",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=VERDE_OSCURO,
        ),
        "norma": ParagraphStyle(
            "NormaConstancia",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1F2937"),
            spaceBefore=1 * mm,
        ),
        "nota": ParagraphStyle(
            "NotaConstancia",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=GRIS_TEXTO,
        ),
    }


def _norma_evaluada(empresa: dict) -> str:
    """
    La norma bajo la cual se evaluó el trámite.

    Se prefiere la del certificado vigente (es la que ampara la certificación)
    y, si no hay certificado, la de la última solicitud radicada.
    """
    certificados = empresa.get("certificados") or []
    fuentes = ([certificados[0]] if certificados else []) + [empresa.get("ultima_solicitud") or {}]

    for fuente in fuentes:
        partes = [
            fuente.get("norma_codigo"),
            fuente.get("norma_nombre") or fuente.get("norma"),
            fuente.get("norma_version"),
        ]
        texto = " ".join(str(parte).strip() for parte in partes if parte).strip()
        if texto:
            return texto

    return "Sin norma registrada"


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
    certificado = certs[0] if certs else {}

    estilos = _estilos()
    ahora = datetime.now(SYSTEM_TIMEZONE)

    campos = [
        ("Empresa", nombre),
        ("NIT", nit),
        ("Ciudad", empresa.get("ciudad")),
        ("Radicada", "Sí" if radicado else "No"),
        ("Número de radicado", radicado or "Sin radicar"),
        ("Fecha de radicación", fecha_solicitud),
        ("Código de verificación", certificado.get("codigo_verificacion") or "Sin certificado emitido"),
        ("Fecha de emisión del certificado", certificado.get("fecha_emision")),
        ("Vigente hasta", certificado.get("fecha_vencimiento")),
        ("Fecha de descarga de la constancia", ahora),
    ]

    filas_datos = [
        [
            Paragraph(escape(str(etiqueta)), estilos["etiqueta"]),
            Paragraph(escape(formatear_valor(valor)), estilos["valor"]),
        ]
        for etiqueta, valor in campos
    ]

    fondo_estado, texto_estado = COLORES_ESTADO[estado]
    chip = Table(
        [[Paragraph(f"Estado de la certificación: <b>{escape(estado)}</b>", estilos["chip"])]],
        colWidths=[180 * mm],
    )
    chip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fondo_estado),
        ("TEXTCOLOR", (0, 0), (-1, -1), texto_estado),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))

    tabla_datos = Table(filas_datos, colWidths=[52 * mm, 128 * mm])
    tabla_datos.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, GRIS_LINEA),
    ]))

    norma = _norma_evaluada(empresa)
    bloque_norma = Table(
        [
            [Paragraph("NORMA BAJO LA CUAL SE EVALUÓ EL TRÁMITE", estilos["kicker"])],
            [Paragraph(escape(norma), estilos["norma"])],
        ],
        colWidths=[180 * mm],
    )
    bloque_norma.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), VERDE_SUAVE),
        ("LINEBEFORE", (0, 0), (-1, -1), 3, VERDE_SENA),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (0, 0), 3 * mm),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 3 * mm),
    ]))

    historia = [
        Spacer(1, 2 * mm),
        Paragraph("Constancia de consulta pública", estilos["titulo"]),
        Paragraph(f"{escape(nombre)} &middot; NIT {escape(nit)}", estilos["subtitulo"]),
        Spacer(1, 5 * mm),
        chip,
        Spacer(1, 5 * mm),
        tabla_datos,
        Spacer(1, 5 * mm),
        bloque_norma,
        Spacer(1, 4 * mm),
        Paragraph(
            "Esta constancia refleja el estado del trámite en la fecha de descarga. "
            "Verifique la autenticidad de un certificado con su código de verificación "
            "en el portal público de CertiSENA.",
            estilos["nota"],
        ),
    ]

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=MARGEN_LATERAL,
        rightMargin=MARGEN_LATERAL,
        topMargin=ALTO_FRANJA + 8 * mm,
        bottomMargin=24 * mm,
        title=f"Constancia de consulta - {nombre}",
        author="CertiSENA - SENA",
    )
    documento.build(historia, onFirstPage=_marco, onLaterPages=_marco)
    return buffer.getvalue()


def _marco(canvas, documento):
    """Franja institucional superior y pie de página, en todas las hojas."""
    ancho, alto = letter
    ruta_logo = Path(__file__).resolve().parents[2] / "static" / "sena_blanco.png"

    canvas.saveState()

    canvas.setFillColor(VERDE_SENA)
    canvas.rect(0, alto - ALTO_FRANJA, ancho, ALTO_FRANJA, stroke=0, fill=1)

    canvas.drawImage(
        str(ruta_logo),
        MARGEN_LATERAL,
        alto - ALTO_FRANJA + 5 * mm,
        width=20 * mm,
        height=20 * mm,
        mask="auto",
        preserveAspectRatio=True,
        anchor="sw",
    )

    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 19)
    canvas.drawString(MARGEN_LATERAL + 24 * mm, alto - 13 * mm, "CertiSENA")
    canvas.setFont("Helvetica", 9.5)
    canvas.drawString(MARGEN_LATERAL + 24 * mm, alto - 18.5 * mm, "Servicio Nacional de Aprendizaje")
    canvas.drawString(
        MARGEN_LATERAL + 24 * mm,
        alto - 23.5 * mm,
        "Plataforma de gestión y consulta de certificados",
    )

    canvas.setStrokeColor(VERDE_SENA)
    canvas.setLineWidth(1.2)
    canvas.line(MARGEN_LATERAL, 17 * mm, ancho - MARGEN_LATERAL, 17 * mm)
    canvas.setFillColor(GRIS_TEXTO)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(
        MARGEN_LATERAL,
        12.5 * mm,
        "Documento generado automáticamente por CertiSENA - SENA. "
        f"Emitido el {datetime.now(SYSTEM_TIMEZONE):%d/%m/%Y %H:%M}.",
    )

    canvas.restoreState()
