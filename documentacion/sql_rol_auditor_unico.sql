-- =====================================================================
-- CertiSENA — Rol único "Auditor" (17/11/2026)
--
-- Decisión: se quitan los roles diferenciados (Auditor líder, Experto
-- técnico, Auditor integral, Observador) y todo integrante es "Auditor".
--
-- La tabla detalle_programacion_auditor tiene hoy el CHECK
--   chk_rol_auditor: rol_auditor IN ('Auditor Líder', 'Auditor Técnico', 'Observador')
-- que NO admite 'Auditor'. Mientras este SQL no se aplique, la Agenda
-- guarda 'Auditor Técnico' (valor permitido que la aplicación nunca
-- muestra: todo se lee como "Auditor").
--
-- Este script amplía el CHECK para admitir 'Auditor' SIN tocar los datos
-- existentes (los valores viejos siguen siendo válidos).
--
-- DESPUÉS de aplicarlo, cambia en
--   modules/asignacion_auditores/rol_auditor.py
--     ROL_DETALLE_BD = "Auditor Técnico"   →   ROL_DETALLE_BD = ROL_AUDITOR
-- y reinicia el servidor.
--
-- auditores_solicitud.especialidad no tiene CHECK: ya se guarda 'Auditor'.
-- =====================================================================

BEGIN;

ALTER TABLE detalle_programacion_auditor
    DROP CONSTRAINT IF EXISTS chk_rol_auditor;

ALTER TABLE detalle_programacion_auditor
    ADD CONSTRAINT chk_rol_auditor CHECK (
        rol_auditor IN ('Auditor', 'Auditor Líder', 'Auditor Técnico', 'Observador')
    );

COMMIT;

-- Comprobación:
-- SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'chk_rol_auditor';
