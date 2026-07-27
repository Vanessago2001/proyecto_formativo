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
