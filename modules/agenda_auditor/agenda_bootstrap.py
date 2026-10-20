"""Preparación del módulo de agenda de auditores.

La confirmación de una programación es **individual**: cada auditor confirma
su propia participación. Para poder registrarla se agregan a
`detalle_programacion_auditor` las columnas `confirmado` y
`fecha_confirmacion`.

El script es idempotente (ADD COLUMN IF NOT EXISTS) y se ejecuta en cada
arranque de la aplicación, igual que el resto de módulos del proyecto.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def preparar_modulo_agenda() -> None:
    """Crea/actualiza el esquema mínimo del módulo de agenda."""
    try:
        async with AsyncSessionLocal() as session:
            for column_sql in [
                "ALTER TABLE detalle_programacion_auditor ADD COLUMN IF NOT EXISTS confirmado BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE detalle_programacion_auditor ADD COLUMN IF NOT EXISTS fecha_confirmacion TIMESTAMP;",
                # Seguimiento de la solicitud formal de reprogramacion.
                "ALTER TABLE programacion_visita ADD COLUMN IF NOT EXISTS estado_solicitud_reprogramacion VARCHAR(30);",
                "ALTER TABLE programacion_visita ADD COLUMN IF NOT EXISTS id_usuario_solicitante_reprogramacion UUID;",
                "ALTER TABLE programacion_visita ADD COLUMN IF NOT EXISTS motivo_solicitud_reprogramacion TEXT;",
            ]:
                await session.execute(text(column_sql))
            await session.commit()
            logger.info("Módulo de agenda (confirmación individual) preparado correctamente.")
    except Exception as exc:  # pragma: no cover - arranque tolerante
        logger.error("No fue posible preparar el módulo de agenda: %s", exc)
