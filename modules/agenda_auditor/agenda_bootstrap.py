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
                # Vincula los bloqueos de fecha con la programacion que los origino,
                # para poder liberarlos al cancelar esa programacion.
                "ALTER TABLE disponibilidad_auditor ADD COLUMN IF NOT EXISTS id_programacion UUID;",
            ]:
                await session.execute(text(column_sql))
            # Enlaza los bloqueos de fecha que ya existian con la programacion
            # vigente que los origino, para que al cancelarla se liberen.
            await session.execute(text("""
                UPDATE disponibilidad_auditor da
                SET id_programacion = p.id_programacion
                FROM programacion_visita p
                JOIN detalle_programacion_auditor d
                    ON d.id_programacion = p.id_programacion
                WHERE da.id_programacion IS NULL
                  AND da.tipo_registro = 'Bloqueo Fecha'
                  AND d.id_usuario = da.id_usuario
                  AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                  AND CAST(p.fecha_inicio AS DATE) <= CAST(da.fecha_inicio AS DATE)
                  AND CAST(COALESCE(p.fecha_fin, p.fecha_inicio) AS DATE) >= CAST(da.fecha_inicio AS DATE)
            """))
            await session.commit()
            logger.info("Módulo de agenda (confirmación individual) preparado correctamente.")
    except Exception as exc:  # pragma: no cover - arranque tolerante
        logger.error("No fue posible preparar el módulo de agenda: %s", exc)
