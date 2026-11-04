from uuid import UUID

from modules.auditores.auditor_service import AuditorService


class ConflictoPolicyService(AuditorService):
    async def debe_bloquear_asignacion(
        self,
        id_usuario: UUID,
        id_empresa: UUID,
    ):
        resultado = await self.validar_conflicto_antes_asignacion(
            id_usuario=id_usuario,
            id_empresa=id_empresa,
        )
        return bool(resultado.get("tiene_conflicto"))
