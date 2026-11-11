"""
M5 — GESTIÓN DE SOLICITUDES · acciones con permiso REQ en los Bloques 5 a 7.

La hoja marca REQ cuando el rol puede pedir la acción pero necesita que la
apruebe un superior. Quien aprueba sale de la misma hoja:

    SOL-048  Aprobar asignación de auditor  -> aprueba el Coordinador
    SOL-049  Reasignar auditor (SA)         -> aprueba el Coordinador (era SA)
    SOL-050  Cancelar asignación            -> aprueba el Coordinador
    SOL-054  Cambiar estado de solicitud    -> aprueba el Coordinador
    SOL-060  Cerrar solicitud               -> aprueba el Coordinador
    SOL-063  Recalcular tiempo de auditoría -> aprueba el Coordinador
    SOL-065  Justificar ajustes de tiempo   -> aprueba el Coordinador (era SA)

Cuando el superior aprueba, se ejecuta aquí la misma operación que habría
hecho el solicitante, con su propio usuario como autor del cambio.
"""

from uuid import UUID

from modules.aprobaciones.aprobacion_service import registrar_accion

APROBADORES = ["admin"]
# Lo que antes aprobaba solo el Super Administrador (retirado) lo aprueba el Coordinador.
SOLO_COORDINADOR = ["admin"]


def _id_solicitud(aprobacion: dict) -> UUID:
    return UUID(str(aprobacion["datos"]["id_solicitud"]))


def _autor(aprobacion: dict, codigo: str) -> dict:
    """Quien aprueba queda como autor del cambio, con el permiso aplicado."""
    return {
        "id_usuario": aprobacion.get("id_revisor") or aprobacion.get("id_solicitante"),
        "role_name": "Coordinador",
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
registrar_accion("SOL-049", "Reasignar auditor", SOLO_COORDINADOR, _reasignar_auditor)
registrar_accion("SOL-050", "Cancelar asignación de auditor", APROBADORES, _cancelar_asignacion)
