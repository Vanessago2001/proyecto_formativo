"""
M3 — EMPRESAS
Documentos de soporte de la empresa (EMP-011 a EMP-020).

Sigue el mismo camino que los documentos de solicitud de M5, para que la
empresa encuentre el mismo comportamiento en las dos pantallas:

    Pendiente  -> la empresa lo subió, falta revisarlo
    Aprobado   -> la administración lo dio por válido   (EMP-018)
    Rechazado  -> la administración lo rechazó          (EMP-017)
    Correccion -> hay que corregirlo y volver a subirlo (EMP-019)

Los archivos se guardan en `storage/empresas/<id_empresa>/` y en
`url_archivo` queda la ruta relativa. Al reemplazar (EMP-012) la versión
anterior no se pisa: pasa a `historial_documento_empresa` (EMP-020).
"""


import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ============================================================
# VALIDACIÓN AUTOMÁTICA DE FORMATO (EMP-016)
# ============================================================

EXTENSIONES_PERMITIDAS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10 MB

# Los admite la restricción `chk_tipo_documento` de la tabla.
TIPOS_DOCUMENTO = (
    "RUT",
    "RUNT",
    "Cámara de Comercio",
    "Representación Legal",
    "Certificación",
    "Otro",
)

ESTADO_PENDIENTE = "Pendiente"
ESTADO_APROBADO = "Aprobado"
ESTADO_RECHAZADO = "Rechazado"
ESTADO_CORRECCION = "Correccion"

# Estados en los que la empresa todavía puede reemplazar el archivo.
ESTADOS_MODIFICABLES = {ESTADO_PENDIENTE, ESTADO_RECHAZADO, ESTADO_CORRECCION}

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_ARCHIVOS = RAIZ_PROYECTO / "storage" / "empresas"

COLUMNAS = """
    id_documento,
    id_empresa,
    tipo_documento,
    numero_documento,
    nombre_archivo,
    url_archivo,
    version,
    estado_validacion,
    observaciones,
    usuario_subida,
    usuario_revision,
    fecha_expedicion,
    fecha_vencimiento,
    fecha_subida,
    fecha_revision
"""


def _nombre_seguro(nombre: str) -> str:
    """Deja el nombre del archivo en algo inofensivo para el disco."""
    base = Path(nombre or "documento").name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    limpio = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base)
    return limpio.strip() or "documento"


class DocumentoEmpresaService:
    """Documentos de soporte que la empresa adjunta a su perfil."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================
    # AYUDANTES
    # ========================================================

    @staticmethod
    def validar_formato(archivo: UploadFile, tamano: int) -> None:
        """
        EMP-016, parte automática: se comprueba al subir y al reemplazar,
        así que no hay forma de saltársela.
        """
        extension = Path(archivo.filename or "").suffix.lower()

        if extension not in EXTENSIONES_PERMITIDAS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Formato '{extension or 'desconocido'}' no permitido. "
                    f"Se aceptan: {', '.join(sorted(EXTENSIONES_PERMITIDAS))}."
                ),
            )

        if tamano == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo está vacío.",
            )

        if tamano > TAMANO_MAXIMO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"El archivo supera el máximo de {TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB.",
            )

    @staticmethod
    def validar_tipo(tipo_documento: str) -> str:
        if tipo_documento not in TIPOS_DOCUMENTO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de documento no válido. Se aceptan: {', '.join(TIPOS_DOCUMENTO)}.",
            )
        return tipo_documento

    def _guardar_archivo(self, id_empresa: UUID, archivo: UploadFile, contenido: bytes) -> tuple[str, str]:
        """Escribe el archivo en disco y devuelve (nombre visible, ruta relativa)."""
        nombre_visible = _nombre_seguro(archivo.filename or "documento")
        carpeta = CARPETA_ARCHIVOS / str(id_empresa)
        carpeta.mkdir(parents=True, exist_ok=True)

        extension = Path(nombre_visible).suffix.lower()
        destino = carpeta / f"{uuid4().hex}{extension}"
        destino.write_bytes(contenido)

        # Se guarda la ruta relativa al proyecto para poder mover la carpeta
        # sin reescribir la base. Si el almacenamiento vive fuera del
        # proyecto, se guarda la ruta completa.
        try:
            relativa = destino.relative_to(RAIZ_PROYECTO).as_posix()
        except ValueError:
            relativa = destino.as_posix()
        return nombre_visible, relativa

    def ruta_absoluta(self, url_archivo: str) -> Path:
        ruta = Path(url_archivo or "")
        return ruta if ruta.is_absolute() else RAIZ_PROYECTO / ruta

    async def _obtener(self, id_empresa: UUID, id_documento: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS}
                FROM documento_empresa
                WHERE id_documento = :id_documento AND id_empresa = :id_empresa;
            """),
            {"id_documento": str(id_documento), "id_empresa": str(id_empresa)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El documento no existe para esta empresa.",
            )
        return dict(fila)

    # ========================================================
    # EMP-011 · SUBIR DOCUMENTO DE SOPORTE
    # ========================================================

    async def subir(
        self,
        id_empresa: UUID,
        archivo: UploadFile,
        tipo_documento: str,
        usuario: dict,
        numero_documento: str | None = None,
        fecha_expedicion=None,
        fecha_vencimiento=None,
    ) -> dict:
        self.validar_tipo(tipo_documento)
        contenido = await archivo.read()
        self.validar_formato(archivo, len(contenido))

        nombre_visible, ruta = self._guardar_archivo(id_empresa, archivo, contenido)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO documento_empresa (
                    id_empresa, tipo_documento, numero_documento, nombre_archivo,
                    url_archivo, version, estado_validacion, usuario_subida,
                    fecha_expedicion, fecha_vencimiento, fecha_subida
                )
                VALUES (
                    :id_empresa, :tipo_documento, :numero_documento, :nombre_archivo,
                    :url_archivo, 1, :estado, :usuario_subida,
                    :fecha_expedicion, :fecha_vencimiento, CURRENT_TIMESTAMP
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_empresa": str(id_empresa),
                "tipo_documento": tipo_documento,
                "numero_documento": numero_documento,
                "nombre_archivo": nombre_visible,
                "url_archivo": ruta,
                "estado": ESTADO_PENDIENTE,
                "usuario_subida": str(usuario.get("id_usuario")),
                "fecha_expedicion": fecha_expedicion,
                "fecha_vencimiento": fecha_vencimiento,
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # EMP-012 · REEMPLAZAR DOCUMENTO
    # ========================================================

    async def reemplazar(
        self,
        id_empresa: UUID,
        id_documento: UUID,
        archivo: UploadFile,
        usuario: dict,
    ) -> dict:
        documento = await self._obtener(id_empresa, id_documento)

        if documento["estado_validacion"] not in ESTADOS_MODIFICABLES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El documento está '{documento['estado_validacion']}' y ya no se "
                    "puede reemplazar."
                ),
            )

        contenido = await archivo.read()
        self.validar_formato(archivo, len(contenido))

        # La versión que se va se guarda antes de escribir la nueva (EMP-020).
        await self.db.execute(
            text("""
                INSERT INTO historial_documento_empresa (
                    id_documento, id_empresa, version, tipo_documento, nombre_archivo,
                    url_archivo, estado_validacion, observaciones, usuario_subida, fecha_subida
                )
                VALUES (
                    :id_documento, :id_empresa, :version, :tipo_documento, :nombre_archivo,
                    :url_archivo, :estado, :observaciones, :usuario_subida, :fecha_subida
                );
            """),
            {
                "id_documento": str(id_documento),
                "id_empresa": str(id_empresa),
                "version": documento["version"],
                "tipo_documento": documento["tipo_documento"],
                "nombre_archivo": documento["nombre_archivo"],
                "url_archivo": documento["url_archivo"],
                "estado": documento["estado_validacion"],
                "observaciones": documento["observaciones"],
                "usuario_subida": documento["usuario_subida"],
                "fecha_subida": documento["fecha_subida"],
            },
        )

        nombre_visible, ruta = self._guardar_archivo(id_empresa, archivo, contenido)

        resultado = await self.db.execute(
            text(f"""
                UPDATE documento_empresa
                SET nombre_archivo = :nombre_archivo,
                    url_archivo = :url_archivo,
                    version = version + 1,
                    estado_validacion = :estado,
                    observaciones = NULL,
                    usuario_subida = :usuario_subida,
                    usuario_revision = NULL,
                    fecha_subida = CURRENT_TIMESTAMP,
                    fecha_revision = NULL
                WHERE id_documento = :id_documento AND id_empresa = :id_empresa
                RETURNING {COLUMNAS};
            """),
            {
                "nombre_archivo": nombre_visible,
                "url_archivo": ruta,
                "estado": ESTADO_PENDIENTE,
                "usuario_subida": str(usuario.get("id_usuario")),
                "id_documento": str(id_documento),
                "id_empresa": str(id_empresa),
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # EMP-016 a EMP-019 · REVISIÓN DE LA ADMINISTRACIÓN
    # ========================================================

    async def revisar(
        self,
        id_empresa: UUID,
        id_documento: UUID,
        nuevo_estado: str,
        observaciones: str | None,
        usuario: dict,
    ) -> dict:
        """Aprobar (EMP-018), rechazar (EMP-017) o pedir corrección (EMP-019)."""
        await self._obtener(id_empresa, id_documento)

        resultado = await self.db.execute(
            text(f"""
                UPDATE documento_empresa
                SET estado_validacion = :estado,
                    observaciones = :observaciones,
                    usuario_revision = :usuario_revision,
                    fecha_revision = CURRENT_TIMESTAMP
                WHERE id_documento = :id_documento AND id_empresa = :id_empresa
                RETURNING {COLUMNAS};
            """),
            {
                "estado": nuevo_estado,
                "observaciones": observaciones,
                "usuario_revision": str(usuario.get("id_usuario")),
                "id_documento": str(id_documento),
                "id_empresa": str(id_empresa),
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def validar(self, id_empresa: UUID, id_documento: UUID) -> dict:
        """
        EMP-016, parte manual: dice si el archivo sigue siendo válido sin
        cambiarle el estado. Sirve para revisar antes de decidir.
        """
        documento = await self._obtener(id_empresa, id_documento)
        ruta = self.ruta_absoluta(documento["url_archivo"] or "")
        existe = bool(documento["url_archivo"]) and ruta.is_file()
        extension = Path(documento["nombre_archivo"] or "").suffix.lower()

        motivos = []
        if not existe:
            motivos.append("El archivo no está disponible en el servidor.")
        if extension and extension not in EXTENSIONES_PERMITIDAS:
            motivos.append(f"La extensión '{extension}' no está permitida.")
        if existe and ruta.stat().st_size > TAMANO_MAXIMO_BYTES:
            motivos.append("El archivo supera el tamaño máximo permitido.")

        return {
            "id_documento": documento["id_documento"],
            "nombre_archivo": documento["nombre_archivo"],
            "estado_validacion": documento["estado_validacion"],
            "formato_valido": not motivos,
            "motivos": motivos,
            "extensiones_permitidas": sorted(EXTENSIONES_PERMITIDAS),
            "tamano_maximo_mb": TAMANO_MAXIMO_BYTES // (1024 * 1024),
        }

    # ========================================================
    # EMP-020 · HISTORIAL DOCUMENTAL
    # ========================================================

    async def historial(self, id_empresa: UUID, id_documento: UUID | None = None) -> list[dict]:
        """
        Versiones reemplazadas más la vigente, de la más nueva a la más vieja.
        Sin `id_documento` devuelve el historial de toda la empresa.
        """
        condicion = "AND h.id_documento = :id_documento" if id_documento else ""
        parametros = {"id_empresa": str(id_empresa)}
        if id_documento:
            parametros["id_documento"] = str(id_documento)

        resultado = await self.db.execute(
            text(f"""
                SELECT h.id_documento, h.version, h.tipo_documento, h.nombre_archivo,
                       h.estado_validacion, h.observaciones, h.fecha_subida,
                       h.fecha_reemplazo, 'Reemplazada' AS situacion
                FROM historial_documento_empresa h
                WHERE h.id_empresa = :id_empresa {condicion}

                UNION ALL

                SELECT d.id_documento, d.version, d.tipo_documento, d.nombre_archivo,
                       d.estado_validacion, d.observaciones, d.fecha_subida,
                       NULL AS fecha_reemplazo, 'Vigente' AS situacion
                FROM documento_empresa d
                WHERE d.id_empresa = :id_empresa
                  {condicion.replace('h.id_documento', 'd.id_documento')}

                ORDER BY fecha_subida DESC NULLS LAST, version DESC;
            """),
            parametros,
        )
        return [dict(fila) for fila in resultado.mappings().all()]
