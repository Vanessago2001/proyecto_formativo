"""
M3 — EMPRESAS · acciones con permiso REQ para el Auxiliar.

Según la hoja "M3 — EMPRESAS", el Auxiliar puede pedir estas acciones pero
necesita que las apruebe un rol con el permiso concedido:

    EMP-006  Cambiar estado de la empresa   -> aprueba ADM o SUPERADM
    EMP-007  Inactivar empresa              -> aprueba ADM o SUPERADM
    EMP-008  Reactivar empresa (SA)         -> aprueba solo SUPERADM
    EMP-023  Eliminar sede                  -> aprueba ADM o SUPERADM
    EMP-029  Eliminar contacto              -> aprueba ADM o SUPERADM

(EMP-010 exportar y EMP-013 eliminar documento también son REQ, pero esas
funciones todavía no existen.)
"""

from modules.aprobaciones.aprobacion_service import registrar_accion
from modules.empresas.empresas_service import EmpresasService

APROBADORES = ["superadmin", "admin"]


def _id_empresa(aprobacion: dict) -> str:
    return str(aprobacion["id_empresa"])


async def _cambiar_estado(db, aprobacion: dict) -> dict:
    return await EmpresasService(db).cambiar_estado(_id_empresa(aprobacion), aprobacion["datos"]["estado"])


async def _inactivar(db, aprobacion: dict) -> dict:
    return await EmpresasService(db).inactivar(_id_empresa(aprobacion))


async def _reactivar(db, aprobacion: dict) -> dict:
    return await EmpresasService(db).reactivar(_id_empresa(aprobacion))


async def _eliminar_sede(db, aprobacion: dict) -> dict:
    servicio = EmpresasService(db)
    await servicio.validar_accion("EMP-023", _id_empresa(aprobacion), aprobacion["datos"])
    return await servicio.delete_sede(_id_empresa(aprobacion), aprobacion["datos"]["id_sede"])


async def _eliminar_contacto(db, aprobacion: dict) -> dict:
    datos = aprobacion["datos"]
    return await EmpresasService(db).delete_contacto(_id_empresa(aprobacion), datos["id_sede"], datos["id_contacto"])


registrar_accion("EMP-006", "Cambiar estado de la empresa", APROBADORES, _cambiar_estado)
registrar_accion("EMP-007", "Inactivar empresa", APROBADORES, _inactivar)
registrar_accion("EMP-008", "Reactivar empresa", ["superadmin"], _reactivar)
registrar_accion("EMP-023", "Eliminar sede", APROBADORES, _eliminar_sede)
registrar_accion("EMP-029", "Eliminar contacto", APROBADORES, _eliminar_contacto)
