"""Almacén central de archivos subidos: base de datos compartida + disco local.

POR QUÉ
-------
La base (PostgreSQL en Aiven) es compartida por todo el equipo, pero cada
integrante corre su propio servidor. Antes los archivos subidos solo quedaban
en el disco del computador que los recibió (``uploads/`` y ``storage/``): los
demás veían el registro en la base pero no el archivo.

CÓMO
----
* La clave de cada archivo es su ruta relativa a la raíz del proyecto,
  normalizada: ``uploads/auditores/x.pdf``, ``storage/apelaciones/<id>/y.png``.
  Es la misma ruta que ya guardan las tablas (``/uploads/...``,
  ``storage\\...``); ``normalizar`` convierte cualquiera de esas formas en la
  clave, así que no hay que tocar los datos existentes.
* ``guardar`` escribe el contenido en la tabla ``archivo_almacenado`` (UPSERT
  por ruta) y en el disco local, que hace de caché.
* ``leer`` / ``ruta_local`` usan el disco si el archivo está; si no, lo traen de
  la base y lo dejan en el disco para la próxima vez.
* ``eliminar`` lo borra de la base y del disco.

CONEXIONES
----------
Cada servidor tiene un pool de 1 (+1) conexiones y la base admite 20 en total.
Por eso se usa SIEMPRE la sesión de la petición (``db``) y la escritura va en un
SAVEPOINT: queda en la misma transacción que el registro que guarda la ruta y
se confirma con el ``commit`` del módulo. Solo si no se pasa ``db`` se abre una
sesión propia, que se confirma y se cierra enseguida. Los listados no llaman a
este módulo: el contenido se lee únicamente al descargar.

SIN LA TABLA
------------
Si el SQL ``documentacion/sql_archivos_compartidos.sql`` todavía no se aplicó,
todo sigue funcionando como antes (solo disco) y se registra un aviso una sola
vez. Ningún error de la base en este módulo produce un 500: se registra y se
continúa con el disco.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import logger

RAIZ_PROYECTO = Path(__file__).resolve().parents[1]
CARPETAS_PERMITIDAS = ("uploads", "storage")
# Debe coincidir con el CHECK de la tabla (documentacion/sql_archivos_compartidos.sql).
# 25 MB: el mayor límite de subida del sistema (evidencias de auditoría, M7).
LIMITE_BYTES = 25 * 1024 * 1024
# Si la tabla no existe, se vuelve a mirar cada tanto (por si se aplicó el SQL).
REVISAR_TABLA_CADA_SEGUNDOS = 300

_PREFIJO_FIRMADO = "/archivos/"


# ----------------------------------------------------------------------
# Rutas
# ----------------------------------------------------------------------

def normalizar(ruta) -> str | None:
    """Clave única del archivo, o None si la ruta no es válida.

    Acepta ``/uploads/x``, ``uploads/x``, ``storage\\x``, un enlace firmado
    ``/archivos/<exp>/<firma>/x`` (que vive en uploads/) o una ruta absoluta
    dentro del proyecto. Rechaza ``..``, unidades de Windows y cualquier ruta
    fuera de ``uploads/`` o ``storage/``.
    """
    if ruta is None:
        return None
    if isinstance(ruta, Path) and ruta.is_absolute():
        try:
            ruta = ruta.resolve().relative_to(RAIZ_PROYECTO).as_posix()
        except (ValueError, OSError):
            return None
    texto = str(ruta).strip().split("#", 1)[0].split("?", 1)[0]
    if not texto:
        return None
    texto = unquote(texto).replace("\\", "/")
    if texto.startswith(_PREFIJO_FIRMADO):
        partes_firmadas = texto[len(_PREFIJO_FIRMADO):].split("/", 2)
        if len(partes_firmadas) < 3:
            return None
        texto = "uploads/" + partes_firmadas[2]
    if ":" in texto:
        # 'C:/...' u otra ruta absoluta de Windows: solo vale si es del proyecto.
        try:
            texto = Path(texto).resolve().relative_to(RAIZ_PROYECTO).as_posix()
        except (ValueError, OSError):
            return None
    partes = [p for p in texto.split("/") if p not in ("", ".")]
    if len(partes) < 2 or any(p == ".." or ":" in p for p in partes):
        return None
    if partes[0] not in CARPETAS_PERMITIDAS:
        return None
    return str(PurePosixPath(*partes))


def _ruta_disco(clave: str, disco: Path | str | None) -> Path | None:
    if disco is not None:
        return Path(disco)
    candidato = (RAIZ_PROYECTO / clave).resolve()
    try:
        candidato.relative_to(RAIZ_PROYECTO)
    except ValueError:
        return None
    return candidato


def _escribir_disco(destino: Path, contenido: bytes) -> None:
    """Escritura atómica: nunca queda un archivo a medias en el disco."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=destino.parent, prefix=".tmp-", suffix=destino.suffix)
    try:
        with os.fdopen(descriptor, "wb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, destino)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


def _id_usuario(usuario) -> str | None:
    if usuario is None:
        return None
    valor = usuario.get("id_usuario") if isinstance(usuario, dict) else usuario
    try:
        return str(UUID(str(valor)))
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# Acceso a la tabla
# ----------------------------------------------------------------------

class _AlmacenBD:
    """Operaciones sobre ``archivo_almacenado``. Las pruebas lo reemplazan."""

    def __init__(self) -> None:
        self._disponible: bool | None = None
        self._revisado = 0.0
        self._avisado = False

    def acepta(self, db) -> bool:
        # Con un doble de prueba (AsyncMock, FakeDB) no se toca la base: las
        # pruebas de cada módulo siguen viendo solo sus propias consultas.
        return db is None or isinstance(db, AsyncSession)

    def sin_tabla_reciente(self) -> bool:
        """True si hace poco se comprobó que la tabla no existe (evita el SAVEPOINT)."""
        return (
            self._disponible is False
            and time.monotonic() - self._revisado < REVISAR_TABLA_CADA_SEGUNDOS
        )

    async def disponible(self, sesion: AsyncSession) -> bool:
        if self._disponible:
            return True
        ahora = time.monotonic()
        if self._disponible is False and ahora - self._revisado < REVISAR_TABLA_CADA_SEGUNDOS:
            return False
        resultado = await sesion.execute(
            text("SELECT to_regclass('public.archivo_almacenado') IS NOT NULL")
        )
        self._disponible = bool(resultado.scalar())
        self._revisado = ahora
        if not self._disponible and not self._avisado:
            self._avisado = True
            logger.warning(
                "La tabla archivo_almacenado no existe: los archivos subidos solo se "
                "guardan en el disco de este computador. Aplique "
                "documentacion/sql_archivos_compartidos.sql para compartirlos."
            )
        return self._disponible

    async def escribir(self, sesion: AsyncSession, fila: dict) -> None:
        await sesion.execute(
            text("""
                INSERT INTO archivo_almacenado (
                    ruta, nombre_original, content_type, tamano_bytes, sha256,
                    contenido, subido_por, fecha_subida
                )
                VALUES (
                    :ruta, :nombre_original, :content_type, :tamano_bytes, :sha256,
                    :contenido, CAST(:subido_por AS uuid), now()
                )
                ON CONFLICT (ruta) DO UPDATE SET
                    nombre_original = EXCLUDED.nombre_original,
                    content_type    = EXCLUDED.content_type,
                    tamano_bytes    = EXCLUDED.tamano_bytes,
                    sha256          = EXCLUDED.sha256,
                    contenido       = EXCLUDED.contenido,
                    subido_por      = EXCLUDED.subido_por,
                    fecha_subida    = now();
            """),
            fila,
        )

    async def obtener(self, sesion: AsyncSession, clave: str) -> bytes | None:
        resultado = await sesion.execute(
            text("SELECT contenido FROM archivo_almacenado WHERE ruta = :ruta"),
            {"ruta": clave},
        )
        valor = resultado.scalar()
        return bytes(valor) if valor is not None else None

    async def existe(self, sesion: AsyncSession, clave: str) -> bool:
        resultado = await sesion.execute(
            text("SELECT 1 FROM archivo_almacenado WHERE ruta = :ruta"),
            {"ruta": clave},
        )
        return resultado.first() is not None

    async def tamanos(self, sesion: AsyncSession, claves: list[str]) -> dict[str, int]:
        resultado = await sesion.execute(
            text("SELECT ruta, tamano_bytes FROM archivo_almacenado WHERE ruta = ANY(:rutas)"),
            {"rutas": claves},
        )
        return {fila[0]: int(fila[1] or 0) for fila in resultado.all()}

    async def huellas(self, sesion: AsyncSession) -> dict[str, str]:
        """{ruta: sha256} de todo lo guardado (lo usa el script de migración)."""
        resultado = await sesion.execute(text("SELECT ruta, sha256 FROM archivo_almacenado"))
        return {fila[0]: (fila[1] or "").strip() for fila in resultado.all()}

    async def borrar(self, sesion: AsyncSession, claves: list[str]) -> None:
        await sesion.execute(
            text("DELETE FROM archivo_almacenado WHERE ruta = ANY(:rutas)"),
            {"rutas": list(claves)},
        )


backend = _AlmacenBD()


@asynccontextmanager
async def _transaccion(db):
    """Sesión de la petición dentro de un SAVEPOINT, o una sesión propia breve.

    Con la sesión de la petición, un fallo deshace solo el SAVEPOINT y la
    transacción del módulo sigue utilizable. La sesión propia se confirma y se
    cierra al salir.
    """
    if db is not None:
        async with db.begin_nested():
            yield db
        return
    from core.database import AsyncSessionLocal  # import tardío: evita crear el motor en las pruebas

    async with AsyncSessionLocal() as propia:
        async with propia.begin():
            yield propia


async def _con_base(db, operacion, por_defecto):
    """Ejecuta ``operacion(sesion)`` si la tabla existe; si algo falla devuelve ``por_defecto``."""
    if not backend.acepta(db) or backend.sin_tabla_reciente():
        return por_defecto
    try:
        async with _transaccion(db) as sesion:
            if not await backend.disponible(sesion):
                return por_defecto
            return await operacion(sesion)
    except Exception as error:  # nunca un 500 por el almacén compartido
        logger.warning("Almacén de archivos: se continúa solo con el disco (%s)", error)
        return por_defecto


# ----------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------

class RutaNoValida(ValueError):
    pass


async def guardar(
    ruta,
    contenido: bytes,
    *,
    db: AsyncSession | None = None,
    disco: Path | str | None = None,
    content_type: str | None = None,
    nombre: str | None = None,
    usuario=None,
) -> str | None:
    """Guarda el archivo en el disco local y en la base. Devuelve la clave.

    ``disco`` es la ruta física cuando el módulo la decide (carpetas
    configurables); si se omite, es ``<raíz del proyecto>/<clave>``.
    Un archivo de más de ``LIMITE_BYTES`` solo queda en el disco (con aviso).
    """
    clave = normalizar(ruta)
    if clave is None and disco is not None:
        # Carpeta fuera de uploads/ y storage/ (configuración propia): solo disco, como antes.
        logger.debug("Almacén de archivos: %r no es una ruta compartible; queda solo en disco.", ruta)
        _escribir_disco(Path(disco), bytes(contenido))
        return None
    if clave is None:
        raise RutaNoValida(f"Ruta de archivo no válida: {ruta!r}")
    destino = _ruta_disco(clave, disco)
    if destino is None:
        raise RutaNoValida(f"Ruta de archivo no válida: {ruta!r}")
    contenido = bytes(contenido)
    _escribir_disco(destino, contenido)

    if not contenido:
        return clave
    if len(contenido) > LIMITE_BYTES:
        logger.warning(
            "Almacén de archivos: %s pesa %s bytes (límite %s); queda solo en el disco local.",
            clave, len(contenido), LIMITE_BYTES,
        )
        return clave

    fila = {
        "ruta": clave,
        "nombre_original": nombre or PurePosixPath(clave).name,
        "content_type": content_type
        or mimetypes.guess_type(nombre or clave)[0]
        or "application/octet-stream",
        "tamano_bytes": len(contenido),
        "sha256": hashlib.sha256(contenido).hexdigest(),
        "contenido": contenido,
        "subido_por": _id_usuario(usuario),
    }

    async def _escribir(sesion):
        try:
            async with sesion.begin_nested():
                await backend.escribir(sesion, fila)
        except IntegrityError:
            # El usuario ya no existe (FK): se guarda sin autor.
            await backend.escribir(sesion, {**fila, "subido_por": None})
        return True

    await _con_base(db, _escribir, False)
    return clave


async def leer(ruta, *, db: AsyncSession | None = None, disco: Path | str | None = None) -> bytes | None:
    """Contenido del archivo: del disco si está; si no, de la base (y queda en caché)."""
    clave = normalizar(ruta)
    if clave is None:
        # Ruta fuera de uploads/ y storage/ (p. ej. absoluta antigua): solo disco, como antes.
        return Path(disco).read_bytes() if disco is not None and Path(disco).is_file() else None
    destino = _ruta_disco(clave, disco)
    if destino is not None and destino.is_file():
        return destino.read_bytes()

    contenido = await _con_base(db, lambda s: backend.obtener(s, clave), None)
    if contenido is not None and destino is not None:
        try:
            _escribir_disco(destino, contenido)
        except OSError as error:
            logger.warning("Almacén de archivos: no se pudo dejar %s en caché (%s)", clave, error)
    return contenido


async def ruta_local(ruta, *, db: AsyncSession | None = None, disco: Path | str | None = None) -> Path | None:
    """Ruta en el disco local lista para ``FileResponse`` (la trae de la base si falta)."""
    clave = normalizar(ruta)
    if clave is None:
        return Path(disco) if disco is not None and Path(disco).is_file() else None
    destino = _ruta_disco(clave, disco)
    if destino is None:
        return None
    if destino.is_file():
        return destino
    await leer(clave, db=db, disco=destino)
    return destino if destino.is_file() else None


async def existe(ruta, *, db: AsyncSession | None = None, disco: Path | str | None = None) -> bool:
    clave = normalizar(ruta)
    if clave is None:
        return False
    destino = _ruta_disco(clave, disco)
    if destino is not None and destino.is_file():
        return True
    return bool(await _con_base(db, lambda s: backend.existe(s, clave), False))


async def eliminar(
    ruta,
    *,
    db: AsyncSession | None = None,
    disco: Path | str | None = None,
    borrar_disco: bool = True,
    confirmar: bool = False,
) -> None:
    """Borra el archivo de la base y del disco local (sin error si no estaba).

    ``borrar_disco=False`` borra solo la fila (dentro de la transacción del
    módulo), cuando el módulo retira el archivo local después del ``commit``.
    ``confirmar=True`` hace ``commit`` de la sesión de la petición: para cuando
    el módulo ya confirmó su transacción y luego retira el archivo viejo.
    """
    await eliminar_varios(
        [(ruta, disco)], db=db, borrar_disco=borrar_disco, confirmar=confirmar
    )


async def eliminar_varios(
    archivos,
    *,
    db: AsyncSession | None = None,
    borrar_disco: bool = True,
    confirmar: bool = False,
) -> None:
    """Como ``eliminar`` para varios ``(ruta, disco)`` con UNA sola consulta a la base."""
    claves = []
    for ruta, disco in archivos:
        clave = normalizar(ruta)
        if clave is None:
            if disco is not None and borrar_disco:
                try:
                    Path(disco).unlink(missing_ok=True)
                except OSError as error:
                    logger.warning("Almacén de archivos: no se pudo borrar %s del disco (%s)", disco, error)
            continue
        claves.append(clave)
        destino = _ruta_disco(clave, disco)
        if destino is not None and borrar_disco:
            try:
                destino.unlink(missing_ok=True)
            except OSError as error:
                logger.warning("Almacén de archivos: no se pudo borrar %s del disco (%s)", clave, error)
    if not claves:
        return

    async def _borrar(sesion):
        await backend.borrar(sesion, claves)
        return True

    borrado = await _con_base(db, _borrar, False)
    if borrado and confirmar and db is not None:
        try:
            await db.commit()
        except Exception as error:
            logger.warning("Almacén de archivos: no se confirmó el borrado de %s (%s)", claves, error)
            await db.rollback()


async def tamanos(rutas, *, db: AsyncSession | None = None) -> dict[str, int]:
    """{clave: tamaño} de los archivos que están en la base, en UNA consulta y sin el contenido.

    Para las pantallas que muestran "disponible / formato / tamaño" de varios
    archivos: se llama solo con los que faltan en el disco local.
    """
    claves = sorted({clave for clave in (normalizar(r) for r in rutas) if clave})
    if not claves:
        return {}
    return await _con_base(db, lambda s: backend.tamanos(s, claves), {})
