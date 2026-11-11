"""Preparación persistente del registro de acciones del comité."""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def ensure_comite_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS comite_accion (
            id_accion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_solicitud UUID NOT NULL REFERENCES solicitud(id_solicitud) ON DELETE CASCADE,
            accion VARCHAR(50) NOT NULL,
            datos JSONB NOT NULL DEFAULT CAST('{}' AS JSONB),
            id_usuario VARCHAR(100),
            fecha TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_comite_accion_solicitud_fecha
            ON comite_accion (id_solicitud, fecha DESC);
    """))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS comite_acta (
            id_acta UUID PRIMARY KEY,
            id_solicitud UUID NOT NULL REFERENCES solicitud(id_solicitud) ON DELETE RESTRICT,
            version INTEGER NOT NULL CHECK (version > 0),
            estado VARCHAR(20) NOT NULL
                CHECK (estado IN ('GENERADA', 'FIRMADA', 'ANULADA')),
            huella_pdf VARCHAR(64) NOT NULL,
            huella_firmante VARCHAR(128),
            id_usuario_genero UUID REFERENCES usuario(id_usuario) ON DELETE SET NULL,
            id_usuario_firmante UUID REFERENCES usuario(id_usuario) ON DELETE SET NULL,
            datos JSONB NOT NULL,
            fecha_generacion TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_firma TIMESTAMP WITH TIME ZONE,
            UNIQUE (id_solicitud, version)
        );
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS huella_pdf VARCHAR(64);
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS huella_firmante VARCHAR(128);
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS id_usuario_genero UUID
            REFERENCES usuario(id_usuario) ON DELETE SET NULL;
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS id_usuario_firmante UUID
            REFERENCES usuario(id_usuario) ON DELETE SET NULL;
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS fecha_generacion TIMESTAMP WITH TIME ZONE
            NOT NULL DEFAULT CURRENT_TIMESTAMP;
    """))
    await session.execute(text("""
        ALTER TABLE comite_acta
        ADD COLUMN IF NOT EXISTS fecha_firma TIMESTAMP WITH TIME ZONE;
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_comite_acta_solicitud_version
            ON comite_acta (id_solicitud, version DESC);
    """))


async def preparar_modulo_comite() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_comite_schema(session)
            await session.commit()
            logger.info("Tabla de acciones del comité preparada correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el módulo de comité: %s", exc)
            raise
