"""Regresión: los conflictos de interés se declaran desde /conflictos-auditor.

El alta quedó separada del formulario de registro, así que un auditor ya
aprobado puede declarar conflictos en cualquier momento y cada declaración es
un registro nuevo que conserva el enlace con la postulación que leen los
filtros de asignación.
"""

import uuid

import pytest
from fastapi import HTTPException

from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_AUDITOR = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_EMPRESA_A = uuid.UUID("55555555-5555-5555-5555-555555555555")
ID_EMPRESA_B = uuid.UUID("66666666-6666-6666-6666-666666666666")
ID_POSTULACION_APROBADA = uuid.UUID("77777777-7777-7777-7777-777777777777")
ID_POSTULACION_BORRADOR = uuid.UUID("88888888-8888-8888-8888-888888888888")


class SesionConflictos:
    """Doble mínimo de `usuario`, `postulacion_auditor` y `conflicto_interes`."""

    def __init__(self, postulaciones=None, usuario_existe=True):
        self.usuario_existe = usuario_existe
        self.postulaciones = postulaciones if postulaciones is not None else [
            _postulacion(ID_POSTULACION_APROBADA, "Aprobado"),
        ]
        self.conflictos: list[dict] = []
        self.sentencias: list[str] = []
        self.commits = 0

    @property
    def borradores(self) -> list[str]:
        return [sql for sql in self.sentencias if "DELETE FROM conflicto_interes" in sql]

    async def commit(self):
        self.commits += 1

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        parametros = parametros or {}
        self.sentencias.append(sql)

        if "FROM usuario WHERE id_usuario" in sql:
            return ResultadoFalso(
                escalar=str(ID_AUDITOR) if self.usuario_existe else None
            )

        if "FROM postulacion_auditor pa" in sql:
            vinculables = [
                p
                for p in self.postulaciones
                if str(p["id_usuario"]) == str(parametros["id_usuario"])
                and (
                    p["estado"].lower() in ("aprobado", "aprobada")
                    or p["estado"] in ("Borrador", "Correcciones", "Enviado")
                )
            ]
            vinculables.sort(
                key=lambda p: (p["fecha_revision"], p["fecha_postulacion"]),
                reverse=True,
            )
            aprobadas = [
                p
                for p in vinculables
                if p["estado"].lower() in ("aprobado", "aprobada")
            ]
            elegida = aprobadas[0] if aprobadas else (
                vinculables[0] if vinculables else None
            )
            return ResultadoFalso(
                escalar=elegida["id_postulacion"] if elegida else None
            )

        if "INSERT INTO conflicto_interes" in sql:
            fila = {
                "id_conflicto": uuid.uuid4(),
                "id_usuario": parametros["id_usuario"],
                "id_empresa": parametros["id_empresa"],
                "tipo_conflicto": parametros["tipo_conflicto"],
                "descripcion": parametros["descripcion"],
                "bloquea_asignacion": parametros["bloquea_asignacion"],
                "estado": "Activo",
                "id_postulacion": parametros["id_postulacion"],
            }
            self.conflictos.append(fila)
            return ResultadoFalso([{"id_conflicto": fila["id_conflicto"]}])

        if "UPDATE conflicto_interes" in sql:
            for fila in self.conflictos:
                if (
                    str(fila["id_conflicto"]) == str(parametros["id_conflicto"])
                    and str(fila["id_usuario"]) == str(parametros["id_usuario"])
                ):
                    fila["id_empresa"] = parametros["id_empresa"]
                    fila["tipo_conflicto"] = parametros["tipo_conflicto"]
                    fila["descripcion"] = parametros["descripcion"]
                    fila["bloquea_asignacion"] = parametros["bloquea_asignacion"]
                    return ResultadoFalso([{"id_conflicto": fila["id_conflicto"]}])
            return ResultadoFalso([])

        if "DELETE FROM conflicto_interes" in sql:
            if "id_conflicto = :id_conflicto" in sql:
                self.conflictos = [
                    f
                    for f in self.conflictos
                    if str(f["id_conflicto"]) != str(parametros["id_conflicto"])
                ]
            else:
                self.conflictos = []
            return ResultadoFalso([])

        raise AssertionError(f"Consulta no contemplada por el doble: {sql[:120]}")


def _postulacion(id_postulacion, estado, fecha_revision="2026-01-10"):
    return {
        "id_postulacion": id_postulacion,
        "id_usuario": ID_AUDITOR,
        "estado": estado,
        "fecha_revision": fecha_revision,
        "fecha_postulacion": "2026-01-01",
    }


def _conflicto(id_empresa=ID_EMPRESA_A, descripcion="Fui exempleado de esa empresa"):
    return ConflictoInteresCrear(
        id_empresa=id_empresa,
        tipo_conflicto="Exempleado",
        descripcion=descripcion,
    )


async def test_auditor_aprobado_puede_declarar_un_conflicto_tardio():
    """Ya no hay verificación de borrador: el estado del auditor no bloquea la declaración."""
    sesion = SesionConflictos()

    respuesta = await AuditorService(sesion).crear_conflicto(ID_AUDITOR, _conflicto())

    assert respuesta["mensaje"] == "Conflicto de interés registrado correctamente."
    assert len(sesion.conflictos) == 1
    assert sesion.commits == 1


async def test_el_conflicto_se_enlaza_a_la_postulacion_aprobada():
    """Sin enlace a la postulación, los filtros de asignación y de agenda no lo ven."""
    sesion = SesionConflictos(
        postulaciones=[
            _postulacion(ID_POSTULACION_BORRADOR, "Borrador", "2026-02-01"),
            _postulacion(ID_POSTULACION_APROBADA, "Aprobada", "2026-01-10"),
        ]
    )

    await AuditorService(sesion).crear_conflicto(ID_AUDITOR, _conflicto())

    assert sesion.conflictos[0]["id_postulacion"] == ID_POSTULACION_APROBADA
    assert sesion.conflictos[0]["estado"] == "Activo"


async def test_con_el_registro_aun_abierto_se_enlaza_esa_postulacion():
    sesion = SesionConflictos(
        postulaciones=[_postulacion(ID_POSTULACION_BORRADOR, "Correcciones")]
    )

    await AuditorService(sesion).crear_conflicto(ID_AUDITOR, _conflicto())

    assert sesion.conflictos[0]["id_postulacion"] == ID_POSTULACION_BORRADOR


async def test_una_postulacion_no_vinculable_no_impide_la_declaracion():
    sesion = SesionConflictos(postulaciones=[_postulacion(ID_POSTULACION_APROBADA, "Rechazado")])

    await AuditorService(sesion).crear_conflicto(ID_AUDITOR, _conflicto())

    assert sesion.conflictos[0]["id_postulacion"] is None


async def test_cada_declaracion_es_un_registro_nuevo():
    """El segundo conflicto convive con el primero: no se reemplaza lo ya declarado."""
    sesion = SesionConflictos()
    servicio = AuditorService(sesion)

    await servicio.crear_conflicto(ID_AUDITOR, _conflicto())
    await servicio.crear_conflicto(
        ID_AUDITOR,
        _conflicto(id_empresa=ID_EMPRESA_B, descripcion="Mi hermana trabaja allí"),
    )

    assert len(sesion.conflictos) == 2
    assert {str(c["id_empresa"]) for c in sesion.conflictos} == {
        str(ID_EMPRESA_A),
        str(ID_EMPRESA_B),
    }
    assert sesion.borradores == []


async def test_actualizar_un_conflicto_conserva_los_demas():
    sesion = SesionConflictos()
    servicio = AuditorService(sesion)

    await servicio.crear_conflicto(ID_AUDITOR, _conflicto())
    await servicio.crear_conflicto(ID_AUDITOR, _conflicto(id_empresa=ID_EMPRESA_B))
    id_actualizado = sesion.conflictos[1]["id_conflicto"]

    await servicio.actualizar_conflicto(
        ID_AUDITOR,
        id_actualizado,
        ConflictoInteresCrear(
            id_empresa=ID_EMPRESA_B,
            tipo_conflicto="Parentesco",
            descripcion="Parentesco de segundo grado",
        ),
    )

    assert len(sesion.conflictos) == 2
    assert sesion.borradores == []
    actualizado = next(c for c in sesion.conflictos if c["id_conflicto"] == id_actualizado)
    assert actualizado["tipo_conflicto"] == "Parentesco"


async def test_actualizar_un_conflicto_ajeno_devuelve_404():
    sesion = SesionConflictos()
    servicio = AuditorService(sesion)
    await servicio.crear_conflicto(ID_AUDITOR, _conflicto())

    with pytest.raises(HTTPException) as error:
        await servicio.actualizar_conflicto(
            uuid.uuid4(),
            sesion.conflictos[0]["id_conflicto"],
            _conflicto(),
        )

    assert error.value.status_code == 404


async def test_declarar_sobre_un_usuario_inexistente_devuelve_404():
    sesion = SesionConflictos(usuario_existe=False)

    with pytest.raises(HTTPException) as error:
        await AuditorService(sesion).crear_conflicto(ID_AUDITOR, _conflicto())

    assert error.value.status_code == 404
