"""Activar auditor: postulación vigente aprobada con estado_auditor sin activar.

Caso real (18/11/2026): "Auditor Pruebas" tenía la postulación Aprobado pero
usuario.estado_auditor = 'Postulante', así que no contaba como auditor
aprobado. POST /admin/auditores-registrados/{id}/activar lo activa con motivo.
Base simulada: nunca se toca la base real.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.administrar_auditores import administrar_auditores_service as banco
from modules.auditores_registrados import auditores_registrados_service as servicio
from modules.auditores_registrados.auditores_registrados_router import router
from modules.permisos_auxiliar import permisos_auxiliar_service
from tests.fake_db import ResultadoFalso
from tests.permisos_aux import con_permisos

ID_AUDITOR = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ID_POSTULACION = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
ID_COORDINADOR = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
MOTIVO = "Postulación aprobada el 14/10/2026; el estado quedó en Postulante por error."


class SesionActivacion:
    """Simula usuario + postulación vigente, historial y notificación."""

    def __init__(self, *, rol="Auditor", estado="Activo", estado_auditor="Postulante",
                 estado_postulacion="Aprobado", existe=True):
        self.usuario = {
            "id_usuario": ID_AUDITOR,
            "nombre": "Auditor Pruebas",
            "estado": estado,
            "estado_auditor": estado_auditor,
            "rol": rol,
            "id_postulacion_vigente": ID_POSTULACION if estado_postulacion else None,
            "estado_postulacion_vigente": estado_postulacion,
        }
        self.existe = existe
        self.historial: list[dict] = []
        self.notificaciones: list[dict] = []
        self.sentencias: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.sentencias.append(sql)
        if sql.startswith("SELECT") and "FOR UPDATE OF u" in sql:
            return ResultadoFalso([dict(self.usuario)] if self.existe else [])
        if sql.startswith("UPDATE usuario SET estado_auditor = 'Activo'"):
            if self.usuario["estado_auditor"] == "Activo":
                return ResultadoFalso([])
            self.usuario["estado_auditor"] = "Activo"
            return ResultadoFalso([{"id_usuario": ID_AUDITOR}])
        if sql.startswith("INSERT INTO historial_postulacion_auditor"):
            self.historial.append(dict(params))
            return ResultadoFalso([])
        if sql.startswith("INSERT INTO notificacion"):
            self.notificaciones.append(dict(params))
            return ResultadoFalso([])
        raise AssertionError(f"Consulta no esperada: {sql[:120]}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _cliente(sesion, rol="Coordinador", delegados=()):
    app = FastAPI()
    app.include_router(router)

    async def _db():
        yield sesion

    async def _usuario():
        usuario = {"id_usuario": str(ID_COORDINADOR), "role_name": rol, "estado": "Activo"}
        # Permisos que el Coordinador delegó al Auxiliar (regla_auxiliar).
        return con_permisos(usuario, *delegados) if delegados else usuario

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _usuario
    return TestClient(app)


def _activar(cliente, cuerpo=None):
    return cliente.post(
        f"/admin/auditores-registrados/{ID_AUDITOR}/activar",
        json={"motivo": MOTIVO} if cuerpo is None else cuerpo,
    )


def test_cumple_activa_registra_historial_y_notifica():
    sesion = SesionActivacion()
    respuesta = _activar(_cliente(sesion))

    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["estado_auditor"] == "Activo"
    assert datos["estado_auditor_anterior"] == "Postulante"
    assert datos["estado_registro"] == "Aprobado"
    assert sesion.usuario["estado_auditor"] == "Activo"
    assert sesion.commits == 1

    # Historial de la postulación vigente: quién, cuándo (CURRENT_TIMESTAMP) y motivo.
    assert len(sesion.historial) == 1
    historial = sesion.historial[0]
    assert historial["id_postulacion"] == ID_POSTULACION
    assert historial["id_usuario_administrador"] == ID_COORDINADOR
    assert historial["estado_nuevo"] == "Aprobado"
    assert "Postulante -> Activo" in historial["observaciones"]
    assert MOTIVO in historial["observaciones"]

    assert len(sesion.notificaciones) == 1
    assert sesion.notificaciones[0]["id_usuario"] == ID_AUDITOR
    assert sesion.notificaciones[0]["asunto"] == "Auditor activado"
    assert len(sesion.notificaciones[0]["mensaje"]) <= 255


def test_postulacion_vigente_no_aprobada_devuelve_409():
    sesion = SesionActivacion(estado_postulacion="En Revisión")
    respuesta = _activar(_cliente(sesion))

    assert respuesta.status_code == 409
    assert "no está aprobada" in respuesta.json()["detail"]
    assert sesion.usuario["estado_auditor"] == "Postulante"
    assert not sesion.historial and not sesion.notificaciones and sesion.commits == 0


def test_sin_postulacion_vigente_devuelve_409():
    sesion = SesionActivacion(estado_postulacion=None)
    assert _activar(_cliente(sesion)).status_code == 409


def test_ya_activo_devuelve_409():
    sesion = SesionActivacion(estado_auditor="Activo")
    respuesta = _activar(_cliente(sesion))

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "El auditor ya está activo."
    assert not sesion.historial and sesion.commits == 0


def test_cuenta_inactiva_devuelve_409():
    sesion = SesionActivacion(estado="Inactivo")
    respuesta = _activar(_cliente(sesion))
    assert respuesta.status_code == 409
    assert "cuenta" in respuesta.json()["detail"]


def test_usuario_sin_rol_auditor_devuelve_409():
    sesion = SesionActivacion(rol="Empresa")
    respuesta = _activar(_cliente(sesion))
    assert respuesta.status_code == 409
    assert "rol Auditor" in respuesta.json()["detail"]


def test_usuario_inexistente_devuelve_404():
    sesion = SesionActivacion(existe=False)
    assert _activar(_cliente(sesion)).status_code == 404


@pytest.mark.parametrize("rol", ["Auditor", "Empresa", "Comité"])
def test_rol_sin_permiso_devuelve_403(rol):
    sesion = SesionActivacion()
    respuesta = _activar(_cliente(sesion, rol=rol))
    assert respuesta.status_code == 403
    assert sesion.sentencias == []


def test_auxiliar_sin_permiso_delegado_devuelve_403(monkeypatch):
    async def _sin_permiso(_db, _usuario, codigo, _detalle=None):
        assert codigo == "AUD-013"
        return False

    monkeypatch.setattr(permisos_auxiliar_service, "usar_permiso_delegado", _sin_permiso)
    sesion = SesionActivacion()
    respuesta = _activar(_cliente(sesion, rol="Auxiliar"))
    assert respuesta.status_code == 403
    assert "AUD-013" in respuesta.json()["detail"]
    assert sesion.usuario["estado_auditor"] == "Postulante"


def test_auxiliar_con_permiso_delegado_puede_activar(monkeypatch):
    async def _con_permiso(_db, _usuario, codigo, _detalle=None):
        return codigo == "AUD-013"

    monkeypatch.setattr(permisos_auxiliar_service, "usar_permiso_delegado", _con_permiso)
    sesion = SesionActivacion()
    respuesta = _activar(_cliente(sesion, rol="Auxiliar", delegados=("AUD-013",)))
    assert respuesta.status_code == 200
    assert sesion.usuario["estado_auditor"] == "Activo"


@pytest.mark.parametrize("cuerpo", [{}, {"motivo": ""}, {"motivo": "   corto   "}, {"motivo": None}])
def test_sin_motivo_o_motivo_corto_devuelve_422(cuerpo):
    sesion = SesionActivacion()
    respuesta = _activar(_cliente(sesion), cuerpo)
    assert respuesta.status_code == 422
    assert sesion.sentencias == []


# ----------------------------------------------------------------------
# Insignia "Aprobado, pendiente de activar" (bandera para la pantalla)
# ----------------------------------------------------------------------

def test_requiere_activacion_solo_con_postulacion_aprobada_y_auditor_sin_activar():
    assert servicio.requiere_activacion("Auditor", "Activo", "Postulante", "Aprobado")
    assert servicio.requiere_activacion("auditor", "Activo", None, "Aprobada")
    assert not servicio.requiere_activacion("Auditor", "Activo", "Activo", "Aprobado")
    assert not servicio.requiere_activacion("Auditor", "Inactivo", "Postulante", "Aprobado")
    assert not servicio.requiere_activacion("Auditor", "Activo", "Postulante", "Rechazado")
    assert not servicio.requiere_activacion("Auditor", "Activo", "Postulante", None)
    assert not servicio.requiere_activacion("Empresa", "Activo", "Postulante", "Aprobado")


def test_banco_marca_pendiente_solo_en_la_postulacion_vigente():
    base = {
        "id_postulacion": ID_POSTULACION,
        "id_postulacion_vigente": ID_POSTULACION,
        "rol": "Auditor",
        "estado_usuario": "Activo",
        "estado_auditor": "Postulante",
        "estado_postulacion": "Aprobado",
    }
    assert banco._pendiente_activacion(base) is True
    assert banco._pendiente_activacion({**base, "id_postulacion_vigente": uuid.uuid4()}) is False
    assert banco._pendiente_activacion({**base, "estado_auditor": "Activo"}) is False
    # Respuestas simuladas antiguas sin la columna nueva no deben romper.
    sin_columna = {k: v for k, v in base.items() if k != "id_postulacion_vigente"}
    assert banco._pendiente_activacion(sin_columna) is False
