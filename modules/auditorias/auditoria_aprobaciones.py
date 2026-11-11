"""
M7 — AUDITORÍAS · acciones con permiso REQ.

De los seis permisos marcados REQ en la hoja, tres cambian algo y por eso
pasan por aprobación:

    AUT-010  Suspender auditoría por anomalía -> aprueba el Coordinador (era SA)
    AUT-014  Registrar requisito de control   -> aprueba el Coordinador
    AUT-057  Cerrar auditoría formalmente     -> aprueba el Coordinador

Los otros tres (AUT-039 exportar evidencias, AUT-060 exportar estadísticas y
AUT-070 consultar el expediente para votación) solo leen, así que se
resuelven en el momento, como dice el catálogo de permisos.
"""

from uuid import UUID

from modules.aprobaciones.aprobacion_service import registrar_accion

APROBADORES = ["admin"]
# Lo que antes aprobaba solo el Super Administrador (retirado) lo aprueba el Coordinador.
SOLO_COORDINADOR = ["admin"]


def _id_auditoria(aprobacion: dict) -> UUID:
    return UUID(str(aprobacion["datos"]["id_auditoria"]))


def _autor(aprobacion: dict, codigo: str) -> dict:
    return {
        "id_usuario": aprobacion.get("id_revisor") or aprobacion.get("id_solicitante"),
        "role_name": "Coordinador",
        "permiso_codigo": codigo,
    }


async def _suspender(db, aprobacion: dict) -> dict:
    from modules.auditorias.auditoria_service import AuditoriaService

    return await AuditoriaService(db).suspender(
        _id_auditoria(aprobacion), aprobacion["datos"]["motivo"], _autor(aprobacion, "AUT-010")
    )


async def _registrar_requisito(db, aprobacion: dict) -> dict:
    from modules.auditorias.evaluacion_service import EvaluacionService

    datos = aprobacion["datos"]
    return await EvaluacionService(db).registrar_requisito(
        _id_auditoria(aprobacion), datos["numeral"], datos["descripcion"],
        _autor(aprobacion, "AUT-014"),
    )


async def _cerrar(db, aprobacion: dict) -> dict:
    from modules.auditorias.seguimiento_service import SeguimientoService

    return await SeguimientoService(db).cerrar(
        _id_auditoria(aprobacion), aprobacion["datos"]["observaciones"],
        _autor(aprobacion, "AUT-057"),
    )


registrar_accion("AUT-010", "Suspender la auditoría por anomalía", SOLO_COORDINADOR, _suspender)
registrar_accion("AUT-014", "Registrar un requisito de control", APROBADORES, _registrar_requisito)
registrar_accion("AUT-057", "Cerrar la auditoría formalmente", APROBADORES, _cerrar)
