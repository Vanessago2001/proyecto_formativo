from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes.solicitud_service import SolicitudService


APELACION_EDITABLE = {"ENVIADA", "EN_REVISION", "INFORMACION_SOLICITADA"}
APELACION_FINAL = {"APROBADA", "RECHAZADA", "CANCELADA"}
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_EVIDENCIAS = RAIZ_PROYECTO / "storage" / "apelaciones"
EXTENSIONES_EVIDENCIA = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}

# La base solo admite estos tipos (restriccion chk_tipo_evidencia), asi que se
# traduce la extension del archivo a uno de ellos.
TIPOS_EVIDENCIA = {
    ".pdf": "Documento PDF",
    ".jpg": "Fotografía",
    ".jpeg": "Fotografía",
    ".png": "Fotografía",
    ".doc": "Informe Técnico",
    ".docx": "Informe Técnico",
}
TIPO_EVIDENCIA_POR_DEFECTO = "Otro"
TAMANO_MAXIMO_EVIDENCIA = 10 * 1024 * 1024


class ApelacionesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _generar_radicado(self) -> str:
        result = await self.db.execute(text("SELECT nextval('apelacion_radicado_seq') AS siguiente;"))
        siguiente = result.scalar() or 1
        anio = datetime.now(timezone.utc).year
        return f"APE-{anio}-{siguiente:06d}"

    async def create_apelacion(self, data: dict, usuario: dict) -> dict:
        id_solicitud = UUID(str(data["id_solicitud"]))
        solicitudes = SolicitudService(self.db)
        solicitud = await solicitudes.consultar(id_solicitud, usuario)
        await solicitudes._exigir_propiedad(solicitud, usuario)
        if str(solicitud.get("estado", "")).strip().lower() != "rechazada":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se puede apelar una solicitud en estado Rechazada.",
            )

        existente = await self.db.execute(
            text("SELECT id FROM apelacion WHERE id_solicitud = :id_solicitud;"),
            {"id_solicitud": id_solicitud},
        )
        if existente.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta solicitud ya tiene una apelación registrada.",
            )

        codigo = await self._generar_radicado()
        usuario_id = UUID(str(usuario["id_usuario"]))
        razones_rechazo = solicitud.get("observaciones") or data.get("razones_rechazo")
        payload = {
            "id_solicitud": id_solicitud,
            "id_usuario_presenta": usuario_id,
            "id_empresa": UUID(str(solicitud["id_empresa"])),
            "estado": "ENVIADA",
            "radicado": codigo,
            "motivo": data.get("motivo"),
            "razones_rechazo": razones_rechazo or data.get("fallo"),
            "fallo": bool(data.get("fallo", False)),
        }

        query = text("""
            INSERT INTO apelacion (
                id, id_solicitud, id_usuario_presenta, id_empresa, estado, radicado,
                fecha, motivo, razones_rechazo, fallo
            )
            VALUES (
                gen_random_uuid(), :id_solicitud, :id_usuario_presenta, :id_empresa, :estado, :radicado,
                CURRENT_TIMESTAMP, :motivo, :razones_rechazo, :fallo
            )
            RETURNING id, id_solicitud, id_empresa, estado,
                      radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        try:
            result = await self.db.execute(query, payload)
        except IntegrityError as exc:
            await self.db.rollback()
            # Solo es duplicado si choca con la unicidad por solicitud; cualquier
            # otro fallo de integridad se deja ver tal cual, en vez de disfrazarlo.
            origen = getattr(exc, "orig", None)
            if getattr(origen, "sqlstate", None) == "23505":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="La solicitud ya tiene una apelación registrada.",
                ) from exc
            raise
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def add_evidence(
        self,
        id_apelacion: UUID,
        archivo: UploadFile,
        descripcion: str | None,
        usuario: dict,
    ) -> dict:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion:
            return None
        if apelacion.get("estado") not in APELACION_EDITABLE:
            raise HTTPException(status_code=409, detail="La apelación ya no admite evidencias.")

        nombre = Path(archivo.filename or "evidencia").name
        extension = Path(nombre).suffix.lower()
        contenido = await archivo.read()
        if extension not in EXTENSIONES_EVIDENCIA:
            raise HTTPException(status_code=415, detail="Formato no permitido para evidencia.")
        if not contenido:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        if len(contenido) > TAMANO_MAXIMO_EVIDENCIA:
            raise HTTPException(status_code=413, detail="El tamaño máximo permitido es 10 MB.")

        carpeta = CARPETA_EVIDENCIAS / str(id_apelacion)
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre_disco = f"{uuid4()}{extension}"
        destino = carpeta / nombre_disco
        destino.write_bytes(contenido)
        ruta_relativa = str(destino.relative_to(RAIZ_PROYECTO))
        payload = {
            "id_apelacion": id_apelacion,
            "id_usuario_subio": UUID(str(usuario["id_usuario"])),
            "nombre_archivo": nombre,
            "tipo_evidencia": TIPOS_EVIDENCIA.get(extension, TIPO_EVIDENCIA_POR_DEFECTO),
            "url_archivo": ruta_relativa,
            "descripcion": descripcion,
        }

        query = text("""
            INSERT INTO evidencia_apelacion (
                id_apelacion, id_usuario_subio, nombre_archivo, tipo_evidencia,
                url_archivo, descripcion, fecha_subida
            )
            VALUES (
                :id_apelacion, :id_usuario_subio, :nombre_archivo, :tipo_evidencia,
                :url_archivo, :descripcion, CURRENT_TIMESTAMP
            )
            RETURNING id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                      nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida;
        """)
        try:
            result = await self.db.execute(query, payload)
            await self.db.commit()
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception:
            destino.unlink(missing_ok=True)
            await self.db.rollback()
            raise

    async def update_apelacion(self, id_apelacion: UUID, data: dict, usuario: dict) -> dict:
        existing = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not existing:
            return None
        if existing.get("estado") not in APELACION_EDITABLE:
            return None

        payload = {
            "id": id_apelacion,
            "motivo": data.get("motivo", existing.get("motivo")),
        }

        query = text("""
            UPDATE apelacion
            SET motivo = :motivo
            WHERE id = :id
            RETURNING id, id_solicitud, id_empresa,
                      estado, radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_all_apelaciones(self, usuario: dict) -> list[dict]:
        from modules.solicitudes.solicitud_permissions import normalizar_rol, ROL_EMP

        filtro_empresa = normalizar_rol(usuario.get("role_name")) == ROL_EMP
        query = text("""
            SELECT a.id, a.id_solicitud,
                   a.id_empresa, a.estado, a.radicado, a.fecha, a.motivo,
                   a.razones_rechazo, a.fallo
            FROM apelacion a
            WHERE NOT :filtro_empresa OR a.id_solicitud IN (
                SELECT s.id_solicitud
                FROM solicitud s
                JOIN user_empresa ue ON ue.id_empresa = s.id_empresa
                WHERE ue.id_usuario = :id_usuario AND ue.estado = 'Activo'
            )
            ORDER BY a.fecha DESC, a.id DESC;
        """)
        result = await self.db.execute(query, {
            "filtro_empresa": filtro_empresa,
            "id_usuario": str(usuario.get("id_usuario")),
        })
        return [dict(row) for row in result.mappings().all()]

    async def get_apelacion_by_id(self, id_apelacion: UUID, usuario: dict | None = None) -> dict:
        query = text("""
            SELECT id, id_solicitud,
                   id_empresa, id_auditor_evaluador, estado, radicado, fecha,
                   motivo, razones_rechazo, fallo, observaciones, fecha_decision
            FROM apelacion
            WHERE id = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        row = result.mappings().first()
        appeal = dict(row) if row else None
        if appeal and usuario and appeal.get("id_solicitud"):
            try:
                await SolicitudService(self.db).consultar(UUID(str(appeal["id_solicitud"])), usuario)
            except (ValueError, HTTPException):
                return None
        return appeal

    async def assign_committee(self, id_apelacion: UUID, miembros_comite: list[UUID], id_auditor_evaluador: UUID | None = None) -> dict:
        if not miembros_comite:
            raise ValueError("Debe indicar al menos un miembro del comité.")
        if id_auditor_evaluador is not None and any(miembro == id_auditor_evaluador for miembro in miembros_comite):
            raise ValueError("No se puede asignar un auditor que evaluó la solicitud original al comité de apelación.")

        existe = await self.db.execute(
            text("SELECT 1 FROM apelacion WHERE id = :id_apelacion;"),
            {"id_apelacion": id_apelacion},
        )
        if existe.scalar() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La apelación no existe.",
            )

        await self.db.execute(
            text("DELETE FROM apelacion_comite WHERE id_apelacion = :id_apelacion;"),
            {"id_apelacion": id_apelacion},
        )

        for miembro in miembros_comite:
            await self.db.execute(
                text("""
                    INSERT INTO apelacion_comite (id_apelacion, id_usuario, asignado_en)
                    VALUES (:id_apelacion, :id_usuario, CURRENT_TIMESTAMP)
                """),
                {"id_apelacion": id_apelacion, "id_usuario": miembro},
            )

        await self.db.execute(
            text("""
                UPDATE apelacion
                SET id_auditor_evaluador = :id_auditor_evaluador,
                    estado = CASE
                        WHEN estado IN ('ENVIADA', 'INFORMACION_SOLICITADA') THEN 'EN_REVISION'
                        ELSE estado
                    END
                WHERE id = :id_apelacion;
            """),
            {"id_apelacion": id_apelacion, "id_auditor_evaluador": id_auditor_evaluador},
        )

        await self.db.commit()
        return {"id_apelacion": id_apelacion, "miembros_comite": miembros_comite}

    async def cancelar_apelacion(self, id_apelacion: UUID, usuario: dict) -> dict:
        current = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not current:
            return None
        if current.get("estado") in APELACION_FINAL:
            return None
        query = text("""
            UPDATE apelacion
            SET estado = 'CANCELADA'
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, id_solicitud, id_empresa, estado, radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_historial(self, id_apelacion: UUID, usuario: dict) -> list[dict]:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion:
            return []

        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                   nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion
            ORDER BY fecha_subida DESC;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        evidencias = [dict(row) for row in result.mappings().all()]

        historial = [apelacion]
        historial.extend(evidencias)
        return historial

    async def get_evidencias_previas(self, id_apelacion: UUID, usuario: dict) -> list[dict]:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return []
        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                   nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        return [dict(row) for row in result.mappings().all()]

    async def solicitar_info_adicional(self, id_apelacion: UUID, requerimiento: str, usuario: dict) -> dict:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion or apelacion.get("estado") not in APELACION_EDITABLE:
            return None
        query = text("""
            UPDATE apelacion
            SET estado = 'INFORMACION_SOLICITADA',
                observaciones = :requerimiento,
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, estado, observaciones;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "requerimiento": requerimiento,
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def registrar_decision_final(self, id_apelacion: UUID, decision: str, observaciones: str | None, usuario: dict) -> dict:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return None
        query = text("""
            UPDATE apelacion
            SET estado = CAST(:decision AS VARCHAR),
                observaciones = :observaciones,
                fallo = (CAST(:decision AS VARCHAR) = 'RECHAZADA'),
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, estado, observaciones, fecha_decision;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "decision": decision,
            "observaciones": observaciones,
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def cambiar_estado_dictamen(self, id_apelacion: UUID, nuevo_estado: str, usuario: dict) -> dict:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        transiciones = {
            "APROBADA": APELACION_EDITABLE,
            "RECHAZADA": APELACION_EDITABLE,
            "NOTIFICADA": {"APROBADA", "RECHAZADA"},
            "CERRADA": {"NOTIFICADA"},
        }
        estados_anteriores = transiciones.get(nuevo_estado)
        if not estados_anteriores:
            raise ValueError("El dictamen no es válido.")
        if not apelacion or apelacion.get("estado") not in estados_anteriores:
            return None
        query = text("""
            UPDATE apelacion
            SET estado = CAST(:nuevo_estado AS VARCHAR),
                fallo = CASE
                    WHEN CAST(:nuevo_estado AS VARCHAR) = 'APROBADA' THEN FALSE
                    WHEN CAST(:nuevo_estado AS VARCHAR) = 'RECHAZADA' THEN TRUE
                    ELSE fallo
                END,
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado = :estado_anterior
            RETURNING id, estado, fallo, fecha_decision;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "nuevo_estado": nuevo_estado,
            "estado_anterior": apelacion["estado"],
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def obtener_archivo_evidencia(self, id_apelacion: UUID, id_evidencia: UUID, usuario: dict) -> tuple[Path, str] | None:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return None
        result = await self.db.execute(text("""
            SELECT nombre_archivo, url_archivo
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion AND id_evidencia = :id_evidencia;
        """), {"id_apelacion": id_apelacion, "id_evidencia": id_evidencia})
        evidence = result.mappings().first()
        if not evidence:
            return None
        ruta = (RAIZ_PROYECTO / evidence["url_archivo"]).resolve()
        if not ruta.is_relative_to(CARPETA_EVIDENCIAS.resolve()) or not ruta.is_file():
            return None
        return ruta, evidence["nombre_archivo"]