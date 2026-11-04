"""Preparación del módulo de certificaciones vigentes del auditor.

Crea la tabla `certificacion_auditor`, donde cada auditor registra sus
certificaciones vigentes junto con el archivo de soporte. El script es
idempotente y se ejecuta en cada arranque de la aplicación, igual que el
resto de módulos del proyecto.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def preparar_modulo_auditores() -> None:
    """Crea el esquema mínimo del módulo de certificaciones del auditor."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS certificacion_auditor (
                    id_certificacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    id_usuario UUID NOT NULL
                        REFERENCES usuario(id_usuario) ON DELETE CASCADE,
                    id_norma UUID
                        REFERENCES norma(id_norma) ON DELETE SET NULL,
                    tipo_certificacion VARCHAR(150) NOT NULL,
                    nombre_archivo VARCHAR(255) NOT NULL,
                    url_archivo VARCHAR(500) NOT NULL,
                    descripcion TEXT,
                    fecha_registro TIMESTAMP WITH TIME ZONE
                        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    estado VARCHAR(30) NOT NULL DEFAULT 'Vigente'
                );
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_certificacion_auditor_usuario
                    ON certificacion_auditor (id_usuario);
            """))
            await session.commit()
            logger.info("Módulo de certificaciones del auditor preparado correctamente.")
    except Exception as exc:  # pragma: no cover - arranque tolerante
        logger.error(
            "No fue posible preparar el módulo de certificaciones del auditor: %s",
            exc,
        )
