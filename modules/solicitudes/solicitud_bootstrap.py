"""
M5 — GESTIÓN DE SOLICITUDES
Preparación mínima de la base de datos al arrancar la aplicación.

La tabla `solicitud` y su entorno (`historial_estado`, `alcance_solicitud`,
`proceso_solicitud`, `solicitud_sede`...) YA EXISTEN en la base de datos del
proyecto, así que aquí no se crea ninguna tabla. Solo se añade lo que el
Bloque 1 necesita y todavía no está:

  · la secuencia del consecutivo de radicado (SOL-005);
  · los índices de los filtros del listado (SOL-006);
  · los roles de la matriz de permisos que faltan en la tabla `rol`.

Todas las sentencias son idempotentes, igual que `ensure_login_security_schema`.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger
from modules.solicitudes.solicitud_permissions import ROL_PUB

# Roles que exige la matriz de M5 y que no están en la tabla `rol`.
#
# 'Super Administrador', 'Administrador', 'Auxiliar', 'Empresa', 'Auditor' y
# 'Comité' ya existen; el módulo los reconoce mediante ALIAS_ROLES.
#
# NO se crea un rol 'Aprobador': el aprobador es el administrador, así que la
# columna APR del Excel la cubre el rol 'Administrador'.
ROLES_FALTANTES = [
    (ROL_PUB, "Consulta pública; sin acceso a solicitudes."),
]


async def ensure_solicitudes_schema(session) -> None:
    """Añade la secuencia y los índices que usa el Bloque 1."""

    # Consecutivo del número de radicado (SOL-005).
    await session.execute(text("""
        CREATE SEQUENCE IF NOT EXISTS solicitud_radicado_seq
            START WITH 1
            INCREMENT BY 1;
    """))

    # Índices de los filtros más frecuentes del listado (SOL-006).
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_solicitud_empresa_viva
            ON solicitud (id_empresa)
            WHERE deleted_at IS NULL;
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_solicitud_estado_viva
            ON solicitud (estado)
            WHERE deleted_at IS NULL;
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_historial_estado_solicitud
            ON historial_estado (id_solicitud);
    """))


async def seed_roles_solicitudes(session) -> None:
    """
    Inserta los roles de la matriz de permisos que aún no existen.

    No toca los roles ya creados: solo agrega los que faltan para que las
    ocho columnas del Excel tengan una fila real en la tabla `rol`.
    """
    for nombre, descripcion in ROLES_FALTANTES:
        existente = await session.execute(
            text("SELECT id_rol FROM rol WHERE LOWER(nombre) = LOWER(:nombre);"),
            {"nombre": nombre},
        )

        if existente.scalar() is None:
            await session.execute(
                text(
                    "INSERT INTO rol (nombre, descripcion) "
                    "VALUES (:nombre, :descripcion);"
                ),
                {"nombre": nombre, "descripcion": descripcion},
            )
            logger.info("Rol '%s' creado para la matriz de permisos M5.", nombre)


async def preparar_modulo_solicitudes() -> None:
    """
    Punto de entrada unico del modulo, para llamar al arrancar la aplicacion.

    Abre su propia sesion a proposito: asi la preparacion de M5 no se pierde
    si falla cualquier otra parte de la siembra inicial, ni arrastra al resto
    si fallara la suya.
    """
    async with AsyncSessionLocal() as session:
        try:
            await ensure_solicitudes_schema(session)
            await seed_roles_solicitudes(session)
            await session.commit()
            logger.info("Modulo M5 (solicitudes) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo M5: %s", exc)
