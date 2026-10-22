"""
Arranque de la aplicación: decide si hay que preparar la base.

Cada módulo trae un `preparar_modulo_*` que crea índices, añade columnas y
siembra datos. Todo eso es idempotente, pero tarda unos 35 segundos y se
repite en cada arranque aunque no haya cambiado nada.

Aquí se decide si hace falta repetirlo:

  · Se calcula una huella con el contenido de los archivos que preparan la
    base y con la base a la que se apunta.
  · Si la huella coincide con la del último arranque que sí preparó, y las
    piezas clave siguen en la base, se salta la preparación.
  · Si cambia cualquiera de esos archivos, si se apunta a otra base o si
    falta una pieza, se prepara otra vez sin que nadie tenga que acordarse.

Se puede forzar con la variable de entorno PREPARAR_BASE:

    PREPARAR_BASE=auto     (por defecto) decide como se explicó arriba
    PREPARAR_BASE=siempre  prepara en cada arranque, como antes
    PREPARAR_BASE=nunca    no prepara nunca (útil en producción)

La huella se guarda en `storage/arranque.json`, que no va al repositorio.
"""

import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from core.config import settings
from core.database import AsyncSessionLocal
from core.logger import logger

RAIZ = Path(__file__).resolve().parent.parent
MARCA = RAIZ / "storage" / "arranque.json"

# Archivos que preparan la base. Si cambia cualquiera, se vuelve a preparar.
ARCHIVOS_DE_PREPARACION = (
    "main.py",
    "modules/agenda_auditor/agenda_bootstrap.py",
    "modules/solicitudes/solicitud_bootstrap.py",
    "modules/auditorias/auditoria_bootstrap.py",
    "modules/comite/comite_bootstrap.py",
    "modules/empresas/empresas_bootstrap.py",
    "modules/aprobaciones/aprobacion_bootstrap.py",
    "modules/certificados/certificados_bootstrap.py",
)

# Piezas que añadieron esos archivos. Si falta una, la base no está al día
# aunque la huella coincida (por ejemplo, tras restaurar una copia vieja).
PIEZAS_CLAVE = (
    ("tabla", "bitacora_solicitud"),
    ("tabla", "observacion_solicitud"),
    ("tabla", "historial_documento_empresa"),
    ("tabla", "aprobacion_pendiente"),
    ("tabla", "contacto_sede"),
    ("columna", "documento_empresa.nombre_archivo"),
    ("columna", "calculo_auditoria.desglose"),
    ("columna", "solicitud.fecha_envio_comite"),
)


def _modo() -> str:
    valor = (getattr(settings, "PREPARAR_BASE", "auto") or "auto").strip().lower()
    if valor in ("1", "true", "si", "sí", "siempre"):
        return "siempre"
    if valor in ("0", "false", "no", "nunca"):
        return "nunca"
    return "auto"


def huella() -> str:
    """Resume en un texto corto el estado de los archivos de preparación."""
    resumen = hashlib.sha256()
    resumen.update(settings.DATABASE_URL.encode("utf-8"))
    for relativo in ARCHIVOS_DE_PREPARACION:
        archivo = RAIZ / relativo
        resumen.update(relativo.encode("utf-8"))
        resumen.update(archivo.read_bytes() if archivo.is_file() else b"-")
    return resumen.hexdigest()


def _huella_guardada() -> str | None:
    try:
        return json.loads(MARCA.read_text(encoding="utf-8")).get("huella")
    except (OSError, ValueError):
        return None


def guardar_huella(valor: str) -> None:
    try:
        MARCA.parent.mkdir(parents=True, exist_ok=True)
        MARCA.write_text(json.dumps({"huella": valor}, indent=1), encoding="utf-8")
    except OSError as error:
        # Si no se puede escribir la marca, la próxima vez preparará de nuevo:
        # molesto, pero nunca incorrecto.
        logger.warning("No se pudo guardar la marca de arranque: %s", error)


async def _faltan_piezas() -> bool:
    """Una sola consulta para comprobar que la base ya está al día."""
    tablas = [nombre for tipo, nombre in PIEZAS_CLAVE if tipo == "tabla"]
    columnas = [nombre.split(".") for tipo, nombre in PIEZAS_CLAVE if tipo == "columna"]

    # Una sola consulta: la base está en un servidor remoto y cada viaje
    # cuesta cerca de un segundo.
    async with AsyncSessionLocal() as session:
        resultado = await session.execute(
            text("""
                SELECT 'tabla' AS tipo, table_name AS tabla, '' AS columna
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = ANY(:tablas)

                UNION ALL

                SELECT 'columna', table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(:tablas_de_columnas)
                  AND column_name = ANY(:columnas)
            """),
            {
                "tablas": tablas,
                "tablas_de_columnas": [tabla for tabla, _ in columnas],
                "columnas": [columna for _, columna in columnas],
            },
        )
        hay_tabla = set()
        hay_columna = set()
        for tipo, tabla, columna in resultado.all():
            if tipo == "tabla":
                hay_tabla.add(tabla)
            else:
                hay_columna.add((tabla, columna))

    faltan = [t for t in tablas if t not in hay_tabla]
    faltan += [f"{t}.{c}" for t, c in columnas if (t, c) not in hay_columna]

    if faltan:
        logger.info("La base no está al día, falta: %s", ", ".join(faltan))
    return bool(faltan)


async def debe_preparar_la_base() -> tuple[bool, str]:
    """
    Devuelve (preparar, motivo). El motivo se escribe en el registro para
    que siempre se sepa por qué un arranque tardó o por qué fue inmediato.
    """
    modo = _modo()
    if modo == "siempre":
        return True, "PREPARAR_BASE=siempre"
    if modo == "nunca":
        return False, "PREPARAR_BASE=nunca"

    actual = huella()
    if _huella_guardada() != actual:
        return True, "cambió algún archivo de preparación o la base de datos"

    try:
        if await _faltan_piezas():
            return True, "faltan piezas del esquema en la base"
    except Exception as error:
        # Ante la duda, preparar: es lento pero seguro.
        logger.warning("No se pudo comprobar el esquema (%s); se prepara igual.", error)
        return True, "no se pudo comprobar el esquema"

    return False, "la base ya estaba preparada"
