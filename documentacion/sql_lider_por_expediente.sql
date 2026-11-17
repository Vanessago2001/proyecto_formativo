-- =====================================================================
-- CertiSENA — Líder del Comité por expediente (17/11/2026)
--
-- Decisión: el Coordinador elige el líder del comité de CADA expediente,
-- entre los miembros del Comité que participaron en su evaluación. Ese
-- líder firma el acta y el certificado de ese expediente.
--
-- Hoy asignacion_lider_comite admite UNA sola asignación vigente para todo
-- el sistema (índice único uq_asignacion_lider_comite_activa sobre (TRUE)
-- WHERE fecha_fin IS NULL). Este script:
--   1. agrega la columna id_solicitud (NULL = líder global de antes);
--   2. deja el índice único del líder global solo para id_solicitud NULL;
--   3. crea un índice único: un líder vigente por expediente.
-- No modifica datos: la asignación global vigente sigue igual y los
-- certificados ya emitidos conservan su id_asignacion_lider.
--
-- Mientras no se aplique, la aplicación sigue con el líder global y le
-- muestra al Coordinador "Falta aplicar el SQL de líder por expediente".
-- No hay que cambiar código después de aplicarlo: el modo se detecta solo.
-- =====================================================================

BEGIN;

ALTER TABLE asignacion_lider_comite
    ADD COLUMN IF NOT EXISTS id_solicitud UUID NULL
        REFERENCES solicitud (id_solicitud);

DROP INDEX IF EXISTS uq_asignacion_lider_comite_activa;

-- Mismo nombre que el índice que crea certificados_bootstrap.py, para que
-- el arranque (CREATE UNIQUE INDEX IF NOT EXISTS) no lo vuelva a crear.
CREATE UNIQUE INDEX uq_asignacion_lider_comite_activa
    ON asignacion_lider_comite ((TRUE))
    WHERE fecha_fin IS NULL AND id_solicitud IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_asignacion_lider_comite_expediente_activa
    ON asignacion_lider_comite (id_solicitud)
    WHERE fecha_fin IS NULL AND id_solicitud IS NOT NULL;

COMMIT;

-- Comprobación:
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name = 'asignacion_lider_comite' AND column_name = 'id_solicitud';
-- SELECT pg_get_indexdef(indexrelid) FROM pg_index
--  WHERE indrelid = 'asignacion_lider_comite'::regclass;
