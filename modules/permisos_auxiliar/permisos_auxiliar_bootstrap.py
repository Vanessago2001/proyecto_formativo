"""
Permisos delegados al Auxiliar · preparación de la base al arrancar.

Crea dos tablas nuevas (idempotente, no toca ninguna tabla existente):

  · permiso_auxiliar      qué códigos otorgó el Administrador a cada auxiliar,
                          con vencimiento opcional y revocación con motivo.
  · permiso_auxiliar_uso  cada vez que un auxiliar ejecutó directamente una
                          acción REQ gracias a un permiso delegado.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger


async def ensure_permisos_auxiliar_schema(session) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS permiso_auxiliar (
            id_permiso BIGSERIAL PRIMARY KEY,
            id_usuario UUID NOT NULL REFERENCES usuario(id_usuario),
            codigo_permiso VARCHAR(30) NOT NULL,
            otorgado_por UUID NOT NULL REFERENCES usuario(id_usuario),
            fecha_otorgado TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_vencimiento DATE,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            motivo TEXT NOT NULL,
            revocado_por UUID REFERENCES usuario(id_usuario),
            fecha_revocado TIMESTAMP,
            motivo_revocacion TEXT
        );
    """))
    await session.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_permiso_auxiliar_activo
            ON permiso_auxiliar (id_usuario, codigo_permiso)
            WHERE activo;
    """))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS permiso_auxiliar_uso (
            id_uso BIGSERIAL PRIMARY KEY,
            id_permiso BIGINT REFERENCES permiso_auxiliar(id_permiso),
            id_usuario UUID NOT NULL REFERENCES usuario(id_usuario),
            codigo_permiso VARCHAR(30) NOT NULL,
            detalle TEXT,
            id_aprobacion UUID,
            fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_permiso_auxiliar_uso_usuario
            ON permiso_auxiliar_uso (id_usuario, fecha DESC);
    """))


async def preparar_permisos_auxiliar() -> None:
    """Punto de entrada al arrancar, con su propia sesión."""
    async with AsyncSessionLocal() as session:
        try:
            await ensure_permisos_auxiliar_schema(session)
            await session.commit()
            logger.info("Tablas de permisos delegados al auxiliar preparadas correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar los permisos delegados al auxiliar: %s", exc)
