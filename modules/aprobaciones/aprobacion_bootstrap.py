"""
Aprobaciones de permisos REQ · preparación de la base al arrancar.

Crea la tabla donde quedan las acciones que un rol pidió y un superior debe
aprobar. La sentencia es idempotente y no toca ninguna tabla existente.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def ensure_aprobaciones_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS aprobacion_pendiente (
            id_aprobacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            codigo_permiso VARCHAR(20) NOT NULL,
            descripcion VARCHAR(150) NOT NULL,
            detalle VARCHAR(255) NOT NULL,
            id_empresa UUID REFERENCES empresa(id_empresa) ON DELETE CASCADE,
            datos JSONB NOT NULL DEFAULT CAST('{}' AS JSONB),
            estado VARCHAR(20) NOT NULL DEFAULT 'Pendiente'
                CONSTRAINT chk_estado_aprobacion
                CHECK (estado IN ('Pendiente', 'Aprobada', 'Rechazada')),
            id_solicitante UUID NOT NULL REFERENCES usuario(id_usuario),
            fecha_solicitud TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            id_revisor UUID REFERENCES usuario(id_usuario),
            fecha_revision TIMESTAMP,
            observacion_revision TEXT
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_aprobacion_pendiente_estado
            ON aprobacion_pendiente (estado);
    """))


async def preparar_aprobaciones() -> None:
    """Punto de entrada al arrancar, con su propia sesión."""
    async with AsyncSessionLocal() as session:
        try:
            await ensure_aprobaciones_schema(session)
            await session.commit()
            logger.info("Tabla de aprobaciones (permisos REQ) preparada correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar las aprobaciones: %s", exc)
