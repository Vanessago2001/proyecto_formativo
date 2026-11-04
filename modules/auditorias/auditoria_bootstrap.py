"""
M7 — AUDITORÍAS
Preparación de la base de datos al arrancar la aplicación.

Las tablas del módulo (`auditoria`, `evaluacion_requisito`, `hallazgo`,
`evidencia`, `informe_auditoria`, `jornada_auditoria`,
`seguimiento_auditoria`) YA EXISTEN en la base del proyecto: aquí no se crea
ninguna. Solo se ajusta lo que impedía registrar el flujo real:

  · `auditoria.fecha_fin` era obligatoria, pero una auditoría que empieza
    todavía no tiene fecha de cierre;
  · `jornada_auditoria.hora_fin` igual: la jornada se abre por la mañana y se
    cierra al terminar el día;
  · `seguimiento_auditoria.id_hallazgo` era obligatoria, y AUT-053 admite
    acciones de seguimiento generales, no atadas a un hallazgo concreto.

Son tres restricciones que se relajan, nunca datos que se borren, y las
sentencias son idempotentes.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def ensure_auditorias_schema(session) -> None:
    for sentencia in (
        "ALTER TABLE auditoria ALTER COLUMN fecha_fin DROP NOT NULL;",
        "ALTER TABLE jornada_auditoria ALTER COLUMN hora_fin DROP NOT NULL;",
        "ALTER TABLE seguimiento_auditoria ALTER COLUMN id_hallazgo DROP NOT NULL;",
    ):
        await session.execute(text(sentencia))

    # Índices de las consultas que más se repiten en las pantallas de campo.
    for indice in (
        "CREATE INDEX IF NOT EXISTS idx_auditoria_solicitud ON auditoria (id_solicitud);",
        "CREATE INDEX IF NOT EXISTS idx_evaluacion_auditoria ON evaluacion_requisito (id_auditoria);",
        "CREATE INDEX IF NOT EXISTS idx_hallazgo_auditoria ON hallazgo (id_auditoria);",
        "CREATE INDEX IF NOT EXISTS idx_evidencia_auditoria ON evidencia (id_auditoria);",
        "CREATE INDEX IF NOT EXISTS idx_jornada_auditoria ON jornada_auditoria (id_auditoria);",
        "CREATE INDEX IF NOT EXISTS idx_informe_auditoria ON informe_auditoria (id_auditoria, version);",
    ):
        await session.execute(text(indice))

    # Una evaluación por requisito y auditoría: el autoguardado de AUT-012
    # actualiza la fila, no crea otra.
    await session.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_evaluacion_auditoria_variable
            ON evaluacion_requisito (id_auditoria, id_variable);
    """))


async def preparar_modulo_auditorias() -> None:
    """Punto de entrada del módulo al arrancar, con su propia sesión."""
    async with AsyncSessionLocal() as session:
        try:
            await ensure_auditorias_schema(session)
            await session.commit()
            logger.info("Modulo M7 (auditorias) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo M7: %s", exc)
