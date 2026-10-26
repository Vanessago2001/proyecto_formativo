"""
Documentos PDF con la identidad visual institucional de CertiSENA.

La cabecera reproduce la constancia pública de consulta: franja verde con el
isotipo del SENA en blanco, título en verde oscuro y pie de página con la fecha
de emisión. El módulo es deliberadamente genérico para que los comprobantes y
las exportaciones compartan la misma presentación sin duplicar estilos.

Los datos siempre llegan desde la consulta real de cada proceso; aquí solo se
organizan en secciones de etiqueta y valor.
"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
ANCHO_UTIL = 180 * mm

COLORES_ESTADO = {
    "aprobado": (VERDE_SUAVE, VERDE_OSCURO),
    "validado": (VERDE_SUAVE, VERDE_OSCURO),
    "activo": (VERDE_SUAVE, VERDE_OSCURO),
    "en revision": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "en revisión": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "pendiente": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "correcciones": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "en proceso": (colors.HexColor("#FFF8E1"), colors.HexColor("#8D6E00")),
    "rechazado": (colors.HexColor("#FDECEC"), colors.HexColor("#B42318")),
    "inactivo": (colors.HexColor("#FDECEC"), colors.HexColor("#B42318")),
    "cancelado": (colors.HexColor("#FDECEC"), colors.HexColor("#B42318")),
    "no radicada": (colors.HexColor("#EEF1F4"), GRIS_TEXTO),
}


def _estilos() -> dict[str, ParagraphStyle]:
    return {
        "titulo": ParagraphStyle(
            "TituloInstitucional",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=VERDE_OSCURO,
            spaceAfter=1 * mm,
        ),
        "subtitulo": ParagraphStyle(
            "SubtituloInstitucional",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=GRIS_TEXTO,
        ),
        "chip": ParagraphStyle(
            "ChipInstitucional",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
        ),
        "etiqueta": ParagraphStyle(
            "EtiquetaInstitucional",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=VERDE_OSCURO,
        ),
        "valor": ParagraphStyle(
            "ValorInstitucional",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#1F2937"),
        ),
        "seccion": ParagraphStyle(
            "SeccionInstitucional",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=VERDE_OSCURO,
            spaceBefore=1 * mm,
            spaceAfter=2 * mm,
        ),
        "nota": ParagraphStyle(
            "NotaInstitucional",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=GRIS_TEXTO,
        ),
    }


def _valor_seguro(valor) -> str:
    return escape(formatear_valor(valor))


def _tabla_campos(campos: list[tuple[str, object]], estilos: dict) -> Table:
    filas = [
        [
            Paragraph(escape(str(etiqueta)), estilos["etiqueta"]),
            Paragraph(_valor_seguro(valor), estilos["valor"]),
        ]
        for etiqueta, valor in campos
    ]

    tabla = Table(filas, colWidths=[52 * mm, 128 * mm])
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, GRIS_LINEA),
            ]
        )
    )
    return tabla


def texto_institucional(texto: str) -> Paragraph:
    """Párrafo de cuerpo, para avisos dentro de una sección."""
    return Paragraph(escape(str(texto)), _estilos()["valor"])


def tabla_institucional(
    encabezados: list[str],
    filas: list[list[object]],
    *,
    anchos: list[float] | None = None,
) -> Table:
    """Tabla limpia para listados, con el encabezado en verde institucional."""

    estilos = _estilos()
    datos = [
        [Paragraph(escape(str(encabezado)), estilos["etiqueta"]) for encabezado in encabezados]
    ]
    datos.extend(
        [
            [Paragraph(_valor_seguro(valor), estilos["valor"]) for valor in fila]
            for fila in filas
        ]
    )

    tabla = Table(
        datos,
        colWidths=anchos or [ANCHO_UTIL / len(encabezados)] * len(encabezados),
        repeatRows=1,
    )
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), VERDE_SUAVE),
                ("TEXTCOLOR", (0, 0), (-1, 0), VERDE_OSCURO),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRIS_LINEA),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFDF9")]),
            ]
        )
    )
    return tabla


def _chip(etiqueta: str, estado: str, estilos: dict) -> Table:
    fondo, color_texto = COLORES_ESTADO.get(
        str(estado or "").strip().lower(),
        (colors.HexColor("#EEF1F4"), GRIS_TEXTO),
    )
    estilo_chip = ParagraphStyle(
        "ChipInstitucionalEstado",
        parent=estilos["chip"],
        textColor=color_texto,
    )
    chip = Table(
        [
            [
                Paragraph(
                    f"{escape(etiqueta)}: <b>{escape(str(estado or 'Sin estado'))}</b>",
                    estilo_chip,
                )
            ]
        ],
        colWidths=[ANCHO_UTIL],
    )
    chip.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), fondo),
                ("TEXTCOLOR", (0, 0), (-1, -1), color_texto),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ]
        )
    )
    return chip


def construir_pdf_institucional(
    *,
    titulo: str,
    subtitulo: str,
    secciones: list[tuple[str, list[tuple[str, object]]]],
    chip: tuple[str, str] | None = None,  # (etiqueta, estado)

    elementos_extra: list[tuple[str, object]] | None = None,
    nota: str | None = None,
    nombre_archivo: str = "documento.pdf",
) -> bytes:
    """
    Construye un PDF de una o varias páginas con la cabecera institucional.

    `chip` recibe (texto, tono). `elementos_extra` recibe pares
    (título de sección, flowable) para listados como los documentos asociados.
    """

    estilos = _estilos()
    historia: list = [
        Spacer(1, 2 * mm),
        Paragraph(escape(titulo), estilos["titulo"]),
        Paragraph(escape(subtitulo), estilos["subtitulo"]),
    ]

    if chip:
        historia.extend([Spacer(1, 5 * mm), _chip(chip[0], chip[1], estilos)])

    for titulo_seccion, campos in secciones:
        historia.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(escape(titulo_seccion), estilos["seccion"]),
                _tabla_campos(campos, estilos),
            ]
        )

    for titulo_seccion, elemento in elementos_extra or []:
        historia.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(escape(titulo_seccion), estilos["seccion"]),
                elemento,
            ]
        )

    if nota:
        historia.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(escape(nota), estilos["nota"]),
            ]
        )

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=MARGEN_LATERAL,
        rightMargin=MARGEN_LATERAL,
        topMargin=ALTO_FRANJA + 8 * mm,
        bottomMargin=24 * mm,
        title=titulo,
        author="CertiSENA - SENA",
        subject=nombre_archivo,
    )
    documento.build(
        historia,
        onFirstPage=marco_institucional,
        onLaterPages=marco_institucional,
    )
    return buffer.getvalue()


def marco_institucional(canvas, documento):
    """Franja superior y pie de página, en todas las hojas."""

    ancho, alto = letter
    ruta_logo = Path(__file__).resolve().parents[1] / "static" / "sena_blanco.png"

    canvas.saveState()

    canvas.setFillColor(VERDE_SENA)
    canvas.rect(0, alto - ALTO_FRANJA, ancho, ALTO_FRANJA, stroke=0, fill=1)

    if ruta_logo.exists():
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
    canvas.drawString(
        MARGEN_LATERAL + 24 * mm,
        alto - 18.5 * mm,
        "Servicio Nacional de Aprendizaje",
    )
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
