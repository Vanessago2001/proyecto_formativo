from fastapi import Depends, HTTPException, status
from core.security import get_current_user


ROLES_PERMITIDOS_LOGS = {
    "superadmin",
    "admin",
    "auxiliar",
}


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