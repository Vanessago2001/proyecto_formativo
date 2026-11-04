from uuid import UUID

from sqlalchemy import text

from modules.auditores.auditor_service import AuditorService


class PerfilAuditorService(AuditorService):
    async def obtener_perfil(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT
                    id_perfil,
                    id_usuario,
                    foto_url,
                    ciudad_residencia,
                    departamento_residencia,
                    modalidad_preferida,
                    resumen_profesional,
                    calificacion_promedio
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY id_perfil DESC
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        row = result.mappings().first()
        return dict(row) if row else None
