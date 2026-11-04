from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from modules.auditores.auditor_service import AuditorService


class ConflictoAuditorService(AuditorService):
    async def listar_por_usuario(self, id_usuario: UUID):
        return await self.listar_conflictos(id_usuario)

    async def eliminar(self, id_usuario: UUID, id_conflicto: UUID):
        return await self.eliminar_conflicto(id_usuario, id_conflicto)

    async def empresas_restringidas(self):
        return await self.consultar_empresas_restringidas()

    async def validar_antes_asignacion(self, id_usuario: UUID, id_empresa: UUID):
        return await self.validar_conflicto_antes_asignacion(id_usuario, id_empresa)

    async def validar_antes_asignacion_por_nit(self, id_usuario: UUID, nit_empresa: str):
        result = await self.db.execute(
            text("SELECT id_empresa FROM empresa WHERE nit = :nit"),
            {"nit": nit_empresa.strip()},
        )
        id_empresa = result.scalar()
        if not id_empresa:
            raise HTTPException(status_code=404, detail="No se encontró empresa con ese NIT.")
        return await self.validar_conflicto_antes_asignacion(id_usuario, id_empresa)
