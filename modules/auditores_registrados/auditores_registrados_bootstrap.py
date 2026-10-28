"""Preparacion del modulo administrativo de auditores registrados.

Agrega las columnas minimas necesarias para conservar la trazabilidad exacta
de los retiros de asignacion: la asignacion afectada y la programacion/visita
de la que se retiro el auditor.

El script es idempotente y no borra datos.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def preparar_modulo_auditores_registrados() -> None:
    """Crea/actualiza el esquema minimo del historial de asignaciones."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    ALTER TABLE historial_asignacion_auditor
                        ADD COLUMN IF NOT EXISTS id_asignacion UUID;
                    """
                )
            )
            await session.execute(
                text(
                    """
                    ALTER TABLE historial_asignacion_auditor
                        ADD COLUMN IF NOT EXISTS id_programacion UUID;
                    """
                )
            )

            await session.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'fk_hist_asig_asignacion'
                        ) THEN
                            ALTER TABLE historial_asignacion_auditor
                                ADD CONSTRAINT fk_hist_asig_asignacion
                                FOREIGN KEY (id_asignacion)
                                REFERENCES auditores_solicitud(id)
                                ON DELETE SET NULL;
                        END IF;
                    END
                    $$;
                    """
                )
            )
            await session.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'fk_hist_asig_programacion'
                        ) THEN
                            ALTER TABLE historial_asignacion_auditor
                                ADD CONSTRAINT fk_hist_asig_programacion
                                FOREIGN KEY (id_programacion)
                                REFERENCES programacion_visita(id_programacion)
                                ON DELETE SET NULL;
                        END IF;
                    END
                    $$;
                    """
                )
            )

            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hist_asig_auditor_fecha
                        ON historial_asignacion_auditor (id_auditor, fecha DESC);
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hist_asig_solicitud_auditor
                        ON historial_asignacion_auditor (id_solicitud, id_auditor);
                    """
                )
            )

            await session.commit()
            logger.info("Modulo de auditores registrados preparado correctamente.")
    except Exception as exc:  # pragma: no cover - arranque tolerante
        logger.error(
            "No fue posible preparar el modulo de auditores registrados: %s",
            exc,
        )
