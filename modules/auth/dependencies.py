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


def es_rol_administrativo(usuario: dict, *codigos: str) -> bool:
    """
    Coordinador: siempre. Auxiliar: solo si el Coordinador le delegó al menos
    uno de `codigos` (sin códigos, nunca: no tiene permisos propios; ver
    modules/permisos_auxiliar/regla_auxiliar.py).
    """
    rol = (usuario.get("role_name") or "").strip().lower()
    if rol not in ROLES_PERMITIDOS_LOGS:
        return False
    if _normalize_role_name(rol) == "auxiliar":
        from modules.permisos_auxiliar.regla_auxiliar import tiene_delegado

        return bool(codigos) and tiene_delegado(usuario, *codigos)
    return True


def _exigir_propio(id_usuario, current_user: dict) -> dict:
    if str(id_usuario) != str(current_user.get("id_usuario")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para acceder a los datos de otro usuario.",
        )
    return current_user


def _error_auxiliar(current_user: dict, codigos: tuple[str, ...]) -> None:
    """403 claro para el Auxiliar sin el permiso delegado."""
    from modules.permisos_auxiliar.regla_auxiliar import exigir_permiso_auxiliar

    exigir_permiso_auxiliar(current_user, *codigos)


async def require_self_or_admin(
    id_usuario: UUID,
    current_user: dict = Depends(get_current_user),
) -> dict:
    if es_rol_administrativo(current_user):
        return current_user
    return _exigir_propio(id_usuario, current_user)


def require_self_or_admin_con(*codigos: str):
    """Como `require_self_or_admin`; el Auxiliar entra con alguno de `codigos`."""

    async def dependencia(
        id_usuario: UUID,
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        if es_rol_administrativo(current_user, *codigos):
            return current_user
        if str(id_usuario) != str(current_user.get("id_usuario")):
            _error_auxiliar(current_user, codigos)
        return _exigir_propio(id_usuario, current_user)

    return dependencia


def _exigir_acceso_administrativo(current_user: dict, codigos: tuple[str, ...]) -> dict:
    rol = (current_user.get("role_name") or "").lower()
    if rol not in ROLES_PERMITIDOS_LOGS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para visualizar el historial de accesos.",
        )
    _error_auxiliar(current_user, codigos)
    return current_user


async def require_admin_access(
    current_user=Depends(get_current_user),
):
    """Coordinador. El Auxiliar no pasa sin código: usar `require_admin_access_con`."""
    return _exigir_acceso_administrativo(current_user, ())


def require_admin_access_con(*codigos: str):
    """Coordinador; el Auxiliar con alguno de `codigos` delegado."""

    async def dependencia(current_user=Depends(get_current_user)):
        return _exigir_acceso_administrativo(current_user, codigos)

    return dependencia

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


# ------------------------------------------------------------------
# Solicitudes visibles para un Auditor (QA 18/11/2026: con rol Auditor la
# API devolvía todas las solicitudes y certificados, incluso borradores).
# Regla: el auditor APROBADO solo ve las solicitudes en las que está
# asignado (auditores_solicitud con asignación no cancelada, reasignada ni
# rechazada) y los certificados de esas solicitudes; el auditor NO aprobado
# recibe el mismo 403 de `require_auditor_aprobado`. Los demás roles no
# cambian.
# ------------------------------------------------------------------
ESTADOS_ASIGNACION_SIN_ACCESO = (
    "CANCELADA", "CANCELADO", "REASIGNADA", "REASIGNADO", "RECHAZADA", "RECHAZADO",
)


def sql_auditor_asignado(columna_solicitud: str, parametro: str = "aud_usuario") -> str:
    """EXISTS: el auditor `:parametro` tiene asignación vigente en la solicitud."""
    sin_acceso = ", ".join(f"'{e}'" for e in ESTADOS_ASIGNACION_SIN_ACCESO)
    return (
        "EXISTS (SELECT 1 FROM auditores_solicitud aud_a"
        f" WHERE aud_a.id_solicitud = {columna_solicitud}"
        f" AND aud_a.id_auditor::TEXT = :{parametro}"
        f" AND UPPER(TRIM(COALESCE(aud_a.estado_asignacion, ''))) NOT IN ({sin_acceso}))"
    )


async def exigir_auditor_aprobado(db: AsyncSession, usuario: dict) -> None:
    """403 (mismo mensaje que `require_auditor_aprobado`) si no está aprobado."""
    acceso = await consultar_acceso_auditor(db, usuario.get("id_usuario"))
    if not acceso.get("aprobado"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=MENSAJE_AUDITOR_NO_APROBADO,
        )


async def filtro_auditor_asignado(
    db: AsyncSession,
    usuario: dict,
    columna_solicitud: str,
    params: dict,
) -> str:
    """
    Condición SQL (sin "AND") que limita un listado a las solicitudes
    asignadas al Auditor de la sesión; "" para cualquier otro rol.
    403 si el auditor aún no está aprobado.
    """
    if not es_rol_auditor(usuario or {}):
        return ""
    await exigir_auditor_aprobado(db, usuario)
    params["aud_usuario"] = str(usuario.get("id_usuario") or "")
    return sql_auditor_asignado(columna_solicitud, "aud_usuario")


async def exigir_auditor_asignado(db: AsyncSession, usuario: dict, id_solicitud, detalle: str) -> None:
    """Para lecturas de detalle: 404 si el Auditor no está asignado a la solicitud."""
    if not es_rol_auditor(usuario or {}):
        return
    await exigir_auditor_aprobado(db, usuario)
    resultado = await db.execute(
        text(f"SELECT {sql_auditor_asignado('CAST(:aud_solicitud AS UUID)')} AS auditor_asignado;"),
        {"aud_solicitud": str(id_solicitud), "aud_usuario": str(usuario.get("id_usuario") or "")},
    )
    fila = resultado.mappings().first()
    if not fila or not fila.get("auditor_asignado"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)
