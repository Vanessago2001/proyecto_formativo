"""
M5 — GESTIÓN DE SOLICITUDES · acciones REQ del Bloque 7.

    SOL-063  Recalcular tiempo de auditoría -> aprueba ADM o SUPERADM
    SOL-065  Justificar ajustes de tiempo   -> aprueba solo SUPERADM

SOL-065 es SA para el Administrador en la hoja, así que un ajuste pedido por
el Auxiliar solo lo puede confirmar el SuperAdministrador.
"""

from uuid import UUID

from modules.aprobaciones.aprobacion_service import registrar_accion

APROBADORES = ["superadmin", "admin"]
SOLO_SUPERADMIN = ["superadmin"]


def _id_solicitud(aprobacion: dict) -> UUID:
    return UUID(str(aprobacion["datos"]["id_solicitud"]))


def _autor(aprobacion: dict, codigo: str) -> dict:
    return {
        "id_usuario": aprobacion.get("id_revisor") or aprobacion.get("id_solicitante"),
        "role_name": "Administrador",
        "permiso_codigo": codigo,
    }


async def _recalcular(db, aprobacion: dict) -> dict:
    from modules.solicitudes.calculo_service import CalculoAuditoriaService

    return await CalculoAuditoriaService(db).calcular(
        _id_solicitud(aprobacion),
        aprobacion["datos"].get("variables") or {},
        _autor(aprobacion, "SOL-063"),
        recalculo=True,
    )


async def _ajustar(db, aprobacion: dict) -> dict:
    from modules.solicitudes.calculo_service import CalculoAuditoriaService

    datos = aprobacion["datos"]
    return await CalculoAuditoriaService(db).ajustar(
        _id_solicitud(aprobacion), datos["horas"], datos["justificacion"],
        _autor(aprobacion, "SOL-065"),
    )


registrar_accion("SOL-063", "Recalcular el tiempo de auditoría", APROBADORES, _recalcular)
registrar_accion("SOL-065", "Justificar un ajuste de tiempo", SOLO_SUPERADMIN, _ajustar)
