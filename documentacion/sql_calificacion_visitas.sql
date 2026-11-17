-- =====================================================================
-- CertiSENA — Calificación de visitas por los auditores
--
-- Cada auditor asignado a una visita (programacion_visita) la califica
-- de 1 a 100 % y deja comentarios. El Comité ve esas calificaciones en el
-- expediente antes de aprobar o rechazar el certificado.
--
-- Una fila por (visita, auditor). Se puede editar mientras el Comité no
-- haya decidido el expediente (eso lo controla la aplicación).
--
-- Mientras este SQL no se ejecute, los endpoints /calificacion-visitas
-- responden 503 "Falta aplicar el SQL de calificación de visitas".
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS calificacion_visita (
    id_calificacion          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_programacion          UUID NOT NULL
        REFERENCES programacion_visita (id_programacion) ON DELETE CASCADE,
    id_solicitud             UUID NOT NULL
        REFERENCES solicitud (id_solicitud) ON DELETE CASCADE,
    id_auditor               UUID NOT NULL
        REFERENCES usuario (id_usuario) ON DELETE RESTRICT,
    calificacion             SMALLINT NOT NULL
        CONSTRAINT ck_calificacion_visita_rango CHECK (calificacion BETWEEN 1 AND 100),
    comentario_visita        TEXT
        CONSTRAINT ck_calificacion_visita_comentario_largo CHECK (char_length(comentario_visita) <= 2000),
    situaciones_encontradas  TEXT
        CONSTRAINT ck_calificacion_visita_situaciones_largo CHECK (char_length(situaciones_encontradas) <= 2000),
    oportunidades_mejora     TEXT
        CONSTRAINT ck_calificacion_visita_mejora_largo CHECK (char_length(oportunidades_mejora) <= 2000),
    fecha_registro           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion      TIMESTAMP WITH TIME ZONE,
    -- Al menos uno de los tres comentarios debe venir diligenciado.
    CONSTRAINT ck_calificacion_visita_algun_comentario CHECK (
        COALESCE(NULLIF(BTRIM(comentario_visita), ''),
                 NULLIF(BTRIM(situaciones_encontradas), ''),
                 NULLIF(BTRIM(oportunidades_mejora), '')) IS NOT NULL
    ),
    -- Una sola calificación por auditor y visita (se edita, no se repite).
    CONSTRAINT uq_calificacion_visita_programacion_auditor UNIQUE (id_programacion, id_auditor)
);

-- El Comité consulta por expediente (solicitud).
CREATE INDEX IF NOT EXISTS idx_calificacion_visita_solicitud
    ON calificacion_visita (id_solicitud);

-- El auditor consulta sus propias calificaciones.
CREATE INDEX IF NOT EXISTS idx_calificacion_visita_auditor
    ON calificacion_visita (id_auditor);

COMMENT ON TABLE calificacion_visita IS
    'Calificación (1-100 %) y comentarios de cada auditor sobre una visita programada; la consulta el Comité.';

COMMIT;
