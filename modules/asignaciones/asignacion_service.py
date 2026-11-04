from uuid import UUID

from modules.auditores.auditor_service import AuditorService


class AsignacionService(AuditorService):
    async def validar_auditor_para_asignacion(
        self,
        id_usuario: UUID,
        id_empresa: UUID,
    ):
        conflictos = await self.validar_conflicto_antes_asignacion(
            id_usuario=id_usuario,
            id_empresa=id_empresa,
        )
        return {
            "asignable": not conflictos.get("tiene_conflicto", False),
            **conflictos,
        }
