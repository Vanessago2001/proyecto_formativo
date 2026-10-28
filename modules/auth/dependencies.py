from uuid import UUID

from fastapi import Depends, HTTPException, status
from core.security import get_current_user


# Roles que pueden gestionar el banco de auditores y solicitudes de postulación.
# Se incluyen las variantes en español para coincidir con los roles reales
# de la base de datos (Administrador, Super Administrador, etc.).
ROLES_PERMITIDOS_LOGS = {
    "superadmin",
    "super administrador",
    "admin",
    "administrador",
    "auxiliar",
}


def es_rol_administrativo(usuario: dict) -> bool:
    rol = (usuario.get("role_name") or "").strip().lower()
    return rol in ROLES_PERMITIDOS_LOGS


async def require_self_or_admin(
    id_usuario: UUID,
    current_user: dict = Depends(get_current_user),
) -> dict:
    if es_rol_administrativo(current_user):
        return current_user

    if str(id_usuario) != str(current_user.get("id_usuario")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para acceder a los datos de otro usuario.",
        )

    return current_user


async def require_admin_access(
    current_user=Depends(get_current_user),
):

    rol = (
        current_user.get("role_name")
        or ""
    ).lower()

    if rol not in ROLES_PERMITIDOS_LOGS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para visualizar el historial de accesos.",
        )

    return current_user