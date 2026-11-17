from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user


# Roles que pueden gestionar el banco de auditores y solicitudes de postulación.
# Se incluyen las variantes en español para coincidir con los roles reales
# de la base de datos (Coordinador, antes Administrador, y Auxiliar).
ROLES_PERMITIDOS_LOGS = {
    "coordinador",
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

# ============================================================
# AUDITOR APROBADO
#
# Pedido de la usuaria (17/11/2026): "Si el auditor está en revisión o no está
# aprobado como auditor, no se le debe permitir ver el resto de acciones o
# módulos a los que los auditores tienen acceso, solo a su proceso mientras se
# le aprueba."
#
# Regla de "aprobado": la misma que usa la asignación de auditores
# (CTE_AUDITORES en modules/asignacion_auditores/asignacion_service.py):
#   · tiene una postulación en estado Aprobado/Aprobada, y
#   · usuario.estado = 'Activo' y usuario.estado_auditor = 'Activo'.
#
# Su proceso (formulario de registro, estado del registro, notificaciones,
# perfil) sigue abierto; los módulos de auditor aprobado usan
# `require_auditor_aprobado`, que solo actúa si el rol de la sesión es Auditor.
# ============================================================

MENSAJE_AUDITOR_NO_APROBADO = "Tu registro como auditor aún no está aprobado"


def es_rol_auditor(usuario: dict) -> bool:
    """Rol Auditor exacto (no 'Administrar auditores' ni otros)."""
    return _normalize_role_name(usuario.get("role_name") or usuario.get("rol") or "") == "auditor"


async def consultar_acceso_auditor(db: AsyncSession, id_usuario) -> dict:
    """Estado de aprobación del auditor (solo lectura)."""
    resultado = await db.execute(
        text("""
            SELECT
                u.estado,
                u.estado_auditor,
                (
                    SELECT pa.estado
                    FROM postulacion_auditor pa
                    WHERE pa.id_usuario = u.id_usuario
                    ORDER BY pa.fecha_postulacion DESC NULLS LAST
                    LIMIT 1
                ) AS estado_postulacion,
                EXISTS (
                    SELECT 1
                    FROM postulacion_auditor pa
                    WHERE pa.id_usuario = u.id_usuario
                      AND LOWER(pa.estado) IN ('aprobado', 'aprobada')
                ) AS tiene_postulacion_aprobada
            FROM usuario u
            WHERE u.id_usuario = :id_usuario
        """),
        {"id_usuario": str(id_usuario)},
    )
    fila = resultado.mappings().first()
    if not fila:
        return {"aprobado": False, "estado_postulacion": None, "estado_auditor": None}
    aprobado = (
        bool(fila["tiene_postulacion_aprobada"])
        and fila["estado"] == "Activo"
        and fila["estado_auditor"] == "Activo"
    )
    return {
        "aprobado": aprobado,
        "estado_postulacion": fila["estado_postulacion"],
        "estado_auditor": fila["estado_auditor"],
    }


async def require_auditor_aprobado(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """403 para un Auditor cuyo registro aún no está aprobado.

    Los demás roles (Coordinador, Auxiliar, Comité, Empresa) pasan sin
    consulta: la regla es solo para el rol Auditor.
    """
    if not es_rol_auditor(current_user):
        return current_user
    acceso = await consultar_acceso_auditor(db, current_user.get("id_usuario"))
    if not acceso.get("aprobado"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MENSAJE_AUDITOR_NO_APROBADO,
        )
    return current_user
