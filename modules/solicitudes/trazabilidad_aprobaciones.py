"""
M5 — GESTIÓN DE SOLICITUDES · acciones REQ del Bloque 6.

    SOL-054  Cambiar estado de la solicitud  -> aprueba ADM o SUPERADM
    SOL-058  Compartir expediente con Comité -> aprueba ADM o SUPERADM
    SOL-060  Cerrar solicitud definitivamente-> aprueba ADM o SUPERADM

SOL-056 (exportar historial) y SOL-059 (reporte del módulo) también están
marcadas REQ, pero solo leen: no cambian nada que haya que aprobar, así que
se resuelven en el momento, como indica el propio catálogo de permisos
("REQ se trata como concedido a nivel de endpoint").
"""

from uuid import UUID

from modules.aprobaciones.aprobacion_service import registrar_accion

APROBADORES = ["superadmin", "admin"]


def _id_solicitud(aprobacion: dict) -> UUID:
    return UUID(str(aprobacion["datos"]["id_solicitud"]))


def _autor(aprobacion: dict, codigo: str) -> dict:
    return {
        "id_usuario": aprobacion.get("id_revisor") or aprobacion.get("id_solicitante"),
        "role_name": "Administrador",
        "permiso_codigo": codigo,
    }


async def _cambiar_estado(db, aprobacion: dict) -> dict:
    from modules.solicitudes.trazabilidad_service import TrazabilidadService

    datos = aprobacion["datos"]
    return await TrazabilidadService(db).cambiar_estado(
        _id_solicitud(aprobacion), datos["estado"], datos.get("motivo"),
        _autor(aprobacion, "SOL-054"),
    )


async def _compartir_con_comite(db, aprobacion: dict) -> dict:
    from modules.solicitudes.trazabilidad_service import TrazabilidadService

    return await TrazabilidadService(db).compartir_con_comite(
        _id_solicitud(aprobacion), _autor(aprobacion, "SOL-058")
    )


async def _cerrar(db, aprobacion: dict) -> dict:
    from modules.solicitudes.trazabilidad_service import TrazabilidadService

    return await TrazabilidadService(db).cerrar(
        _id_solicitud(aprobacion), aprobacion["datos"]["motivo"], _autor(aprobacion, "SOL-060")
    )


registrar_accion("SOL-054", "Cambiar estado de la solicitud", APROBADORES, _cambiar_estado)
registrar_accion("SOL-058", "Compartir expediente con el Comité", APROBADORES, _compartir_con_comite)
registrar_accion("SOL-060", "Cerrar solicitud definitivamente", APROBADORES, _cerrar)
