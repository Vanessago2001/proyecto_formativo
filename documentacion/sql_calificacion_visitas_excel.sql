-- =====================================================================
-- OPCIONAL (NO APLICADO) — Ruta del Excel de la evaluación de la visita
-- =====================================================================
-- Hoy el Excel que el auditor adjunta al finalizar la visita se guarda en
-- una ruta DERIVADA de la visita y del auditor (no hace falta este SQL):
--
--   storage/calificaciones_visita/<id_programacion>/<id_auditor>.xlsx|.xls
--   storage/calificaciones_visita/<id_programacion>/<id_auditor>.json  (metadatos)
--
-- (modules/calificacion_visitas/evaluacion_excel.py, con core/almacen_archivos.py).
-- Si se prefiere tener la ruta, el nombre y el hash en la propia fila de la
-- calificación, este es el cambio mínimo. Después de aplicarlo habría que
-- ajustar evaluacion_excel.py para escribir/leer estas columnas.

ALTER TABLE calificacion_visita
    ADD COLUMN IF NOT EXISTS excel_ruta    TEXT,
    ADD COLUMN IF NOT EXISTS excel_nombre  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS excel_sha256  CHAR(64);
