"""Preparación idempotente de los objetos auxiliares de M9."""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def preparar_modulo_certificados() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text("""
                CREATE SEQUENCE IF NOT EXISTS certificado_codigo_seq
                    START WITH 1 INCREMENT BY 1;
            """))
            await session.execute(text("""
                SELECT pg_advisory_xact_lock(76139521, 9);
            """))
            await session.execute(text("""
                DO $$
                DECLARE
                    sequence_called BOOLEAN;
                    next_code BIGINT;
                BEGIN
                    SELECT is_called INTO sequence_called FROM certificado_codigo_seq;
                    IF NOT sequence_called THEN
                        SELECT GREATEST(
                            COALESCE(MAX((substring(codigo_verificacion FROM '-([0-9]+)$'))::BIGINT), 0) + 1,
                            1
                        ) INTO next_code
                        FROM certificado
                        WHERE codigo_verificacion ~ '^CS-[0-9]{4}-[0-9]+$';
                        PERFORM setval('certificado_codigo_seq', next_code, FALSE);
                    END IF;
                END $$;
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_certificado_codigo_verificacion
                    ON certificado (codigo_verificacion);
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_certificado_publico_estado
                    ON certificado (publico_certificado, estado_certificado);
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS historial_certificado (
                    id_historial UUID PRIMARY KEY,
                    id_certificado UUID NOT NULL
                        REFERENCES certificado (id_certificado) ON DELETE RESTRICT,
                    estado_anterior VARCHAR(50),
                    estado_nuevo VARCHAR(50) NOT NULL,
                    motivo TEXT NOT NULL,
                    id_usuario UUID,
                    fecha TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """))
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS asignacion_lider_comite (
                    id_asignacion UUID PRIMARY KEY,
                    id_usuario UUID NOT NULL REFERENCES usuario (id_usuario),
                    asignado_por UUID REFERENCES usuario (id_usuario),
                    fecha_inicio TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    fecha_fin TIMESTAMP WITHOUT TIME ZONE
                );
            """))
            await session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_asignacion_lider_comite_activa
                    ON asignacion_lider_comite ((TRUE))
                    WHERE fecha_fin IS NULL;
            """))
            await session.execute(text("""
                ALTER TABLE certificado
                ADD COLUMN IF NOT EXISTS id_asignacion_lider UUID
                    REFERENCES asignacion_lider_comite (id_asignacion);
            """))
            await session.execute(text("""
                ALTER TABLE certificado
                ADD COLUMN IF NOT EXISTS id_firmante UUID
                    REFERENCES usuario (id_usuario);
            """))
            await session.execute(text("""
                ALTER TABLE certificado
                ADD COLUMN IF NOT EXISTS huella_firmante VARCHAR(128);
            """))
            await session.execute(text("""
                ALTER TABLE certificado
                ADD COLUMN IF NOT EXISTS huella_pdf VARCHAR(64);
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_certificado_asignacion_lider
                    ON certificado (id_asignacion_lider, estado_certificado);
            """))
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_historial_certificado_fecha
                    ON historial_certificado (id_certificado, fecha DESC);
            """))
            await session.commit()
            logger.info("Modulo M9 (certificados) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo M9: %s", exc)