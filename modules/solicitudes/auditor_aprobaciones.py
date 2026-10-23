"""
M5 — GESTIÓN DE SOLICITUDES · acciones con permiso REQ en los Bloques 5 a 7.

La hoja marca REQ cuando el rol puede pedir la acción pero necesita que la
apruebe un superior. Quien aprueba sale de la misma hoja:

    SOL-048  Aprobar asignación de auditor  -> aprueba ADM o SUPERADM
    SOL-049  Reasignar auditor (SA)         -> aprueba solo SUPERADM
    SOL-050  Cancelar asignación            -> aprueba ADM o SUPERADM
    SOL-054  Cambiar estado de solicitud    -> aprueba ADM o SUPERADM
    SOL-060  Cerrar solicitud               -> aprueba ADM o SUPERADM
    SOL-063  Recalcular tiempo de auditoría -> aprueba ADM o SUPERADM
    SOL-065  Justificar ajustes de tiempo   -> aprueba solo SUPERADM

Cuando el superior aprueba, se ejecuta aquí la misma operación que habría
hecho el solicitante, con su propio usuario como autor del cambio.
"""

from uuid import UUID

from modules.aprobaciones.aprobacion_service import registrar_accion

APROBADORES = ["superadmin", "admin"]
SOLO_SUPERADMIN = ["superadmin"]


def _id_solicitud(aprobacion: dict) -> UUID:
    return UUID(str(aprobacion["datos"]["id_solicitud"]))


def _autor(aprobacion: dict, codigo: str) -> dict:
    """Quien aprueba queda como autor del cambio, con el permiso aplicado."""
    return {
        "id_usuario": aprobacion.get("id_revisor") or aprobacion.get("id_solicitante"),
        "role_name": "Administrador",
        "permiso_codigo": codigo,
    }


async def _aprobar_asignacion(db, aprobacion: dict) -> dict:
    from modules.solicitudes.auditor_service import AuditorSolicitudService

    datos = aprobacion["datos"]
    return await AuditorSolicitudService(db).aprobar(
        _id_solicitud(aprobacion), UUID(str(datos["id_asignacion"])), _autor(aprobacion, "SOL-048")
    )


async def _reasignar_auditor(db, aprobacion: dict) -> dict:
    from modules.solicitudes.auditor_service import AuditorSolicitudService

    datos = aprobacion["datos"]
    return await AuditorSolicitudService(db).reasignar(
        _id_solicitud(aprobacion),
        UUID(str(datos["id_asignacion"])),
        UUID(str(datos["id_nuevo_auditor"])),
        datos["motivo"],
        _autor(aprobacion, "SOL-049"),
    )


async def _cancelar_asignacion(db, aprobacion: dict) -> dict:
    from modules.solicitudes.auditor_service import AuditorSolicitudService

    datos = aprobacion["datos"]
    return await AuditorSolicitudService(db).cancelar(
        _id_solicitud(aprobacion),
        UUID(str(datos["id_asignacion"])),
        datos["motivo"],
        _autor(aprobacion, "SOL-050"),
    )


registrar_accion("SOL-048", "Aprobar asignación de auditor", APROBADORES, _aprobar_asignacion)
registrar_accion("SOL-049", "Reasignar auditor", SOLO_SUPERADMIN, _reasignar_auditor)
registrar_accion("SOL-050", "Cancelar asignación de auditor", APROBADORES, _cancelar_asignacion)
