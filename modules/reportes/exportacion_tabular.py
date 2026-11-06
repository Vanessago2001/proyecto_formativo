"""
Exportación de listados a Excel (.xlsx) y PDF, compartida por los módulos.

La usan el registro de certificados (CER-025), el listado oficial de empresas
certificadas (CER-026) y el historial de decisiones del Comité (COM-020). Antes
cada uno descargaba un .csv que Windows abre en el Bloc de notas; aquí se
arma, con las mismas filas, un libro de Excel con encabezados en español,
fechas legibles y columnas con ancho fijo, o un PDF horizontal con la
identidad institucional.

Quien llama decide los permisos y las filas; este módulo solo da formato.

Seguridad: en el .xlsx todas las celdas de texto se escriben como texto
(`data_type = "s"`), así que un valor como "=HYPERLINK(...)" escrito por un
usuario se muestra tal cual y nunca se evalúa como fórmula.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from typing import Any, Callable, Iterable
from xml.sax.saxutils import escape

from fastapi import HTTPException, Response, status

from core.datetime_utils import SYSTEM_TIMEZONE, system_now

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TIPO_PDF = "application/pdf"
FORMATOS = ("xlsx", "pdf")


@dataclass(frozen=True)
class Columna:
    """Una columna del listado: clave en la fila, título y ancho en Excel."""

    clave: str
    titulo: str
    ancho: float = 18
    transformar: Callable[[Any], Any] | None = None


# ---------------------------------------------------------------------------
# Valores legibles
# ---------------------------------------------------------------------------

def _a_hora_local(valor: datetime) -> datetime:
    if valor.tzinfo is not None:
        return valor.astimezone(SYSTEM_TIMEZONE).replace(tzinfo=None)
    return valor


def estado_legible(valor) -> str:
    """'PENDIENTE_FIRMA  ' -> 'Pendiente firma'; 'En revision' se conserva."""
    texto = " ".join(str(valor or "").replace("_", " ").split())
    if not texto:
        return ""
    return texto[0].upper() + texto[1:].lower() if texto.isupper() else texto


def texto_legible(valor) -> str:
    """El valor como lo leería una persona (para el PDF)."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, datetime):
        return _a_hora_local(valor).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = " ".join(str(valor).split()) if not isinstance(valor, str) else valor.strip()
    return "".join(c for c in texto if c in "\t\n" or ord(c) >= 32)


def _valor(fila: dict, columna: Columna):
    valor = fila.get(columna.clave)
    if columna.transformar is not None:
        valor = columna.transformar(valor)
    if isinstance(valor, str):
        valor = valor.strip()
    return valor


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def generar_xlsx(
    titulo: str,
    columnas: list[Columna],
    filas: Iterable[dict],
    *,
    subtitulo: str | None = None,
    hoja: str = "Datos",
) -> bytes:
    """Libro de una hoja: título, fecha de generación y la tabla con filtro."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    ws = libro.active
    ws.title = hoja[:31]

    ws.cell(row=1, column=1, value=titulo).font = Font(bold=True, size=14, color="256D00")
    linea = 2
    if subtitulo:
        ws.cell(row=linea, column=1, value=subtitulo).data_type = "s"
        linea += 1
    ws.cell(row=linea, column=1, value=f"Generado: {system_now():%d/%m/%Y %H:%M}").font = Font(
        italic=True, color="4B5563"
    )
    fila_encabezado = linea + 2

    relleno = PatternFill("solid", fgColor="39A900")
    for indice, columna in enumerate(columnas, start=1):
        celda = ws.cell(row=fila_encabezado, column=indice, value=columna.titulo)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        celda.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(indice)].width = columna.ancho

    numero = fila_encabezado
    for numero, fila in enumerate(filas, start=fila_encabezado + 1):
        for indice, columna in enumerate(columnas, start=1):
            valor = _valor(fila, columna)
            celda = ws.cell(row=numero, column=indice)
            celda.alignment = Alignment(vertical="top", wrap_text=True)
            if isinstance(valor, bool):
                celda.value = "Sí" if valor else "No"
            elif isinstance(valor, datetime):
                celda.value = _a_hora_local(valor)
                celda.number_format = "DD/MM/YYYY HH:MM"
            elif isinstance(valor, date):
                celda.value = valor
                celda.number_format = "DD/MM/YYYY"
            elif isinstance(valor, (int, float)):
                celda.value = valor
            elif valor is None:
                continue
            else:
                celda.value = texto_legible(valor)
            if isinstance(celda.value, str):
                # Nunca fórmula: un texto que empiece por "=" queda como texto.
                celda.data_type = "s"

    if numero == fila_encabezado:
        ws.cell(row=numero + 1, column=1, value="No hay información para mostrar.")
    else:
        ultima = get_column_letter(len(columnas))
        ws.auto_filter.ref = f"A{fila_encabezado}:{ultima}{numero}"
    ws.freeze_panes = ws.cell(row=fila_encabezado + 1, column=1)

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def generar_pdf_tabla(
    titulo: str,
    columnas: list[Columna],
    filas: Iterable[dict],
    *,
    subtitulo: str | None = None,
) -> bytes:
    """PDF horizontal con la franja institucional y la tabla paginada."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from core.pdf_institucional import GRIS_LINEA, GRIS_TEXTO, VERDE_OSCURO, VERDE_SENA, VERDE_SUAVE

    tamano = landscape(letter)
    margen = 12 * mm
    alto_franja = 18 * mm
    ancho_util = tamano[0] - 2 * margen

    estilo_titulo = ParagraphStyle("ExpTitulo", fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=VERDE_OSCURO)
    estilo_sub = ParagraphStyle("ExpSub", fontName="Helvetica", fontSize=9, leading=12, textColor=GRIS_TEXTO)
    estilo_enc = ParagraphStyle("ExpEnc", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=VERDE_OSCURO)
    estilo_val = ParagraphStyle("ExpVal", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#1F2937"))

    filas = list(filas)
    total_ancho = sum(c.ancho for c in columnas) or 1
    anchos = [ancho_util * c.ancho / total_ancho for c in columnas]
    datos = [[Paragraph(escape(c.titulo), estilo_enc) for c in columnas]]
    for fila in filas:
        datos.append([Paragraph(escape(texto_legible(_valor(fila, c))), estilo_val) for c in columnas])
    if not filas:
        datos.append([Paragraph("No hay información para mostrar.", estilo_val)] + [""] * (len(columnas) - 1))

    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    estilo_tabla = [
        ("BACKGROUND", (0, 0), (-1, 0), VERDE_SUAVE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRIS_LINEA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFDF9")]),
    ]
    if not filas:
        estilo_tabla.append(("SPAN", (0, 1), (-1, 1)))
    tabla.setStyle(TableStyle(estilo_tabla))

    generado = f"{system_now():%d/%m/%Y %H:%M}"
    historia = [Paragraph(escape(titulo), estilo_titulo)]
    if subtitulo:
        historia.append(Paragraph(escape(subtitulo), estilo_sub))
    historia.append(Paragraph(escape(f"Generado el {generado} · {len(filas)} registro(s)"), estilo_sub))
    historia.extend([Spacer(1, 4 * mm), tabla])

    def marco(canvas, documento):
        ancho, alto = tamano
        canvas.saveState()
        canvas.setFillColor(VERDE_SENA)
        canvas.rect(0, alto - alto_franja, ancho, alto_franja, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(margen, alto - 11 * mm, "CertiSENA")
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(margen + 32 * mm, alto - 11 * mm, "Servicio Nacional de Aprendizaje")
        canvas.setFillColor(GRIS_TEXTO)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(margen, 8 * mm, f"Documento generado por CertiSENA - SENA el {generado}.")
        canvas.drawRightString(ancho - margen, 8 * mm, f"Página {documento.page}")
        canvas.restoreState()

    salida = BytesIO()
    SimpleDocTemplate(
        salida,
        pagesize=tamano,
        leftMargin=margen,
        rightMargin=margen,
        topMargin=alto_franja + 6 * mm,
        bottomMargin=15 * mm,
        title=titulo,
        author="CertiSENA - SENA",
    ).build(historia, onFirstPage=marco, onLaterPages=marco)
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Respuesta HTTP
# ---------------------------------------------------------------------------

def normalizar_formato(formato: str | None) -> str:
    valor = str(formato or "xlsx").strip().lower()
    if valor in {"excel", "xls"}:
        valor = "xlsx"
    if valor not in FORMATOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Formato de exportación no admitido. Usa 'xlsx' o 'pdf'.",
        )
    return valor


def respuesta_exportacion(
    formato: str | None,
    *,
    titulo: str,
    columnas: list[Columna],
    filas: list[dict],
    nombre_base: str,
    subtitulo: str | None = None,
    hoja: str = "Datos",
) -> Response:
    """Genera el archivo pedido y lo devuelve como descarga."""
    formato = normalizar_formato(formato)
    if formato == "pdf":
        contenido = generar_pdf_tabla(titulo, columnas, filas, subtitulo=subtitulo)
        tipo = TIPO_PDF
    else:
        contenido = generar_xlsx(titulo, columnas, filas, subtitulo=subtitulo, hoja=hoja)
        tipo = TIPO_XLSX
    nombre = f"{nombre_base}.{formato}"
    return Response(
        content=contenido,
        media_type=tipo,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
