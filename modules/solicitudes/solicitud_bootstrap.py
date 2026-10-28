"""
M5 — GESTIÓN DE SOLICITUDES
Preparación mínima de la base de datos al arrancar la aplicación.

La tabla `solicitud` y su entorno (`historial_estado`, `alcance_solicitud`,
`proceso_solicitud`, `solicitud_sede`...) YA EXISTEN en la base de datos del
proyecto, así que aquí no se crea ninguna tabla. Solo se añade lo que el
Bloque 1 necesita y todavía no está:

  · la secuencia del consecutivo de radicado (SOL-005);
  · los índices de los filtros del listado (SOL-006);
  · los roles de la matriz de permisos que faltan en la tabla `rol`;
  · lo que les falta a las tablas de los Bloques 5, 6 y 7, que también
    existían de antes (`auditores_solicitud`, `calculo_auditoria`...).

Todas las sentencias son idempotentes, igual que `ensure_login_security_schema`.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger
from modules.solicitudes import estado_solicitud as estados
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


async def ensure_estados_canonicos(session) -> None:
    """
    Deja un solo nombre por estado y lo deja cerrado.

    La tabla tenia 'Radicada' y 'RADICADO', 'APROBADO' y 'Aprobada'. Para una
    consulta no son lo mismo: cada comparacion con un literal exacto perdia
    las filas escritas con la otra grafia. Aqui se reescriben al valor
    canonico de `estado_solicitud` y se anade una restriccion para que una
    grafia nueva falle al escribirse en vez de ensuciar en silencio.

    Es idempotente: si ya estan normalizados, los UPDATE no tocan ninguna fila.
    """
    casos = "\n".join(
        f"            WHEN '{alias}' THEN '{canonico}'"
        for alias, canonico in estados.ALIAS.items()
    )
    expresion = (
        "CASE UPPER(TRANSLATE(TRIM(COALESCE(estado, '')), "
        "'ÁÉÍÓÚÜÑáéíóúüñ_', 'AEIOUUNaeiouun '))\n"
        f"{casos}\n"
        "            ELSE estado\n"
        "        END"
    )

    for tabla in ("solicitud", "historial_estado"):
        await session.execute(text(f"""
            UPDATE {tabla}
            SET estado = {expresion}
            WHERE estado IS NOT NULL AND estado <> ({expresion});
        """))

    admitidos = ", ".join(f"'{estado}'" for estado in estados.ESTADOS)
    await session.execute(text(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_estado_solicitud'
            ) THEN
                ALTER TABLE solicitud DROP CONSTRAINT chk_estado_solicitud;
            END IF;
            ALTER TABLE solicitud
            ADD CONSTRAINT chk_estado_solicitud
            CHECK (estado IN ({admitidos}));
        END $$;
    """))


async def ensure_bloques_5_a_7(session) -> None:
    """
    Lo que necesitan la asignación de auditores (Bloque 5), la trazabilidad
    (Bloque 6) y el cálculo del tiempo de auditoría (Bloque 7).

    Las tablas `auditores_solicitud`, `historial_asignacion_auditor`,
    `calculo_auditoria` y `variables_norma` ya existen en la base; aquí solo
    se añade lo que les falta. Nada de esto borra ni reescribe datos.
    """

    # ---- Bloque 5 ----
    # Un auditor propuesto (SOL-047) todavía no está asignado: espera la
    # aprobación de SOL-048. La restricción original no admitía ese estado.
    await session.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'auditores_solicitud'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%estado_asignacion%'
            ) THEN
                EXECUTE (
                    SELECT 'ALTER TABLE auditores_solicitud DROP CONSTRAINT ' || quote_ident(conname)
                    FROM pg_constraint
                    WHERE conrelid = 'auditores_solicitud'::regclass AND contype = 'c'
                      AND pg_get_constraintdef(oid) LIKE '%estado_asignacion%'
                    LIMIT 1
                );
            END IF;
            ALTER TABLE auditores_solicitud
            ADD CONSTRAINT chk_estado_asignacion_auditor
            CHECK (estado_asignacion IN (
                'Propuesto', 'Asignado', 'Agendada', 'Programada',
                'Confirmado', 'Ejecutada', 'Cancelada', 'Reasignado'
            ));
        END $$;
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_auditores_solicitud_solicitud
            ON auditores_solicitud (id_solicitud);
    """))

    # ---- Bloque 6 ----
    # SOL-052 / SOL-053: observaciones de control sobre la solicitud.
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS observacion_solicitud (
            id_observacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_solicitud UUID NOT NULL REFERENCES solicitud(id_solicitud) ON DELETE CASCADE,
            texto TEXT NOT NULL,
            tipo VARCHAR(30) NOT NULL DEFAULT 'Control',
            id_usuario UUID,
            fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_observacion_solicitud
            ON observacion_solicitud (id_solicitud);
    """))

    # SOL-055: bitácora inmutable. Guarda qué permiso se ejecutó, quién y
    # sobre qué, y no se actualiza ni se borra desde la aplicación.
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS bitacora_solicitud (
            id_bitacora BIGSERIAL PRIMARY KEY,
            id_solicitud UUID NOT NULL,
            permiso_codigo VARCHAR(10) NOT NULL,
            accion VARCHAR(120) NOT NULL,
            detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
            id_usuario UUID,
            rol_usuario VARCHAR(50),
            fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_bitacora_solicitud
            ON bitacora_solicitud (id_solicitud, id_bitacora);
    """))

    # SOL-058: constancia de que el expediente se compartió con el Comité.
    await session.execute(text("""
        ALTER TABLE solicitud
        ADD COLUMN IF NOT EXISTS fecha_envio_comite TIMESTAMP;
    """))

    # ---- Bloque 7 ----
    # `calculo_auditoria` guarda el resultado; faltaban las variables de
    # entrada, el desglose y el ajuste justificado (SOL-061, 065, 068).
    for columna in (
        "ADD COLUMN IF NOT EXISTS variables JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ADD COLUMN IF NOT EXISTS desglose JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ADD COLUMN IF NOT EXISTS horas_base NUMERIC(8,2)",
        "ADD COLUMN IF NOT EXISTS ajuste_horas NUMERIC(8,2) NOT NULL DEFAULT 0",
        "ADD COLUMN IF NOT EXISTS justificacion_ajuste TEXT",
        "ADD COLUMN IF NOT EXISTS usuario_ajuste UUID",
        "ADD COLUMN IF NOT EXISTS usuario_validacion UUID",
        "ADD COLUMN IF NOT EXISTS fecha_validacion TIMESTAMP",
        "ADD COLUMN IF NOT EXISTS fecha_bloqueo TIMESTAMP",
    ):
        await session.execute(text(f"ALTER TABLE calculo_auditoria {columna};"))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_calculo_auditoria_solicitud
            ON calculo_auditoria (id_solicitud, version);
    """))

    # SOL-066: las variables base de cada norma se editan, no se escriben en
    # el programa. `variables_norma` solo tenía el nombre de la variable.
    for columna in (
        "ADD COLUMN IF NOT EXISTS valor NUMERIC(10,4)",
        "ADD COLUMN IF NOT EXISTS descripcion TEXT",
        "ADD COLUMN IF NOT EXISTS actualizado_por UUID",
        "ADD COLUMN IF NOT EXISTS fecha_actualizacion TIMESTAMP",
    ):
        await session.execute(text(f"ALTER TABLE variables_norma {columna};"))


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
            await ensure_bloques_5_a_7(session)
            await ensure_estados_canonicos(session)
            await seed_roles_solicitudes(session)
            await session.commit()
            logger.info("Modulo M5 (solicitudes) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo M5: %s", exc)
