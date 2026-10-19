from uuid import UUID

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
