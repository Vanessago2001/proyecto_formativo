-- =====================================================================
-- ARCHIVOS COMPARTIDOS ENTRE LOS COMPUTADORES DEL EQUIPO
-- =====================================================================
-- Los archivos subidos (uploads/ y storage/) se guardan también en la base,
-- para que un documento subido desde un computador se pueda ver desde los
-- demás. Lo usa core/almacen_archivos.py.
--
-- * Se aplica UNA sola vez (lo hace una persona del equipo).
-- * No modifica ninguna tabla existente: las tablas siguen guardando la
--   misma ruta de siempre ('/uploads/...', 'storage/...'); esta tabla
--   guarda el contenido bajo esa ruta normalizada (sin '/' inicial y con '/').
-- * Si no se aplica, el sistema sigue funcionando como antes (solo disco).
-- * Después: cada integrante ejecuta una vez
--     venv\Scripts\python.exe -m modules.scripts.subir_archivos_locales
--   y reinicia su servidor.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS archivo_almacenado (
    -- Ruta relativa normalizada: 'uploads/auditores/x.pdf',
    -- 'storage/apelaciones/<id>/y.png', 'storage/certificados_firmados/<id>.pdf'.
    ruta            TEXT        PRIMARY KEY
                    CHECK (ruta ~ '^(uploads|storage)/' AND ruta !~ '(^|/)\.\.(/|$)' AND ruta !~ '\\'),
    nombre_original TEXT,
    content_type    TEXT,
    -- 25 MB: el mayor límite de subida del sistema (evidencias de auditoría).
    -- Debe coincidir con LIMITE_BYTES de core/almacen_archivos.py.
    tamano_bytes    INTEGER     NOT NULL CHECK (tamano_bytes > 0 AND tamano_bytes <= 26214400),
    sha256          CHAR(64)    NOT NULL,
    contenido       BYTEA       NOT NULL,
    subido_por      UUID        NULL REFERENCES usuario (id_usuario) ON DELETE SET NULL,
    fecha_subida    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (octet_length(contenido) = tamano_bytes)
);

-- PDF, imágenes y DOCX ya vienen comprimidos: EXTERNAL los guarda fuera de la
-- fila (TOAST) sin intentar recomprimirlos.
ALTER TABLE archivo_almacenado ALTER COLUMN contenido SET STORAGE EXTERNAL;

-- No hacen falta más índices: todas las consultas buscan por la clave primaria
-- (ruta). El script de migración lee (ruta, sha256) de toda la tabla una vez.

COMMENT ON TABLE archivo_almacenado IS
    'Contenido de los archivos subidos, compartido entre los servidores del equipo (core/almacen_archivos.py).';

COMMIT;

-- Comprobación (solo lectura):
--   SELECT count(*), pg_size_pretty(sum(tamano_bytes)) FROM archivo_almacenado;
--   SELECT pg_size_pretty(pg_total_relation_size('archivo_almacenado'));
