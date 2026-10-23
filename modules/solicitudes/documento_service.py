"""
M5 — GESTIÓN DE SOLICITUDES
Lógica del Bloque 4 (documentos adjuntos, SOL-031 a SOL-040).

Trabaja sobre las tablas `documento_solicitud` y
`historial_documento_solicitud`, que ya existen en la base de datos.

Los archivos se guardan en disco bajo `storage/solicitudes/<id_solicitud>/`
y en la columna `url_archivo` queda la ruta relativa. Es lo más simple que
funciona; si el proyecto pasa a varios servidores habrá que mover esto a un
almacenamiento compartido (S3 o similar) cambiando solo `_guardar_archivo`
y `ruta_absoluta`.
"""

import shutil
import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes.documento_schema import (
    ESTADOS_MODIFICABLES,
    EstadoDocumento,
)
from modules.solicitudes.solicitud_service import SolicitudService

# ============================================================
# VALIDACIÓN AUTOMÁTICA DE FORMATO (SOL-036)
# ============================================================

EXTENSIONES_PERMITIDAS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
TAMANO_MAXIMO_BYTES = 10 * 1024 * 1024  # 10 MB

# Tipos que el portal de empresa pide de entrada. No es una lista cerrada:
# la administración puede exigir otros según la norma solicitada.
TIPOS_DOCUMENTO_SUGERIDOS = [
    "Documento de existencia",
    "Registro tributario",
    "Documentos del proceso",
]

# Carpeta raíz de los archivos, relativa a la raíz del proyecto.
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_ARCHIVOS = RAIZ_PROYECTO / "storage" / "solicitudes"

COLUMNAS_DOCUMENTO = """
    id_documento,
    id_solicitud,
    tipo_documento,
    nombre_archivo,
    version,
    estado,
    observaciones,
    usuario_subida,
    usuario_revision,
    fecha_subida,
    fecha_revision
"""


def _nombre_seguro(nombre: str) -> str:
    """
    Deja el nombre del archivo en algo inofensivo para el sistema de ficheros.

    Quita tildes, rutas y cualquier carácter raro: el nombre original solo se
    usa para mostrarlo y para descargarlo, nunca para construir la ruta real.
    """
    base = Path(nombre or "documento").name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    limpio = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base)
    return limpio.strip() or "documento"


class DocumentoService:
    """Operaciones sobre los documentos adjuntos de una solicitud."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    @staticmethod
    def validar_formato(archivo: UploadFile, tamano: int) -> None:
        """
        SOL-036: validación automática de formato.

        Se comprueba al subir y al reemplazar; no hay forma de saltársela.
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
                detail=(
                    f"El archivo pesa {tamano / 1024 / 1024:.1f} MB y el máximo "
                    f"son {TAMANO_MAXIMO_BYTES // 1024 // 1024} MB."
                ),
            )

    @staticmethod
    def ruta_absoluta(url_archivo: str) -> Path:
        """Traduce lo guardado en `url_archivo` a una ruta real en disco."""
        return RAIZ_PROYECTO / url_archivo

    def _guardar_archivo(
        self,
        archivo: UploadFile,
        id_solicitud: UUID | str,
        id_documento: UUID | str,
    ) -> str:
        """
        Escribe el archivo en disco y devuelve la ruta relativa a guardar.

        El nombre real en disco es el id del documento, así que dos archivos
        con el mismo nombre nunca se pisan.
        """
        carpeta = CARPETA_ARCHIVOS / str(id_solicitud)
        carpeta.mkdir(parents=True, exist_ok=True)

        extension = Path(archivo.filename or "").suffix.lower()
        destino = carpeta / f"{id_documento}{extension}"

        archivo.file.seek(0)
        with destino.open("wb") as salida:
            shutil.copyfileobj(archivo.file, salida)

        return str(destino.relative_to(RAIZ_PROYECTO))

    async def _obtener_documento(
        self,
        id_solicitud: UUID,
        id_documento: UUID,
        usuario: dict,
    ) -> dict:
        """Trae un documento validando el acceso a su solicitud."""
        # Esto ya lanza 404 si la solicitud no es visible para el usuario.
        await self.solicitudes.consultar(id_solicitud, usuario)

        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_DOCUMENTO}, url_archivo
                FROM documento_solicitud
                WHERE id_documento = :id_documento
                  AND id_solicitud = :id_solicitud;
            """),
            {
                "id_documento": str(id_documento),
                "id_solicitud": str(id_solicitud),
            },
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El documento no existe en esta solicitud.",
            )

        return dict(fila)

    # ========================================================
    # SOL-031 — SUBIR DOCUMENTO REQUERIDO
    # ========================================================

    async def subir(
        self,
        id_solicitud: UUID,
        tipo_documento: str,
        archivo: UploadFile,
        usuario: dict,
    ) -> dict:
        """
        SOL-031: adjunta un documento nuevo a la solicitud.

        Si ya existe uno del mismo tipo se rechaza: para cambiarlo está
        SOL-032 (reemplazar), que conserva el historial de versiones.
        """
        solicitud = await self.solicitudes.consultar(id_solicitud, usuario)
        await self.solicitudes._exigir_propiedad(solicitud, usuario)

        contenido = await archivo.read()
        self.validar_formato(archivo, len(contenido))
        await archivo.seek(0)

        repetido = await self.db.execute(
            text("""
                SELECT id_documento FROM documento_solicitud
                WHERE id_solicitud = :id_solicitud
                  AND LOWER(tipo_documento) = LOWER(:tipo_documento);
            """),
            {"id_solicitud": str(id_solicitud), "tipo_documento": tipo_documento},
        )
        if repetido.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Ya hay un documento de tipo '{tipo_documento}' en esta "
                    "solicitud. Use el reemplazo (SOL-032) para actualizarlo."
                ),
            )

        id_documento = uuid4()
        url = self._guardar_archivo(archivo, id_solicitud, id_documento)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO documento_solicitud (
                    id_documento, id_solicitud, tipo_documento, nombre_archivo,
                    url_archivo, version, estado, usuario_subida, fecha_subida
                )
                VALUES (
                    :id_documento, :id_solicitud, :tipo_documento, :nombre_archivo,
                    :url_archivo, 1, :estado, :usuario_subida, NOW()
                )
                RETURNING {COLUMNAS_DOCUMENTO};
            """),
            {
                "id_documento": str(id_documento),
                "id_solicitud": str(id_solicitud),
                "tipo_documento": tipo_documento,
                "nombre_archivo": _nombre_seguro(archivo.filename),
                "url_archivo": url,
                "estado": EstadoDocumento.pendiente.value,
                "usuario_subida": str(usuario.get("id_usuario")),
            },
        )
        documento = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Documento adjuntado: {tipo_documento}",
        )
        await self.db.commit()

        return documento

    # ========================================================
    # SOL-032 — REEMPLAZAR DOCUMENTO
    # ========================================================

    async def reemplazar(
        self,
        id_solicitud: UUID,
        id_documento: UUID,
        archivo: UploadFile,
        usuario: dict,
    ) -> dict:
        """
        SOL-032: sube una versión nueva conservando la anterior.

        La versión que se va queda en `historial_documento_solicitud`, así que
        nunca se pierde lo que la empresa presentó antes.
        """
        documento = await self._obtener_documento(id_solicitud, id_documento, usuario)
        solicitud = await self.solicitudes.consultar(id_solicitud, usuario)
        await self.solicitudes._exigir_propiedad(solicitud, usuario)

        if EstadoDocumento(documento["estado"]) not in ESTADOS_MODIFICABLES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No se puede reemplazar un documento ya aprobado. "
                    f"Estado actual: {documento['estado']}."
                ),
            )

        contenido = await archivo.read()
        self.validar_formato(archivo, len(contenido))
        await archivo.seek(0)

        # 1. Se archiva la versión vigente.
        await self.db.execute(
            text("""
                INSERT INTO historial_documento_solicitud (
                    id_documento, id_solicitud, version, nombre_archivo,
                    url_archivo, estado, observaciones, usuario_subida,
                    fecha_subida
                )
                SELECT
                    id_documento, id_solicitud, version, nombre_archivo,
                    url_archivo, estado, observaciones, usuario_subida,
                    fecha_subida
                FROM documento_solicitud
                WHERE id_documento = :id_documento;
            """),
            {"id_documento": str(id_documento)},
        )

        # 2. Se guarda el archivo nuevo con la versión siguiente en el nombre,
        #    para no sobrescribir el fichero de la versión archivada.
        nueva_version = int(documento["version"] or 1) + 1
        url = self._guardar_archivo(
            archivo, id_solicitud, f"{id_documento}_v{nueva_version}"
        )

        resultado = await self.db.execute(
            text(f"""
                UPDATE documento_solicitud
                SET nombre_archivo = :nombre_archivo,
                    url_archivo = :url_archivo,
                    version = :version,
                    estado = :estado,
                    observaciones = NULL,
                    usuario_subida = :usuario_subida,
                    usuario_revision = NULL,
                    fecha_subida = NOW(),
                    fecha_revision = NULL
                WHERE id_documento = :id_documento
                RETURNING {COLUMNAS_DOCUMENTO};
            """),
            {
                "nombre_archivo": _nombre_seguro(archivo.filename),
                "url_archivo": url,
                "version": nueva_version,
                "estado": EstadoDocumento.pendiente.value,
                "usuario_subida": str(usuario.get("id_usuario")),
                "id_documento": str(id_documento),
            },
        )
        actualizado = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Documento reemplazado: {documento['tipo_documento']} (v{nueva_version})",
        )
        await self.db.commit()

        return actualizado

    # ========================================================
    # SOL-033 — ELIMINAR DOCUMENTO
    # ========================================================

    async def eliminar(
        self,
        id_solicitud: UUID,
        id_documento: UUID,
        usuario: dict,
    ) -> dict:
        """
        SOL-033: quita un documento que aún no ha sido aprobado.

        El archivo en disco se conserva: el expediente debe poder auditarse.
        """
        documento = await self._obtener_documento(id_solicitud, id_documento, usuario)
        solicitud = await self.solicitudes.consultar(id_solicitud, usuario)
        await self.solicitudes._exigir_propiedad(solicitud, usuario)

        if EstadoDocumento(documento["estado"]) is EstadoDocumento.aprobado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede eliminar un documento ya aprobado.",
            )

        # Se archiva antes de borrar la fila, para no perder la traza.
        await self.db.execute(
            text("""
                INSERT INTO historial_documento_solicitud (
                    id_documento, id_solicitud, version, nombre_archivo,
                    url_archivo, estado, observaciones, usuario_subida,
                    fecha_subida
                )
                SELECT
                    id_documento, id_solicitud, version, nombre_archivo,
                    url_archivo, estado, observaciones, usuario_subida,
                    fecha_subida
                FROM documento_solicitud
                WHERE id_documento = :id_documento;
            """),
            {"id_documento": str(id_documento)},
        )
        await self.db.execute(
            text("DELETE FROM documento_solicitud WHERE id_documento = :id_documento;"),
            {"id_documento": str(id_documento)},
        )

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Documento eliminado: {documento['tipo_documento']}",
        )
        await self.db.commit()

        return {
            "id_documento": str(id_documento),
            "mensaje": "Documento eliminado. Su historial se conserva.",
        }

    # ========================================================
    # SOL-034 / SOL-035 — DESCARGAR, VER Y LISTAR
    # ========================================================

    async def listar(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        """SOL-035: documentos adjuntos de la solicitud."""
        await self.solicitudes.consultar(id_solicitud, usuario)

        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_DOCUMENTO}
                FROM documento_solicitud
                WHERE id_solicitud = :id_solicitud
                ORDER BY tipo_documento;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def obtener_archivo(
        self,
        id_solicitud: UUID,
        id_documento: UUID,
        usuario: dict,
    ) -> tuple[Path, str]:
        """SOL-034 y SOL-035: ruta en disco y nombre original del archivo."""
        documento = await self._obtener_documento(id_solicitud, id_documento, usuario)
        ruta = self.ruta_absoluta(documento["url_archivo"])

        if not ruta.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=(
                    "El registro existe pero el archivo no está en el "
                    "almacenamiento. Debe volver a subirse."
                ),
            )

        return ruta, documento["nombre_archivo"]

    # ========================================================
    # SOL-037 / SOL-038 / SOL-039 — REVISIÓN
    # ========================================================

    async def revisar(
        self,
        id_solicitud: UUID,
        id_documento: UUID,
        nuevo_estado: EstadoDocumento,
        observaciones: str | None,
        usuario: dict,
    ) -> dict:
        """
        SOL-037 (rechazar), SOL-038 (aprobar) y SOL-039 (solicitar corrección).

        Las tres son la misma operación con distinto estado de destino; el
        permiso concreto ya lo verificó el endpoint.
        """
        documento = await self._obtener_documento(id_solicitud, id_documento, usuario)
        solicitud = await self.solicitudes.consultar(id_solicitud, usuario)

        if EstadoDocumento(documento["estado"]) is nuevo_estado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El documento ya está en estado '{nuevo_estado.value}'.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE documento_solicitud
                SET estado = :estado,
                    observaciones = :observaciones,
                    usuario_revision = :usuario_revision,
                    fecha_revision = NOW()
                WHERE id_documento = :id_documento
                RETURNING {COLUMNAS_DOCUMENTO};
            """),
            {
                "estado": nuevo_estado.value,
                "observaciones": observaciones,
                "usuario_revision": str(usuario.get("id_usuario")),
                "id_documento": str(id_documento),
            },
        )
        revisado = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Documento '{documento['tipo_documento']}' -> {nuevo_estado.value}",
        )
        await self.db.commit()

        return revisado

    # ========================================================
    # SOL-040 — HISTORIAL DOCUMENTAL
    # ========================================================

    async def historial(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        """SOL-040: versiones anteriores de todos los documentos."""
        await self.solicitudes.consultar(id_solicitud, usuario)

        resultado = await self.db.execute(
            text("""
                SELECT id_historial, id_documento, version, nombre_archivo,
                       estado, observaciones, usuario_subida, fecha_subida,
                       fecha_reemplazo
                FROM historial_documento_solicitud
                WHERE id_solicitud = :id_solicitud
                ORDER BY fecha_reemplazo DESC;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]
