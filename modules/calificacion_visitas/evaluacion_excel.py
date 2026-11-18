"""
Archivo Excel de la evaluación de una visita (obligatorio al finalizarla).

Pedido de la usuaria (18/11/2026): al finalizar la auditoría, en la misma
ventana el auditor deja la calificación de la visita y adjunta el Excel en
el que hizo toda la calificación; sin los dos no se finaliza. El Comité lo
descarga desde el expediente ("Calificación de los auditores").

DÓNDE SE GUARDA (sin tablas ni columnas nuevas)
-----------------------------------------------
No hay en la base una columna para la ruta de este archivo:

  · `evidencia` (M7) exige `id_auditoria`, y la visita de la agenda
    (`programacion_visita`) no tiene una auditoría M7 asociada (la tabla
    `auditoria` está vacía). Crear una auditoría "de mentira" solo para
    colgar el archivo ensuciaría el módulo M7.
  · `calificacion_visita` no tiene columnas para archivos.

Por eso la ruta se DERIVA de los identificadores, que ya quedan registrados
en `calificacion_visita` (id_programacion + id_auditor):

    storage/calificaciones_visita/<id_programacion>/<id_auditor>.xlsx|.xls
    storage/calificaciones_visita/<id_programacion>/<id_auditor>.json

El .json guarda el nombre original, la extensión, el tamaño, el SHA-256 y
la fecha. Los dos se escriben con core/almacen_archivos.py (disco local y,
cuando se aplique documentacion/sql_archivos_compartidos.sql, también la
base compartida, en la misma transacción que la calificación).

Si más adelante se quiere la ruta en la base, el SQL mínimo está en
documentacion/sql_calificacion_visitas_excel.sql (no aplicado).
"""

from __future__ import annotations

import hashlib
import io
import json
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, status

from core import almacen_archivos
from core.logger import logger

CARPETA = "storage/calificaciones_visita"
EXTENSIONES = {".xlsx", ".xls"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10 MB
TIPOS_CONTENIDO = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}
# Firma de un documento OLE2 (Excel 97-2003, .xls).
FIRMA_OLE2 = bytes.fromhex("D0CF11E0A1B11AE1")
FIRMA_ZIP = b"PK\x03\x04"

MENSAJE_FALTA_EXCEL = (
    "Adjunta el archivo Excel (.xlsx o .xls) con la calificación de la visita: "
    "es obligatorio para finalizar la auditoría."
)


def _error(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detalle)


def nombre_seguro(nombre: str | None) -> str:
    base = Path(str(nombre or "evaluacion")).name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    limpio = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base).strip()
    return (limpio or "evaluacion")[:150]


@dataclass
class ExcelValidado:
    nombre: str
    extension: str
    contenido: bytes
    sha256: str

    @property
    def content_type(self) -> str:
        return TIPOS_CONTENIDO[self.extension]


def _es_xlsx(contenido: bytes) -> bool:
    if not contenido.startswith(FIRMA_ZIP):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
            nombres = set(libro.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return False
    # Un .docx o un .zip cualquiera también empiezan por PK: se exige el libro.
    return "[Content_Types].xml" in nombres and "xl/workbook.xml" in nombres


def _es_xls(contenido: bytes) -> bool:
    return contenido.startswith(FIRMA_OLE2)


def validar_excel(nombre: str | None, contenido: bytes | None) -> ExcelValidado:
    """Extensión, tamaño y tipo REAL del contenido (422 con mensaje claro)."""
    if contenido is None or not nombre:
        raise _error(MENSAJE_FALTA_EXCEL)
    nombre_limpio = nombre_seguro(nombre)
    extension = PurePosixPath(nombre_limpio).suffix.lower()
    if extension not in EXTENSIONES:
        raise _error(
            f"El archivo «{nombre_limpio}» no es un Excel: solo se aceptan archivos .xlsx o .xls."
        )
    if not contenido:
        raise _error("El archivo Excel está vacío.")
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise _error(
            f"El archivo Excel supera el máximo de {TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB."
        )
    valido = _es_xlsx(contenido) if extension == ".xlsx" else _es_xls(contenido)
    if not valido:
        raise _error(
            f"El contenido de «{nombre_limpio}» no corresponde a un libro de Excel {extension} válido. "
            "Guárdalo de nuevo desde Excel y vuelve a adjuntarlo."
        )
    return ExcelValidado(
        nombre=nombre_limpio,
        extension=extension,
        contenido=bytes(contenido),
        sha256=hashlib.sha256(contenido).hexdigest(),
    )


# ----------------------------------------------------------------------
# Rutas derivadas
# ----------------------------------------------------------------------

def ruta_excel(id_programacion, id_auditor, extension: str) -> str:
    return f"{CARPETA}/{id_programacion}/{id_auditor}{extension}"


def ruta_metadatos(id_programacion, id_auditor) -> str:
    return f"{CARPETA}/{id_programacion}/{id_auditor}.json"


def ruta_disco(clave: str) -> Path:
    return almacen_archivos.RAIZ_PROYECTO / clave


async def guardar_excel(db, id_programacion, id_auditor, excel: ExcelValidado, usuario) -> dict:
    """Escribe el Excel y sus metadatos. Devuelve los metadatos y las rutas escritas.

    El registro en la base compartida (si existe) va en un SAVEPOINT de la
    sesión de la petición: se confirma o se deshace con el commit/rollback
    de la finalización. Quien llama borra los archivos del disco si falla.
    """
    clave = ruta_excel(id_programacion, id_auditor, excel.extension)
    metadatos = {
        "id_programacion": str(id_programacion),
        "id_auditor": str(id_auditor),
        "nombre_original": excel.nombre,
        "extension": excel.extension,
        "content_type": excel.content_type,
        "tamano_bytes": len(excel.contenido),
        "sha256": excel.sha256,
        "ruta": clave,
        "fecha_subida": datetime.now(timezone.utc).isoformat(),
    }
    escritas: list[str] = []
    await almacen_archivos.guardar(
        clave, excel.contenido, db=db, content_type=excel.content_type, nombre=excel.nombre, usuario=usuario
    )
    escritas.append(clave)
    clave_meta = ruta_metadatos(id_programacion, id_auditor)
    await almacen_archivos.guardar(
        clave_meta,
        json.dumps(metadatos, ensure_ascii=False).encode("utf-8"),
        db=db,
        content_type="application/json",
        usuario=usuario,
    )
    escritas.append(clave_meta)
    return {"metadatos": metadatos, "rutas": escritas}


def borrar_del_disco(rutas: list[str]) -> None:
    """Deshace lo escrito en el disco cuando la transacción falla."""
    for clave in rutas or []:
        try:
            ruta_disco(clave).unlink(missing_ok=True)
        except OSError as error:  # pragma: no cover - solo registro
            logger.warning("No se pudo borrar %s tras deshacer la finalización: %s", clave, error)


async def leer_metadatos(db, id_programacion, id_auditor) -> dict | None:
    """Metadatos del Excel de esa evaluación, o None si no se adjuntó."""
    contenido = await almacen_archivos.leer(ruta_metadatos(id_programacion, id_auditor), db=db)
    if not contenido:
        return None
    try:
        datos = json.loads(contenido.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if datos.get("extension") not in EXTENSIONES:
        return None
    return datos
