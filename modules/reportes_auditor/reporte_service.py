from uuid import UUID

from modules.auditores.auditor_service import AuditorService


class ReporteAuditorService(AuditorService):
    async def reporte_conflictos(self):
        return await self.consultar_empresas_restringidas()

    async def reporte_historial_academico(self, id_usuario: UUID):
        return await self.consultar_historial_academico(id_usuario)
