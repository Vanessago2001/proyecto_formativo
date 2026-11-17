"""Sube a la base compartida los archivos que solo están en ESTE computador.

Antes de ``core/almacen_archivos.py`` cada servidor guardaba los archivos
subidos solo en su disco (``uploads/`` y ``storage/``). Este script los copia
a la tabla ``archivo_almacenado`` para que todo el equipo los vea.

* Compara por ruta y SHA-256: lo que ya está igual en la base no se vuelve a
  subir; si la ruta existe con otro contenido, se actualiza.
* Usa UNA sola conexión y confirma cada pocos archivos.
* No sube archivos internos (``storage/arranque.json``, temporales) ni llaves
  de firma (``.p12``, ``.pfx``, ``.pem``, ``.key``).
* Los archivos de más de ``LIMITE_BYTES`` se omiten y se informan.

Requisito: haber aplicado una vez ``documentacion/sql_archivos_compartidos.sql``.
Cada integrante lo ejecuta una vez en su equipo:

    venv\\Scripts\\python.exe -m modules.scripts.subir_archivos_locales --dry-run
    venv\\Scripts\\python.exe -m modules.scripts.subir_archivos_locales
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import mimetypes
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core import almacen_archivos
from core.almacen_archivos import LIMITE_BYTES, RAIZ_PROYECTO

LOTE = 20
EXCLUIR_RUTAS = {"storage/arranque.json"}
EXCLUIR_EXTENSIONES = {".p12", ".pfx", ".pem", ".key", ".env", ".tmp"}


@dataclass
class Resumen:
    encontrados: int = 0
    ya_estaban: int = 0
    nuevos: int = 0
    actualizados: int = 0
    omitidos_grandes: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    bytes_a_subir: int = 0


def carpetas_a_recorrer() -> list[tuple[Path, str]]:
    """(carpeta en disco, prefijo de la clave). Incluye las carpetas configurables."""
    from core.config import settings

    carpetas = [(RAIZ_PROYECTO / "uploads", "uploads"), (RAIZ_PROYECTO / "storage", "storage")]
    for valor, prefijo in (
        (settings.CERTIFICADOS_STORAGE_DIR, "storage/certificados_firmados"),
        (settings.COMITE_ACTAS_STORAGE_DIR, "storage/actas_comite"),
    ):
        carpeta = Path(valor).expanduser()
        carpeta = carpeta if carpeta.is_absolute() else RAIZ_PROYECTO / carpeta
        carpeta = carpeta.resolve()
        try:
            carpeta.relative_to(RAIZ_PROYECTO / "storage")
        except ValueError:
            carpetas.append((carpeta, prefijo))  # vive fuera de storage/: se recorre aparte
    return carpetas


def archivos_locales(carpetas: list[tuple[Path, str]] | None = None) -> list[tuple[str, Path]]:
    """[(clave, ruta en disco)] de los archivos subibles, sin repetir claves."""
    vistos: dict[str, Path] = {}
    for carpeta, prefijo in carpetas if carpetas is not None else carpetas_a_recorrer():
        if not carpeta.is_dir():
            continue
        for archivo in sorted(carpeta.rglob("*")):
            if not archivo.is_file() or archivo.is_symlink():
                continue
            if archivo.name.startswith(".") or archivo.suffix.lower() in EXCLUIR_EXTENSIONES:
                continue
            if archivo.name.endswith(".pdf.tmp"):
                continue
            clave = almacen_archivos.normalizar(f"{prefijo}/{archivo.relative_to(carpeta).as_posix()}")
            if clave is None or clave in EXCLUIR_RUTAS or clave in vistos:
                continue
            vistos[clave] = archivo
    return sorted(vistos.items())


async def migrar(dry_run: bool, carpetas=None, sesion_factory=None, salida=print) -> Resumen:
    resumen = Resumen()
    locales = archivos_locales(carpetas)
    resumen.encontrados = len(locales)

    if sesion_factory is None:
        from core.database import AsyncSessionLocal

        sesion_factory = AsyncSessionLocal

    backend = almacen_archivos.backend
    async with sesion_factory() as sesion:
        try:
            hay_tabla = await backend.disponible(sesion)
        except Exception as error:  # sin conexión: en dry-run igual se cuenta
            if not dry_run:
                raise
            salida(f"Aviso: no se pudo consultar la base ({error}); se cuentan todos como pendientes.")
            hay_tabla = False

        if not hay_tabla and not dry_run:
            salida(
                "La tabla archivo_almacenado no existe. Aplique primero "
                "documentacion/sql_archivos_compartidos.sql y vuelva a ejecutar el script."
            )
            resumen.errores.append("tabla archivo_almacenado inexistente")
            return resumen

        huellas = await backend.huellas(sesion) if hay_tabla else {}
        await sesion.rollback()  # cierra la transacción de lectura

        pendientes_en_lote = 0
        for clave, archivo in locales:
            try:
                contenido = archivo.read_bytes()
            except OSError as error:
                resumen.errores.append(f"{clave}: {error}")
                continue
            if not contenido:
                continue
            if len(contenido) > LIMITE_BYTES:
                resumen.omitidos_grandes.append(clave)
                continue
            huella = hashlib.sha256(contenido).hexdigest()
            anterior = huellas.get(clave)
            if anterior == huella:
                resumen.ya_estaban += 1
                continue
            if anterior is None:
                resumen.nuevos += 1
            else:
                resumen.actualizados += 1
            resumen.bytes_a_subir += len(contenido)
            if dry_run:
                continue

            await backend.escribir(sesion, {
                "ruta": clave,
                "nombre_original": archivo.name,
                "content_type": mimetypes.guess_type(archivo.name)[0] or "application/octet-stream",
                "tamano_bytes": len(contenido),
                "sha256": huella,
                "contenido": contenido,
                "subido_por": None,
            })
            pendientes_en_lote += 1
            if pendientes_en_lote >= LOTE:
                await sesion.commit()
                pendientes_en_lote = 0
        if pendientes_en_lote and not dry_run:
            await sesion.commit()
    return resumen


def imprimir_resumen(resumen: Resumen, dry_run: bool, salida=print) -> None:
    verbo = "se subirían" if dry_run else "subidos"
    salida("")
    salida("RESUMEN" + (" (dry-run: no se escribió nada)" if dry_run else ""))
    salida(f"  Archivos locales encontrados : {resumen.encontrados}")
    salida(f"  Ya estaban en la base        : {resumen.ya_estaban}")
    salida(f"  Nuevos ({verbo})        : {resumen.nuevos}")
    salida(f"  Con otro contenido ({verbo}): {resumen.actualizados}")
    salida(f"  Tamaño a subir               : {resumen.bytes_a_subir / (1024 * 1024):.2f} MB")
    if resumen.omitidos_grandes:
        salida(f"  Omitidos por superar {LIMITE_BYTES // (1024 * 1024)} MB: {len(resumen.omitidos_grandes)}")
        for clave in resumen.omitidos_grandes:
            salida(f"    - {clave}")
    if resumen.errores:
        salida(f"  Errores: {len(resumen.errores)}")
        for error in resumen.errores:
            salida(f"    - {error}")


def main(argv=None) -> int:
    lector = argparse.ArgumentParser(description="Sube a la base compartida los archivos de este computador.")
    lector.add_argument("--dry-run", action="store_true", help="solo cuenta; no escribe nada en la base")
    opciones = lector.parse_args(argv)
    resumen = asyncio.run(migrar(opciones.dry_run))
    imprimir_resumen(resumen, opciones.dry_run)
    return 1 if resumen.errores else 0


if __name__ == "__main__":
    sys.exit(main())
