from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class EmpresasService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_empresas(self) -> list[dict]:
        result = await self.db.execute(text("""
            SELECT id_empresa, nombre, nit, ciudad, direccion, correo
            FROM empresa
            ORDER BY nombre ASC;
        """))
        return [dict(row) for row in result.mappings().all()]

    async def create_empresa(self, data: dict) -> dict:
        query = text("""
            INSERT INTO empresa (nombre, nit, ciudad, direccion, correo)
            VALUES (:nombre, :nit, :ciudad, :direccion, :correo)
            RETURNING id_empresa, nombre, nit, ciudad, direccion, correo;
        """)
        result = await self.db.execute(query, data)
        await self.db.commit()
        return dict(result.mappings().first())

    async def get_empresa_by_id(self, id_empresa: int) -> dict:
        query = text("""
            SELECT id_empresa, nombre, nit, ciudad, direccion, correo
            FROM empresa
            WHERE id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        row = result.mappings().first()
        return dict(row) if row else None

    async def update_empresa(self, id_empresa: int, data: dict) -> dict:
        query = text("""
            UPDATE empresa
            SET nombre = :nombre, nit = :nit, ciudad = :ciudad, direccion = :direccion, correo = :correo
            WHERE id_empresa = :id_empresa
            RETURNING id_empresa, nombre, nit, ciudad, direccion, correo;
        """)
        data["id_empresa"] = id_empresa
        result = await self.db.execute(query, data)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_usuarios_by_empresa(self, id_empresa: int) -> list[dict]:
        query = text("""
            SELECT u.* FROM usuario u
            JOIN user_empresa ue ON u.id_usuario = ue.usuario_id
            WHERE ue.empresa_id = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_historial_solicitudes_by_empresa(self, id_empresa: int) -> list[dict]:
        query = text("""
            SELECT * FROM solicitud WHERE id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_sedes_by_empresa(self, id_empresa: int) -> list[dict]:
        query = text("""
            SELECT id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                   es_principal, estado, fecha_registro
            FROM sede
            WHERE id_empresa = :id_empresa
            ORDER BY es_principal DESC, id_sede ASC;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_sede_by_id(self, id_empresa: int, id_sede: int) -> dict | None:
        query = text("""
            SELECT id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                   es_principal, estado, fecha_registro
            FROM sede
            WHERE id_empresa = :id_empresa
              AND id_sede = :id_sede;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa, "id_sede": id_sede})
        row = result.mappings().first()
        return dict(row) if row else None

    async def create_sede(self, id_empresa: int, data: dict) -> dict | None:
        empresa = await self.get_empresa_by_id(id_empresa)
        if not empresa:
            return None

        payload = {
            "id_empresa": id_empresa,
            "nombre_sede": data.get("nombre_sede"),
            "direccion": data.get("direccion"),
            "ciudad": data.get("ciudad"),
            "departamento": data.get("departamento"),
            "pais": data.get("pais"),
            "es_principal": data.get("es_principal", False),
            "estado": data.get("estado") or "Activo",
        }

        insert_sede = text("""
            INSERT INTO sede (
                id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                es_principal, estado, fecha_registro
            )
            VALUES (
                :id_empresa, :nombre_sede, :direccion, :ciudad, :departamento, :pais,
                :es_principal, :estado, CURRENT_TIMESTAMP
            )
            RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                      es_principal, estado, fecha_registro;
        """)
        result = await self.db.execute(insert_sede, payload)
        sede_row = result.mappings().first()
        if not sede_row:
            await self.db.rollback()
            return None

        await self.db.commit()
        return dict(sede_row)

    async def update_sede(self, id_empresa: int, id_sede: int, data: dict) -> dict | None:
        current = await self.get_sede_by_id(id_empresa, id_sede)
        if not current:
            return None

        payload = {
            "id_empresa": id_empresa,
            "id_sede": id_sede,
            "nombre_sede": data.get("nombre_sede", current.get("nombre_sede")),
            "direccion": data.get("direccion", current.get("direccion")),
            "ciudad": data.get("ciudad", current.get("ciudad")),
            "departamento": data.get("departamento", current.get("departamento")),
            "pais": data.get("pais", current.get("pais")),
            "es_principal": data.get("es_principal", current.get("es_principal")),
            "estado": data.get("estado", current.get("estado")),
        }

        query = text("""
            UPDATE sede
            SET nombre_sede = :nombre_sede,
                direccion = :direccion,
                ciudad = :ciudad,
                departamento = :departamento,
                pais = :pais,
                es_principal = :es_principal,
                estado = :estado
            WHERE id_empresa = :id_empresa
              AND id_sede = :id_sede
            RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                      es_principal, estado, fecha_registro;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def delete_sede(self, id_empresa: int, id_sede: int) -> dict | None:
        existing = await self.get_sede_by_id(id_empresa, id_sede)
        if not existing:
            return None

        result = await self.db.execute(
            text("""
                DELETE FROM sede
                WHERE id_empresa = :id_empresa
                  AND id_sede = :id_sede
                RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                          es_principal, estado, fecha_registro;
            """),
            {"id_empresa": id_empresa, "id_sede": id_sede},
        )
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_documentos_by_empresa(self, id_empresa: int) -> list[dict]:
        query = text("""
            SELECT * FROM documento_empresa WHERE empresa_id = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

