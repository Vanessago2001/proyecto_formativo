"""
Generador de PDF mínimo, construido con la librería estándar.

Se escribe el archivo a mano para no añadir una dependencia al proyecto.
Produce un PDF 1.4 de una página con las fuentes Helvetica y Helvetica-Bold,
que son fuentes base del formato y no hay que incrustar.

Lo usan el PDF de la solicitud (SOL-007) y la constancia pública (PUB-009).
"""

from datetime import date, datetime

# Medidas de la página Carta en puntos PostScript (1 pt = 1/72").
ANCHO_PAGINA = 612
ALTO_PAGINA = 792

MARGEN_IZQUIERDO = 56
MARGEN_SUPERIOR = 56

INTERLINEADO = 16
ANCHO_MAXIMO_LINEA = 88  # caracteres por línea antes de partir el texto

# Puntuación tipográfica frecuente que Latin-1 no cubre. Sin esto, un guion
# largo copiado desde Word acabaría impreso como "?".
EQUIVALENCIAS = {
    "—": "-",   # raya
    "–": "-",   # semiraya
    "‐": "-",
    "‑": "-",
    "‘": "'",   # comillas simples tipográficas
    "’": "'",
    "“": '"',   # comillas dobles tipográficas
    "”": '"',
    "…": "...",
    " ": " ",   # espacio duro
    "•": "-",   # viñeta
    "€": "EUR",
}


def escapar(texto: str) -> str:
    """Escapa los caracteres reservados de una cadena literal PDF."""
    return texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def a_latin1(texto: str) -> str:
    """
    Las fuentes base del PDF usan WinAnsi (Latin-1).

    Las tildes y la eñe sí están cubiertas. Lo que queda fuera se traduce a
    su equivalente ASCII, y solo en último caso se reemplaza, para que el
    archivo nunca quede corrupto.
    """
    for original, sustituto in EQUIVALENCIAS.items():
        texto = texto.replace(original, sustituto)

    return texto.encode("latin-1", errors="replace").decode("latin-1")


def partir(texto: str, ancho: int = ANCHO_MAXIMO_LINEA) -> list[str]:
    """Parte un texto largo en varias líneas sin cortar palabras."""
    palabras = texto.split()
    if not palabras:
        return [""]

    lineas: list[str] = []
    actual = palabras[0]

    for palabra in palabras[1:]:
        if len(actual) + 1 + len(palabra) <= ancho:
            actual = f"{actual} {palabra}"
        else:
            lineas.append(actual)
            actual = palabra

    lineas.append(actual)
    return lineas


def formatear_valor(valor) -> str:
    """Vuelve legible cualquier valor que se quiera imprimir."""
    if valor is None or valor == "":
        return "No registrado"
    if isinstance(valor, bool):
        return "Si" if valor else "No"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _contenido(
    titulo: str,
    subtitulo: str,
    campos: list[tuple[str, object]],
    pie: str,
) -> str:
    """Arma el flujo de operadores de texto de la página."""
    partes: list[str] = [
        "BT",
        f"1 0 0 1 {MARGEN_IZQUIERDO} {ALTO_PAGINA - MARGEN_SUPERIOR} Tm",
        f"{INTERLINEADO} TL",
        "/F2 16 Tf",
        f"({escapar(a_latin1(titulo))}) Tj",
        "T*",
        "/F1 9 Tf",
        f"({escapar(a_latin1(subtitulo))}) Tj",
        "T*",
        "T*",
    ]

    for etiqueta, valor in campos:
        partes.append("/F2 10 Tf")
        partes.append(f"({escapar(a_latin1(str(etiqueta) + ':'))}) Tj")
        partes.append("T*")
        partes.append("/F1 10 Tf")

        for linea in partir(formatear_valor(valor)):
            partes.append(f"({escapar(a_latin1(linea))}) Tj")
            partes.append("T*")

        partes.append("T*")

    partes.append("/F1 8 Tf")
    for linea in partir(pie, 110):
        partes.append(f"({escapar(a_latin1(linea))}) Tj")
        partes.append("T*")
    partes.append("ET")

    return "\n".join(partes)


def construir_pdf(
    titulo: str,
    subtitulo: str,
    campos: list[tuple[str, object]],
    pie: str = "Documento generado automaticamente por el sistema CertiSENA.",
) -> bytes:
    """
    Devuelve un PDF de una página como bytes listos para descargar.

    Se ensambla objeto por objeto y se calculan los desplazamientos reales
    para la tabla xref, que es lo que exige el formato.
    """
    contenido = _contenido(titulo, subtitulo, campos, pie).encode("latin-1")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R "
            b"/MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> "
            b"/Contents 4 0 R >>" % (ANCHO_PAGINA, ALTO_PAGINA)
        ),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(contenido), contenido),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]

    salida = bytearray(b"%PDF-1.4\n")
    desplazamientos: list[int] = []

    for numero, cuerpo in enumerate(objetos, start=1):
        desplazamientos.append(len(salida))
        salida += b"%d 0 obj\n" % numero + cuerpo + b"\nendobj\n"

    inicio_xref = len(salida)
    total = len(objetos) + 1

    salida += b"xref\n0 %d\n" % total
    salida += b"0000000000 65535 f \n"
    for desplazamiento in desplazamientos:
        salida += b"%010d 00000 n \n" % desplazamiento

    salida += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % total
    salida += b"startxref\n%d\n%%%%EOF\n" % inicio_xref

    return bytes(salida)
