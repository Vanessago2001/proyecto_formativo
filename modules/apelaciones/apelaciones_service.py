from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ApelacionesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_apelacion(self, data: dict) -> dict:
        payload = {
            "id_solicitud": data.get("id_solicitud"),
            "estado": data.get("estado") or "RADICADA",
            "motivo": data.get("motivo"),
            "fallo": data.get("fallo"),
        }

        query = text("""
            INSERT INTO apelacion (id_solicitud, estado, fecha, motivo, fallo)
            VALUES (:id_solicitud, :estado, CURRENT_TIMESTAMP, :motivo, :fallo)
            RETURNING id, id_solicitud, estado, fecha, motivo, fallo;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def add_evidence(self, id_apelacion: int, data: dict) -> dict:
        payload = {
            "id_apelacion": id_apelacion,
            "id_usuario": data.get("id_usuario"),
            "nombre_archivo": data.get("nombre_archivo"),
            "tipo_evidencia": data.get("tipo_evidencia"),
            "url_archivo": data.get("url_archivo"),
            "descripcion": data.get("descripcion"),
        }

        query = text("""
            INSERT INTO evidencia_apelacion (
                id_apelacion, id_usuario, nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            )
            VALUES (
                :id_apelacion, :id_usuario, :nombre_archivo, :tipo_evidencia, :url_archivo, :descripcion, CURRENT_TIMESTAMP
            )
            RETURNING id_evidencia, id_apelacion, id_usuario, nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def update_apelacion(self, id_apelacion: int, data: dict) -> dict:
        existing = await self.get_apelacion_by_id(id_apelacion)
        if not existing:
            return None

        allowed_states = {"RADICADA", "PENDIENTE_REVISION", "EN_REVISION"}
        if existing.get("estado") not in allowed_states:
            return None

        payload = {
            "id": id_apelacion,
            "id_solicitud": data.get("id_solicitud", existing.get("id_solicitud")),
            "motivo": data.get("motivo", existing.get("motivo")),
            "fallo": data.get("fallo", existing.get("fallo")),
            "estado": data.get("estado", existing.get("estado")),
        }

        query = text("""
            UPDATE apelacion
            SET id_solicitud = :id_solicitud,
                motivo = :motivo,
                fallo = :fallo,
                estado = :estado
            WHERE id = :id
            RETURNING id, id_solicitud, estado, fecha, motivo, fallo;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_all_apelaciones(self) -> list[dict]:
        result = await self.db.execute(text("""
            SELECT id, id_solicitud, estado, fecha, motivo, fallo
            FROM apelacion
            ORDER BY fecha DESC, id DESC;
        """))
        return [dict(row) for row in result.mappings().all()]

    async def get_apelacion_by_id(self, id_apelacion: int) -> dict:
        query = text("""
            SELECT id, id_solicitud, estado, fecha, motivo, fallo
            FROM apelacion
            WHERE id = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        row = result.mappings().first()
        return dict(row) if row else None

    async def cancelar_apelacion(self, id_apelacion: int, estado: str = "CANCELADA") -> dict:
        query = text("""
            UPDATE apelacion
            SET estado = :estado
            WHERE id = :id_apelacion
            RETURNING id, id_solicitud, estado, fecha, motivo, fallo;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "estado": estado})
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def registrar_hilo_legal(self, id_apelacion: int, observaciones: str) -> dict:
        query = text("""
            INSERT INTO hilo_legal_apelacion (apelacion_id, observaciones)
            VALUES (:id_apelacion, :observaciones)
            RETURNING id_hilo, apelacion_id, observaciones, fecha;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "observaciones": observaciones})
        await self.db.commit()
        return dict(result.mappings().first())

    async def get_historial(self, id_apelacion: int) -> list[dict]:
        apelacion = await self.get_apelacion_by_id(id_apelacion)
        if not apelacion:
            return []

        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario, nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion
            ORDER BY fecha_subida DESC;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        evidencias = [dict(row) for row in result.mappings().all()]

        historial = [apelacion]
        historial.extend(evidencias)
        return historial

    async def get_evidencias_previas(self, id_apelacion: int) -> list[dict]:
        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario, nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        return [dict(row) for row in result.mappings().all()]

    async def registrar_analisis_juridico(self, id_apelacion: int, analisis: str) -> dict:
        query = text("""
            INSERT INTO analisis_juridico (apelacion_id, contenido)
            VALUES (:id_apelacion, :analisis)
            RETURNING id_analisis, apelacion_id, contenido;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "analisis": analisis})
        await self.db.commit()
        return dict(result.mappings().first())

    async def solicitar_info_adicional(self, id_apelacion: int, requerimiento: str) -> dict:
        query = text("""
            INSERT INTO requerimiento_apelacion (apelacion_id, descripcion, estado)
            VALUES (:id_apelacion, :requerimiento, 'SOLICITADO')
            RETURNING id_requerimiento, apelacion_id, descripcion, estado;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "requerimiento": requerimiento})
        await self.db.commit()
        return dict(result.mappings().first())

    async def registrar_decision_final(self, id_apelacion: int, decision: str) -> dict:
        query = text("""
            UPDATE apelacion
            SET estado = 'DECISION_REGISTRADA'
            WHERE id = :id_apelacion
            RETURNING id, estado;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def cambiar_estado_dictamen(self, id_apelacion: int, nuevo_estado: str) -> dict:
        query = text("""
            UPDATE apelacion
            SET estado = :nuevo_estado
            WHERE id = :id_apelacion
            RETURNING id, estado;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "nuevo_estado": nuevo_estado})
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def registrar_bitacora_cierre(self, id_apelacion: int, detalle: str) -> dict:
        query = text("""
            INSERT INTO bitacora_apelacion (apelacion_id, detalle)
            VALUES (:id_apelacion, :detalle)
            RETURNING id_bitacora, apelacion_id, detalle, fecha;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion, "detalle": detalle})
        await self.db.commit()
        return dict(result.mappings().first())