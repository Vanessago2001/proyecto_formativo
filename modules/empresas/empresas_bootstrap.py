"""
M3 — EMPRESAS
Preparación de la base de datos al arrancar la aplicación.

Añade lo que necesitan el estado de la empresa (EMP-006 a EMP-008), los
contactos de sede (EMP-027 a EMP-029) y los documentos de soporte
(EMP-011 a EMP-020). Todas las sentencias son idempotentes
y no modifican datos existentes: las empresas que ya estaban quedan 'Activa'.
"""

from sqlalchemy import text

from core.database import AsyncSessionLocal
from core.logger import logger

ESTADOS_EMPRESA = ("Activa", "Suspendida", "Inactiva")


async def ensure_empresas_schema(session) -> None:
    # EMP-006 / EMP-007 / EMP-008: estado de la empresa.
    await session.execute(text("""
        ALTER TABLE empresa
        ADD COLUMN IF NOT EXISTS estado VARCHAR(20) NOT NULL DEFAULT 'Activa';
    """))
    await session.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_estado_empresa'
            ) THEN
                ALTER TABLE empresa
                ADD CONSTRAINT chk_estado_empresa
                CHECK (estado IN ('Activa', 'Suspendida', 'Inactiva'));
            END IF;
        END $$;
    """))

    # EMP-027 / EMP-028 / EMP-029: personas de contacto de cada sede.
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS contacto_sede (
            id_contacto UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_sede UUID NOT NULL REFERENCES sede_empresa(id_sede) ON DELETE CASCADE,
            nombre VARCHAR(150) NOT NULL,
            cargo VARCHAR(100),
            telefono VARCHAR(30),
            correo VARCHAR(150),
            fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_contacto_sede_sede
            ON contacto_sede (id_sede);
    """))

    # EMP-011 a EMP-020: documentos de soporte de la empresa.
    # `documento_empresa` ya existía para guardar el dato del documento
    # (tipo y número). Para subirlo, revisarlo y versionarlo hacen falta
    # estas columnas; todas se añaden sin tocar lo que ya hay.
    for columna in (
        "ADD COLUMN IF NOT EXISTS nombre_archivo VARCHAR(255)",
        "ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
        "ADD COLUMN IF NOT EXISTS usuario_subida UUID",
        "ADD COLUMN IF NOT EXISTS usuario_revision UUID",
        "ADD COLUMN IF NOT EXISTS fecha_revision TIMESTAMP",
    ):
        await session.execute(text(f"ALTER TABLE documento_empresa {columna};"))

    # EMP-019 pide corregir un documento: es un estado más, y la restricción
    # original no lo admitía. Añadirlo no invalida ninguna fila existente.
    await session.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_estado_doc_validacion'
            ) THEN
                ALTER TABLE documento_empresa DROP CONSTRAINT chk_estado_doc_validacion;
            END IF;
            ALTER TABLE documento_empresa
            ADD CONSTRAINT chk_estado_doc_validacion
            CHECK (estado_validacion IN ('Pendiente', 'Aprobado', 'Rechazado', 'Correccion', 'Vencido'));
        END $$;
    """))

    # EMP-020: cada versión reemplazada se conserva, no se pisa.
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS historial_documento_empresa (
            id_historial UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            id_documento UUID NOT NULL,
            id_empresa UUID NOT NULL REFERENCES empresa(id_empresa) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            tipo_documento VARCHAR(100),
            nombre_archivo VARCHAR(255),
            url_archivo TEXT,
            estado_validacion VARCHAR(20),
            observaciones TEXT,
            usuario_subida UUID,
            fecha_subida TIMESTAMP,
            fecha_reemplazo TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_hist_doc_empresa_documento
            ON historial_documento_empresa (id_documento);
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_documento_empresa_empresa
            ON documento_empresa (id_empresa);
    """))


async def preparar_modulo_empresas() -> None:
    """
    Punto de entrada del módulo al arrancar. Abre su propia sesión para que
    un fallo aquí no deshaga la siembra inicial ni la preparación de otros
    módulos.
    """
    async with AsyncSessionLocal() as session:
        try:
            await ensure_empresas_schema(session)
            await session.commit()
            logger.info("Modulo M3 (empresas) preparado correctamente.")
        except Exception as exc:
            await session.rollback()
            logger.exception("Error al preparar el modulo M3: %s", exc)
