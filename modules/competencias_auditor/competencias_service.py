from uuid import UUID

from modules.auditores.auditor_service import AuditorService


class CompetenciaAuditorService(AuditorService):
    async def consultar_catalogo(self):
        return await self.consultar_catalogo_competencias()

    async def consultar_sectores_iaf(self):
        return await self.consultar_sectores_iaf()

    async def consultar_historial_academico(self, id_usuario: UUID):
        return await self.consultar_historial_academico(id_usuario)
