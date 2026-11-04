"""
M7 — AUDITORÍAS
Evidencias de la auditoría (AUT-031 a AUT-040).

Las fotos y los PDF que respaldan un hallazgo se guardan en
`storage/auditorias/<id_auditoria>/` y en la tabla `evidencia` queda la ruta
relativa, el tipo y un hash SHA-256 del contenido.

El hash es lo que hace útil a AUT-037: si el archivo del servidor cambia o se
corrompe, la verificación lo detecta, porque el hash se calculó al subirlo y
nunca se vuelve a escribir.
"""

import hashlib
import unicodedata
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auditorias.auditoria_service import AuditoriaService

EXTENSIONES_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".mp4"}
TAMANO_MAXIMO_BYTES = 25 * 1024 * 1024  # 25 MB: las fotos de campo pesan

ESTADO_CARGADA = "Cargada"
ESTADO_VALIDADA = "Validada"
ESTADO_REEMPLAZADA = "Reemplazada"

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_ARCHIVOS = RAIZ_PROYECTO / "storage" / "auditorias"

COLUMNAS = """
    id_evidencia, id_auditoria, id_evaluacion, id_hallazgo,
    nombre_archivo, tipo_archivo, ruta_archivo, hash_archivo,
    version, observaciones, estado, id_usuario_subida, fecha_subida
"""


def _nombre_seguro(nombre: str) -> str:
    base = Path(nombre or "evidencia").name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    limpio = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base)
    return limpio.strip() or "evidencia"


class EvidenciaService:
    """Carga, consulta y verificación de las evidencias de campo."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.auditorias = AuditoriaService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    @staticmethod
    def validar_formato(archivo: UploadFile, tamano: int) -> str:
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
                status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo está vacío."
            )
        if tamano > TAMANO_MAXIMO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"El archivo supera el máximo de {TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB.",
            )
        return extension

    def _guardar(self, id_auditoria: UUID, archivo: UploadFile, contenido: bytes) -> tuple[str, str, str]:
        nombre_visible = _nombre_seguro(archivo.filename or "evidencia")
        carpeta = CARPETA_ARCHIVOS / str(id_auditoria)
        carpeta.mkdir(parents=True, exist_ok=True)

        destino = carpeta / f"{uuid4().hex}{Path(nombre_visible).suffix.lower()}"
        destino.write_bytes(contenido)

        try:
            relativa = destino.relative_to(RAIZ_PROYECTO).as_posix()
        except ValueError:
            relativa = destino.as_posix()

        return nombre_visible, relativa, hashlib.sha256(contenido).hexdigest()

    def ruta_absoluta(self, ruta: str) -> Path:
        camino = Path(ruta or "")
        return camino if camino.is_absolute() else RAIZ_PROYECTO / camino

    async def _evidencia(self, id_auditoria: UUID, id_evidencia: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM evidencia
                WHERE id_evidencia = :id AND id_auditoria = :id_auditoria;
            """),
            {"id": str(id_evidencia), "id_auditoria": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La evidencia no existe para esta auditoría.",
            )
        return dict(fila)

    async def _historial(
        self, id_evidencia: UUID, accion: str, version: int, usuario: dict, observacion: str | None = None
    ) -> None:
        await self.db.execute(
            text("""
                INSERT INTO historial_evidencia (
                    id_evidencia, accion, version, observacion, id_usuario, fecha
                )
                VALUES (:id_evidencia, :accion, :version, :observacion, :id_usuario, CURRENT_TIMESTAMP);
            """),
            {
                "id_evidencia": str(id_evidencia),
                "accion": accion,
                "version": version,
                "observacion": observacion,
                "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )

    # ========================================================
    # AUT-031 / AUT-036 · SUBIR Y ASOCIAR
    # ========================================================

    async def subir(
        self,
        id_auditoria: UUID,
        archivo: UploadFile,
        usuario: dict,
        id_hallazgo: UUID | None = None,
        id_evaluacion: UUID | None = None,
        observaciones: str | None = None,
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)

        contenido = await archivo.read()
        extension = self.validar_formato(archivo, len(contenido))
        nombre, ruta, hash_archivo = self._guardar(id_auditoria, archivo, contenido)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO evidencia (
                    id_auditoria, id_evaluacion, id_hallazgo, nombre_archivo,
                    tipo_archivo, ruta_archivo, hash_archivo, version,
                    observaciones, estado, id_usuario_subida, fecha_subida
                )
                VALUES (
                    :id_auditoria, :id_evaluacion, :id_hallazgo, :nombre,
                    :tipo, :ruta, :hash, 1,
                    :observaciones, :estado, :usuario, CURRENT_TIMESTAMP
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_auditoria": str(id_auditoria),
                "id_evaluacion": str(id_evaluacion) if id_evaluacion else None,
                "id_hallazgo": str(id_hallazgo) if id_hallazgo else None,
                "nombre": nombre,
                "tipo": extension.lstrip("."),
                "ruta": ruta,
                "hash": hash_archivo,
                "observaciones": observaciones,
                "estado": ESTADO_CARGADA,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        evidencia = dict(resultado.mappings().first())

        await self._historial(evidencia["id_evidencia"], "Evidencia cargada", 1, usuario)
        await self.db.commit()
        return evidencia

    async def asociar(
        self, id_auditoria: UUID, id_evidencia: UUID, id_evaluacion: UUID, usuario: dict
    ) -> dict:
        """AUT-036: ata una evidencia ya cargada a un requisito evaluado."""
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        await self._evidencia(id_auditoria, id_evidencia)

        resultado = await self.db.execute(
            text(f"""
                UPDATE evidencia SET id_evaluacion = :id_evaluacion
                WHERE id_evidencia = :id
                RETURNING {COLUMNAS};
            """),
            {"id_evaluacion": str(id_evaluacion), "id": str(id_evidencia)},
        )
        await self._historial(id_evidencia, "Evidencia asociada a un requisito", 1, usuario)
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-033 · REEMPLAZAR
    # ========================================================

    async def reemplazar(
        self, id_auditoria: UUID, id_evidencia: UUID, archivo: UploadFile, usuario: dict
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        evidencia = await self._evidencia(id_auditoria, id_evidencia)

        if evidencia["estado"] == ESTADO_VALIDADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La evidencia ya fue validada y no se puede reemplazar.",
            )

        contenido = await archivo.read()
        extension = self.validar_formato(archivo, len(contenido))
        nombre, ruta, hash_archivo = self._guardar(id_auditoria, archivo, contenido)

        resultado = await self.db.execute(
            text(f"""
                UPDATE evidencia
                SET nombre_archivo = :nombre,
                    tipo_archivo = :tipo,
                    ruta_archivo = :ruta,
                    hash_archivo = :hash,
                    version = version + 1,
                    estado = :estado,
                    id_usuario_subida = :usuario,
                    fecha_subida = CURRENT_TIMESTAMP
                WHERE id_evidencia = :id
                RETURNING {COLUMNAS};
            """),
            {
                "nombre": nombre,
                "tipo": extension.lstrip("."),
                "ruta": ruta,
                "hash": hash_archivo,
                "estado": ESTADO_CARGADA,
                "usuario": str(usuario["id_usuario"]),
                "id": str(id_evidencia),
            },
        )
        nueva = dict(resultado.mappings().first())

        await self._historial(
            id_evidencia, "Evidencia reemplazada", nueva["version"], usuario,
            f"Versión anterior: {evidencia['nombre_archivo']}",
        )
        await self.db.commit()
        return nueva

    # ========================================================
    # AUT-034 · ELIMINAR UNA EVIDENCIA PENDIENTE
    # ========================================================

    async def eliminar(self, id_auditoria: UUID, id_evidencia: UUID, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        evidencia = await self._evidencia(id_auditoria, id_evidencia)

        if evidencia["estado"] == ESTADO_VALIDADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Una evidencia validada no se elimina: forma parte del expediente.",
            )

        await self._historial(id_evidencia, "Evidencia eliminada", evidencia["version"], usuario)
        await self.db.execute(
            text("DELETE FROM evidencia WHERE id_evidencia = :id;"), {"id": str(id_evidencia)}
        )
        await self.db.commit()
        return {"mensaje": "Evidencia eliminada.", "evidencia": evidencia}

    # ========================================================
    # AUT-032 / AUT-035 · DESCARGAR Y CONSULTAR
    # ========================================================

    async def listar(
        self, id_auditoria: UUID, id_hallazgo: UUID | None = None
    ) -> list[dict]:
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT e.id_evidencia, e.nombre_archivo, e.tipo_archivo, e.version,
                       e.estado, e.observaciones, e.fecha_subida, e.hash_archivo,
                       e.id_hallazgo, e.id_evaluacion,
                       COALESCE(u.nombre, u.correo) AS subida_por
                FROM evidencia e
                LEFT JOIN usuario u ON u.id_usuario = e.id_usuario_subida
                WHERE e.id_auditoria = :id_auditoria
                  AND (CAST(:id_hallazgo AS UUID) IS NULL
                       OR e.id_hallazgo = CAST(:id_hallazgo AS UUID))
                ORDER BY e.fecha_subida DESC;
            """),
            {
                "id_auditoria": str(id_auditoria),
                "id_hallazgo": str(id_hallazgo) if id_hallazgo else None,
            },
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def archivo(self, id_auditoria: UUID, id_evidencia: UUID) -> tuple[Path, str]:
        evidencia = await self._evidencia(id_auditoria, id_evidencia)
        ruta = self.ruta_absoluta(evidencia["ruta_archivo"] or "")
        if not evidencia["ruta_archivo"] or not ruta.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo de la evidencia ya no está disponible.",
            )
        return ruta, evidencia["nombre_archivo"] or ruta.name

    # ========================================================
    # AUT-037 · VALIDAR LA INTEGRIDAD
    # ========================================================

    async def verificar_integridad(self, id_auditoria: UUID, id_evidencia: UUID) -> dict:
        evidencia = await self._evidencia(id_auditoria, id_evidencia)
        ruta = self.ruta_absoluta(evidencia["ruta_archivo"] or "")

        if not evidencia["ruta_archivo"] or not ruta.is_file():
            return {
                "id_evidencia": evidencia["id_evidencia"],
                "integra": False,
                "motivo": "El archivo no está en el servidor.",
            }

        actual = hashlib.sha256(ruta.read_bytes()).hexdigest()
        integra = actual == evidencia["hash_archivo"]
        return {
            "id_evidencia": evidencia["id_evidencia"],
            "nombre_archivo": evidencia["nombre_archivo"],
            "integra": integra,
            "hash_registrado": evidencia["hash_archivo"],
            "hash_actual": actual,
            "motivo": None if integra else "El contenido del archivo cambió desde que se cargó.",
        }

    # ========================================================
    # AUT-038 · OBSERVACIONES Y VALIDACIÓN
    # ========================================================

    async def registrar_observacion(
        self, id_auditoria: UUID, id_evidencia: UUID, observaciones: str, usuario: dict,
        validar: bool = False,
    ) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        AuditoriaService.exigir_abierta(auditoria)
        await self._evidencia(id_auditoria, id_evidencia)

        resultado = await self.db.execute(
            text(f"""
                UPDATE evidencia
                SET observaciones = :observaciones,
                    estado = CASE WHEN :validar THEN :validada ELSE estado END
                WHERE id_evidencia = :id
                RETURNING {COLUMNAS};
            """),
            {
                "observaciones": observaciones,
                "validar": validar,
                "validada": ESTADO_VALIDADA,
                "id": str(id_evidencia),
            },
        )
        actualizada = dict(resultado.mappings().first())
        await self._historial(
            id_evidencia, "Observación sobre la evidencia",
            actualizada["version"], usuario, observaciones,
        )
        await self.db.commit()
        return actualizada

    # ========================================================
    # AUT-039 / AUT-040 · PAQUETE E HISTORIAL
    # ========================================================

    async def paquete(self, id_auditoria: UUID) -> dict:
        """
        AUT-039: el inventario del paquete de evidencias, con su verificación.
        Se entrega como listado y no como ZIP para no duplicar archivos que ya
        están en el servidor; cada uno se descarga con AUT-032.
        """
        evidencias = await self.listar(id_auditoria)
        revisadas = []
        for evidencia in evidencias:
            revision = await self.verificar_integridad(id_auditoria, evidencia["id_evidencia"])
            revisadas.append({**evidencia, "integra": revision["integra"]})

        return {
            "id_auditoria": str(id_auditoria),
            "total": len(revisadas),
            "integras": sum(1 for e in revisadas if e["integra"]),
            "evidencias": revisadas,
        }

    async def historial(self, id_auditoria: UUID) -> list[dict]:
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.accion, h.version, h.observacion, h.fecha,
                       e.nombre_archivo, COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_evidencia h
                JOIN evidencia e ON e.id_evidencia = h.id_evidencia
                LEFT JOIN usuario u ON u.id_usuario = h.id_usuario
                WHERE e.id_auditoria = :id_auditoria
                ORDER BY h.fecha;
            """),
            {"id_auditoria": str(id_auditoria)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]
