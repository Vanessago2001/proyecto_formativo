from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.tareas.tarea_schema import (
    TareaCreate,
    TareaEstadoUpdate
)


class TareaService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def crear_tarea(
        self,
        data: TareaCreate
    ):

        query = text("""
            INSERT INTO tareas
            (
                nombre,
                descripcion,
                fecha_vencimiento,
                responsable_hizo,
                estado
            )
            VALUES
            (
                :nombre,
                :descripcion,
                :fecha_vencimiento,
                :responsable_hizo,
                'Pendiente'
            )
            RETURNING id
        """)

        result = await self.db.execute(
            query,
            {
                "nombre": data.nombre,
                "descripcion": data.descripcion,
                "fecha_vencimiento": data.fecha_vencimiento,
                "responsable_hizo": data.responsable_hizo
            }
        )

        await self.db.commit()

        return {
            "message": "Tarea creada correctamente",
            "id": result.scalar()
        }

    async def cambiar_estado(
        self,
        tarea_id: int,
        data: TareaEstadoUpdate
    ):

        query = text("""
            UPDATE tareas
            SET estado = :estado
            WHERE id = :id
        """)

        result = await self.db.execute(
            query,
            {
                "id": tarea_id,
                "estado": data.estado.value
            }
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Tarea no encontrada"
            )

        await self.db.commit()

        return {
            "message": "Estado actualizado correctamente"
        }

    async def listar_tareas(self):

        query = text("""   
        SELECT
        t.id,
        t.nombre,
        t.descripcion,
        t.fecha_vencimiento,
        t.estado,
        u.id AS responsable_id,
        u.username AS responsable
        FROM tareas t
        INNER JOIN users u
        ON u.id = t.responsable_hizo
        ORDER BY t.id
            """)

        result = await self.db.execute(query)

        return [
            dict(row._mapping)
            for row in result.fetchall()
        ]

    async def listar_tareas_usuario(
        self,
        user_id: int
    ):

        query = text("""
            SELECT
                id,
                nombre,
                descripcion,
                fecha_vencimiento,
                estado
            FROM tareas
            WHERE responsable_hizo = :user_id
            ORDER BY id
        """)

        result = await self.db.execute(
            query,
            {"user_id": user_id}
        )

        return [
            dict(row._mapping)
            for row in result.fetchall()
        ]