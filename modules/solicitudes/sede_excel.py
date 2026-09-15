"""
M5 — GESTIÓN DE SOLICITUDES
Exportación de las sedes de una solicitud a Excel (SOL-030).

Se genera con la librería estándar, igual que el PDF de SOL-007: no se añade
ninguna dependencia al proyecto.

Un .xlsx es un ZIP con unos pocos archivos XML. Aquí se escribe el mínimo que
abren Excel, LibreOffice y Google Sheets: una hoja, un estilo en negrita para
los títulos y todas las celdas como texto (`inlineStr`). Al ser texto y no
fórmula, un valor como "=HYPERLINK(...)" escrito por un usuario se muestra tal
cual y nunca se ejecuta.
"""

import io
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from core.datetime_utils import system_now

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ENCABEZADOS = (
    "Nombre de la sede",
    "Dirección",
    "Ciudad",
    "Departamento",
    "País",
    "Principal",
    "Estado en la solicitud",
    "Fecha de inclusión",
)

ESTILO_NORMAL = 0
ESTILO_NEGRITA = 1

_CABECERA_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_NS_HOJA = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_RELACION = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PAQUETE = "http://schemas.openxmlformats.org/package/2006/relationships"

_TIPOS_CONTENIDO = f"""{_CABECERA_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELACIONES_RAIZ = f"""{_CABECERA_XML}<Relationships xmlns="{_NS_PAQUETE}">
<Relationship Id="rId1" Type="{_NS_RELACION}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_LIBRO = f"""{_CABECERA_XML}<workbook xmlns="{_NS_HOJA}" xmlns:r="{_NS_RELACION}">
<sheets><sheet name="Sedes" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_RELACIONES_LIBRO = f"""{_CABECERA_XML}<Relationships xmlns="{_NS_PAQUETE}">
<Relationship Id="rId1" Type="{_NS_RELACION}/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="{_NS_RELACION}/styles" Target="styles.xml"/>
</Relationships>"""

_ESTILOS = f"""{_CABECERA_XML}<styleSheet xmlns="{_NS_HOJA}">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _letra_columna(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M")
    # XML no admite caracteres de control; se conservan tabulador y salto.
    return "".join(c for c in str(valor) if c in "\t\n" or ord(c) >= 32)


def _fila(numero: int, valores: list, estilo: int) -> str:
    atributo_estilo = f' s="{estilo}"' if estilo else ""
    celdas = "".join(
        f'<c r="{_letra_columna(i)}{numero}" t="inlineStr"{atributo_estilo}>'
        f'<is><t xml:space="preserve">{escape(_texto(valor))}</t></is></c>'
        for i, valor in enumerate(valores)
    )
    return f'<row r="{numero}">{celdas}</row>'


def generar_excel_sedes(solicitud: dict, sedes: list[dict]) -> bytes:
    """
    Construye el .xlsx con las sedes incluidas en la solicitud.

    `solicitud` es la consulta ampliada (con nombre y NIT de la empresa), para
    que el archivo no muestre identificadores internos, igual que el PDF.
    """
    radicado = solicitud.get("numero_radicado") or "sin radicar (borrador)"
    empresa = solicitud.get("empresa_nombre") or "No registrada"
    if solicitud.get("empresa_nit"):
        empresa += f" (NIT {solicitud['empresa_nit']})"

    filas: list[tuple[list, int]] = [
        ([f"Sedes de la solicitud {radicado}"], ESTILO_NEGRITA),
        ([f"Empresa: {empresa}"], ESTILO_NORMAL),
        ([f"Generado: {system_now():%Y-%m-%d %H:%M}"], ESTILO_NORMAL),
        ([], ESTILO_NORMAL),
        (list(ENCABEZADOS), ESTILO_NEGRITA),
    ]

    for sede in sedes:
        filas.append(
            (
                [
                    sede.get("nombre_sede"),
                    sede.get("direccion"),
                    sede.get("ciudad"),
                    sede.get("departamento"),
                    sede.get("pais"),
                    sede.get("es_principal"),
                    sede.get("estado_en_solicitud"),
                    sede.get("fecha_inclusion"),
                ],
                ESTILO_NORMAL,
            )
        )

    if not sedes:
        filas.append((["La solicitud no tiene sedes incluidas."], ESTILO_NORMAL))

    contenido_filas = "".join(
        _fila(numero, valores, estilo)
        for numero, (valores, estilo) in enumerate(filas, start=1)
    )
    hoja = (
        f'{_CABECERA_XML}<worksheet xmlns="{_NS_HOJA}">'
        f'<cols><col min="1" max="{len(ENCABEZADOS)}" width="26" customWidth="1"/></cols>'
        f"<sheetData>{contenido_filas}</sheetData>"
        "</worksheet>"
    )

    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as libro:
        libro.writestr("[Content_Types].xml", _TIPOS_CONTENIDO)
        libro.writestr("_rels/.rels", _RELACIONES_RAIZ)
        libro.writestr("xl/workbook.xml", _LIBRO)
        libro.writestr("xl/_rels/workbook.xml.rels", _RELACIONES_LIBRO)
        libro.writestr("xl/styles.xml", _ESTILOS)
        libro.writestr("xl/worksheets/sheet1.xml", hoja)

    return salida.getvalue()
