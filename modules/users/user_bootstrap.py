"""
Usuarios · historial de gestion de cuentas.

Guarda quien cambio el correo o restablecio la contrasena de una cuenta
(Empresa o Auditor), a quien, cuando, que cambio y el motivo. Nunca se guarda
la contrasena ni el enlace de restablecimiento.

Las sentencias son idempotentes y no tocan datos existentes.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger

SQL_TABLA_HISTORIAL = """
    CREATE TABLE IF NOT EXISTS historial_gestion_cuenta (
        id_historial UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        id_usuario_objetivo UUID NOT NULL,
        id_usuario_actor UUID,
        rol_actor VARCHAR(80),
        accion VARCHAR(40) NOT NULL,
        valor_anterior VARCHAR(150),
        valor_nuevo VARCHAR(150),
        motivo TEXT NOT NULL,
        resultado_envio TEXT,
        fecha TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

SQL_INDICE_HISTORIAL = """
    CREATE INDEX IF NOT EXISTS idx_historial_gestion_cuenta_objetivo
        ON historial_gestion_cuenta (id_usuario_objetivo);
"""


async def ensure_users_schema(session) -> None:
    await session.execute(text(SQL_TABLA_HISTORIAL))
    await session.execute(text(SQL_INDICE_HISTORIAL))


async def preparar_modulo_usuarios() -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_users_schema(session)
            await session.commit()
            logger.info("Modulo de usuarios (historial de gestion) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo de usuarios: %s", exc)
