"""
Preparación idempotente de las tablas del módulo PQRS.

En la base ya existen unas tablas `pqrs`, `pqrs_asignacion`, `pqrs_evidencia`,
`pqrs_historial_estado` y `pqrs_mensaje` heredadas del diseño original (vacías).
No se usan ni se tocan: sus restricciones CHECK no admiten el flujo acordado
(Radicada, Asignada, Información solicitada, Reabierta...) y les faltan datos
obligatorios del peticionario (documento, aceptación de tratamiento de datos,
respuesta). Cambiarlas exigiría ALTER sobre tablas existentes; por eso el
módulo trabaja con tablas propias `pqrs_caso*`. Si el equipo decide retirar
las heredadas, se hace aparte y de forma manual.

Todo aquí es CREATE ... IF NOT EXISTS o un INSERT ... ON CONFLICT DO NOTHING:
nunca borra ni altera datos.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger
from modules.pqrs.pqrs_reglas import (
    DIAS_ALERTA_POR_DEFECTO,
    PLAZO_DIAS_HABILES_POR_DEFECTO,
    TIPOS,
)

SENTENCIAS = (
    """
    CREATE SEQUENCE IF NOT EXISTS pqrs_caso_radicado_seq START WITH 1 INCREMENT BY 1;
    """,
    """
    CREATE TABLE IF NOT EXISTS pqrs_plazo_tipo (
        tipo VARCHAR(20) PRIMARY KEY,
        dias_habiles INTEGER NOT NULL DEFAULT 15 CHECK (dias_habiles BETWEEN 1 AND 90),
        dias_alerta INTEGER NOT NULL DEFAULT 3 CHECK (dias_alerta BETWEEN 0 AND 30),
        actualizado_por UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        fecha_actualizacion TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pqrs_caso (
        id_pqrs UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        radicado VARCHAR(30) NOT NULL,
        tipo VARCHAR(20) NOT NULL,
        estado VARCHAR(30) NOT NULL DEFAULT 'Radicada',
        canal VARCHAR(30) NOT NULL DEFAULT 'Web',
        asunto VARCHAR(200) NOT NULL,
        descripcion TEXT NOT NULL,
        nombre_peticionario VARCHAR(150) NOT NULL,
        tipo_documento VARCHAR(30) NOT NULL,
        numero_documento VARCHAR(30) NOT NULL,
        correo VARCHAR(150) NOT NULL,
        telefono VARCHAR(30),
        empresa_nombre VARCHAR(200),
        nit VARCHAR(30),
        id_empresa UUID REFERENCES empresa (id_empresa) ON DELETE SET NULL,
        id_auditoria UUID REFERENCES auditoria (id_auditoria) ON DELETE SET NULL,
        acepta_tratamiento_datos BOOLEAN NOT NULL,
        id_usuario_peticionario UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        id_usuario_radica UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        id_responsable UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        plazo_dias_habiles INTEGER NOT NULL DEFAULT 15,
        fecha_radicacion TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        fecha_limite DATE NOT NULL,
        respuesta TEXT,
        fecha_respuesta TIMESTAMP WITH TIME ZONE,
        fecha_cierre TIMESTAMP WITH TIME ZONE,
        veces_reabierta INTEGER NOT NULL DEFAULT 0,
        fecha_actualizacion TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_pqrs_caso_radicado UNIQUE (radicado),
        CONSTRAINT chk_pqrs_caso_tipo CHECK (tipo IN
            ('Petición', 'Queja', 'Reclamo', 'Sugerencia', 'Felicitación')),
        CONSTRAINT chk_pqrs_caso_estado CHECK (estado IN
            ('Radicada', 'Asignada', 'En trámite', 'Información solicitada',
             'Respondida', 'Cerrada', 'Reabierta')),
        CONSTRAINT chk_pqrs_caso_datos CHECK (acepta_tratamiento_datos)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_estado ON pqrs_caso (estado, fecha_limite);",
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_responsable ON pqrs_caso (id_responsable);",
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_peticionario ON pqrs_caso (id_usuario_peticionario);",
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_empresa ON pqrs_caso (id_empresa);",
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_auditoria ON pqrs_caso (id_auditoria);",
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_fecha ON pqrs_caso (fecha_radicacion DESC);",
    """
    CREATE TABLE IF NOT EXISTS pqrs_caso_historial (
        id_historial UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        id_pqrs UUID NOT NULL REFERENCES pqrs_caso (id_pqrs) ON DELETE CASCADE,
        accion VARCHAR(40) NOT NULL,
        estado_anterior VARCHAR(30),
        estado_nuevo VARCHAR(30),
        comentario TEXT,
        id_usuario UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        actor VARCHAR(150) NOT NULL,
        visible_peticionario BOOLEAN NOT NULL DEFAULT TRUE,
        es_peticionario BOOLEAN NOT NULL DEFAULT FALSE,
        fecha TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_historial ON pqrs_caso_historial (id_pqrs, fecha);",
    """
    CREATE TABLE IF NOT EXISTS pqrs_caso_adjunto (
        id_adjunto UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        id_pqrs UUID NOT NULL REFERENCES pqrs_caso (id_pqrs) ON DELETE CASCADE,
        nombre_archivo VARCHAR(255) NOT NULL,
        ruta_archivo TEXT NOT NULL,
        tipo_mime VARCHAR(120) NOT NULL,
        tamano_bytes INTEGER NOT NULL,
        hash_sha256 VARCHAR(64) NOT NULL,
        origen VARCHAR(20) NOT NULL DEFAULT 'peticionario'
            CHECK (origen IN ('peticionario', 'gestion')),
        id_usuario UUID REFERENCES usuario (id_usuario) ON DELETE SET NULL,
        fecha_subida TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pqrs_caso_adjunto ON pqrs_caso_adjunto (id_pqrs);",
)


async def preparar_modulo_pqrs() -> None:
    async with AsyncSessionLocal() as session:
        try:
            for sentencia in SENTENCIAS:
                await session.execute(text(sentencia))
            for tipo in TIPOS:
                await session.execute(
                    text("""
                        INSERT INTO pqrs_plazo_tipo (tipo, dias_habiles, dias_alerta)
                        VALUES (:tipo, :dias, :alerta)
                        ON CONFLICT (tipo) DO NOTHING;
                    """),
                    {"tipo": tipo, "dias": PLAZO_DIAS_HABILES_POR_DEFECTO, "alerta": DIAS_ALERTA_POR_DEFECTO},
                )
            await session.commit()
            logger.info("Modulo PQRS preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo PQRS: %s", exc)
