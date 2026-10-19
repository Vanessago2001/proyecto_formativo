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
