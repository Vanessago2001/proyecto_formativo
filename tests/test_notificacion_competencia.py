"""Regresión de la revisión de competencias, comparada con la de documentos.

Rechazar una competencia tiene que producir las mismas acciones que rechazar un
documento: marcar la postulación propia en 'Correcciones', devolver al auditor a
'Postulante', dejar la observación visible en el panel y avisar al auditor por su
buzón. También comparte las guardas: competencia inexistente (404), competencia ya
aprobada (409) y rechazo sin observación (400).
"""

import uuid

import pytest
from fastapi import HTTPException

from modules.administrar_auditores.administrar_auditores_service import (
    AdministrarAuditoresService,
)
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_PROPIA = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_OTRA = uuid.UUID("33333333-3333-3333-3333-333333333333")
ID_ACTOR = uuid.UUID("44444444-4444-4444-4444-444444444444")


def competencia(estado: str = "Pendiente", id_postulacion=ID_PROPIA) -> dict:
    return {
        "id_competencia": uuid.uuid4(),
        "id_usuario": ID_USUARIO,
        "id_postulacion": id_postulacion,
        "tipo_competencia": "Norma ISO",
        "estado_validacion": estado,
        "observacion_validacion": None,
    }


class SesionRevision:
    """Doble de las tablas que toca `revisar_validacion_competencia`."""

    def __init__(self, fila: dict | None, postulaciones: dict | None = None):
        self.fila = fila
        self.postulaciones = postulaciones or {
            str(ID_PROPIA): {"estado": "Enviado"},
            str(ID_OTRA): {"estado": "Aprobado"},
        }
        self.estado_auditor = "Activo"
        self.notificaciones: list[dict] = []
        self.commitido = False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}

        if sql.startswith("INSERT INTO notificacion"):
            self.notificaciones.append(dict(params))
            return ResultadoFalso()

        if sql.startswith("UPDATE competencia_auditor"):
            if self.fila is None:
                return ResultadoFalso([])
            self.fila["estado_validacion"] = params["estado_validacion"]
            self.fila["observacion_validacion"] = params["observacion"]
            return ResultadoFalso([dict(self.fila)])

        if sql.startswith("UPDATE postulacion_auditor"):
            id_postulacion = str(params["id_postulacion"]) if params["id_postulacion"] else None
            if id_postulacion in self.postulaciones:
                if self.postulaciones[id_postulacion]["estado"] not in (
                    "Aprobado",
                    "Rechazado",
                    "Cancelado",
                ):
                    self.postulaciones[id_postulacion]["estado"] = "Correcciones"
            return ResultadoFalso()

        if sql.startswith("UPDATE usuario"):
            self.estado_auditor = "Postulante"
            return ResultadoFalso()

        if "FROM competencia_auditor" in sql:
            return ResultadoFalso([dict(self.fila)] if self.fila else [])

        if "FROM postulacion_auditor" in sql:
            activa = next(
                (
                    {"id_postulacion": uuid.UUID(id_postulacion)}
                    for id_postulacion, datos in self.postulaciones.items()
                    if datos["estado"] in ("Borrador", "Correcciones", "Enviado", "En Revisión")
                ),
                None,
            )
            return ResultadoFalso([activa] if activa else [])

        raise AssertionError(f"Consulta no contemplada por el doble: {sql[:120]}")

    async def commit(self):
        self.commitido = True


async def revisar(
    sesion: SesionRevision,
    estado: str,
    observacion: str | None = None,
):
    return await AdministrarAuditoresService(sesion).revisar_validacion_competencia(
        id_competencia=uuid.uuid4(),
        estado_validacion=estado,
        observacion=observacion,
        id_usuario_actor=ID_ACTOR,
    )


async def test_el_rechazo_notifica_al_auditor_con_su_observacion():
    sesion = SesionRevision(competencia())

    await revisar(sesion, "Rechazado", "Falta el soporte de la norma")

    assert len(sesion.notificaciones) == 1
    aviso = sesion.notificaciones[0]
    assert aviso["id_usuario"] == ID_USUARIO
    assert aviso["asunto"] == "Competencia rechazada"
    assert "Norma ISO" in aviso["mensaje"]
    assert "Falta el soporte de la norma" in aviso["mensaje"]
    assert sesion.commitido is True


async def test_el_rechazo_devuelve_la_postulacion_y_el_auditor():
    """Las mismas dos acciones que ejecuta el rechazo de un documento."""
    sesion = SesionRevision(competencia())

    await revisar(sesion, "Rechazado", "Falta el soporte")

    assert sesion.postulaciones[str(ID_PROPIA)]["estado"] == "Correcciones"
    assert sesion.estado_auditor == "Postulante"


async def test_la_devolucion_afecta_a_la_postulacion_propia():
    """Una competencia de una postulación antigua no puede devolver la vigente."""
    sesion = SesionRevision(
        competencia(id_postulacion=ID_OTRA),
        postulaciones={
            str(ID_PROPIA): {"estado": "Enviado"},
            str(ID_OTRA): {"estado": "En Revisión"},
        },
    )

    await revisar(sesion, "Rechazado", "Observacion")

    assert sesion.postulaciones[str(ID_OTRA)]["estado"] == "Correcciones"
    assert sesion.postulaciones[str(ID_PROPIA)]["estado"] == "Enviado"


async def test_sin_postulacion_propia_se_usa_la_activa():
    """Las filas antiguas no guardan id_postulacion; se resuelve la activa."""
    sesion = SesionRevision(
        competencia(id_postulacion=None),
        postulaciones={
            str(ID_OTRA): {"estado": "Aprobado"},
            str(ID_PROPIA): {"estado": "Enviado"},
        },
    )

    await revisar(sesion, "Rechazado", "Observacion")

    assert sesion.postulaciones[str(ID_PROPIA)]["estado"] == "Correcciones"
    assert len(sesion.notificaciones) == 1


async def test_la_aprobacion_tambien_notifica_y_confirma():
    """El panel envia 'Aprobado' y se guarda 'Validado', como en el resto del flujo."""
    sesion = SesionRevision(competencia())

    respuesta = await revisar(sesion, "Aprobado")

    assert sesion.fila["estado_validacion"] == "Validado"
    assert sesion.notificaciones[0]["asunto"] == "Competencia aprobada"
    assert "rechazada" not in sesion.notificaciones[0]["mensaje"]
    assert respuesta["competencia"]["estado_validacion"] == "Validado"


async def test_la_competencia_aprobada_no_vuelve_a_modificarse():
    """Misma guarda que los documentos: la aprobación es definitiva."""
    sesion = SesionRevision(competencia(estado="Validado"))

    with pytest.raises(HTTPException) as error:
        await revisar(sesion, "Rechazado", "Observacion")

    assert error.value.status_code == 409
    assert sesion.notificaciones == []
    assert sesion.commitido is False


async def test_una_competencia_que_no_existe_no_hace_nada():
    sesion = SesionRevision(None)

    with pytest.raises(HTTPException) as error:
        await revisar(sesion, "Rechazado", "Observacion")

    assert error.value.status_code == 404
    assert sesion.notificaciones == []
    assert sesion.postulaciones[str(ID_PROPIA)]["estado"] == "Enviado"


async def test_rechazar_sin_observacion_no_notifica():
    sesion = SesionRevision(competencia())

    with pytest.raises(HTTPException) as error:
        await revisar(sesion, "Rechazado")

    assert error.value.status_code == 400
    assert sesion.notificaciones == []
    assert sesion.commitido is False


async def test_devolver_a_pendiente_no_notifica():
    """Quitar la revisión no es una decisión que el auditor deba recibir."""
    sesion = SesionRevision(competencia(estado="Rechazado"))

    await revisar(sesion, "Pendiente")

    assert sesion.notificaciones == []
    assert sesion.postulaciones[str(ID_PROPIA)]["estado"] == "Enviado"
