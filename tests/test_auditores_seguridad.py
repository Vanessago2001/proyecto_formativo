"""Regresión: el módulo de auditores exige autenticación y propiedad de los datos."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.auditores.auditor_router import public_router, router
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_AUDITOR = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_OTRO_AUDITOR = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_POSTULACION = uuid.UUID("33333333-3333-3333-3333-333333333333")
ID_CONFLICTO = uuid.UUID("44444444-4444-4444-4444-444444444444")


class SesionAuditores:
    """Solo responde a la consulta de propiedad de postulaciones."""

    def __init__(self, dueno_postulacion: uuid.UUID | None = ID_AUDITOR):
        self.dueno_postulacion = dueno_postulacion

    async def execute(self, statement, params=None):
        if "FROM postulacion_auditor" in str(statement):
            parametros = params or {}
            if (
                str(parametros.get("id_postulacion")) == str(ID_POSTULACION)
                and str(parametros.get("id_usuario")) == str(self.dueno_postulacion)
            ):
                return ResultadoFalso([{"1": 1}])
            return ResultadoFalso([])
        return ResultadoFalso([])

    async def commit(self):
        return None


@pytest.fixture
def sesion():
    return SesionAuditores()


@pytest.fixture
def app(sesion) -> FastAPI:
    aplicacion = FastAPI()
    aplicacion.include_router(public_router)
    aplicacion.include_router(router)

    async def _db():
        yield sesion

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def autenticar(app: FastAPI, id_usuario=ID_AUDITOR, rol: str = "Auditor") -> None:
    async def _usuario():
        return {
            "id_usuario": id_usuario,
            "nombre": "tester",
            "correo": "tester@example.com",
            "estado": "Activo",
            "rol_id": 1,
            "role_name": rol,
        }

    app.dependency_overrides[get_current_user] = _usuario


def test_sin_token_devuelve_401(app):
    respuesta = TestClient(app).get(f"/auditores/registro/conflictos/{ID_AUDITOR}")
    assert respuesta.status_code == 401


def test_catalogo_publico_no_exige_token(app):
    respuesta = TestClient(app).get("/auditores/catalogos/normas")
    assert respuesta.status_code == 200


def test_auditor_no_puede_leer_datos_de_otro(app):
    autenticar(app)

    respuesta = TestClient(app).get(
        f"/auditores/registro/conflictos/{ID_OTRO_AUDITOR}"
    )

    assert respuesta.status_code == 403


def test_auditor_puede_leer_sus_propios_datos(app, monkeypatch):
    async def _conflictos(self, id_usuario):
        return []

    monkeypatch.setattr(AuditorService, "listar_conflictos", _conflictos)
    autenticar(app)

    respuesta = TestClient(app).get(
        f"/auditores/registro/conflictos/{ID_AUDITOR}"
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"conflictos": []}


def test_administrador_puede_leer_datos_de_otro(app, monkeypatch):
    async def _conflictos(self, id_usuario):
        return []

    monkeypatch.setattr(AuditorService, "listar_conflictos", _conflictos)
    autenticar(app, rol="Administrador")

    respuesta = TestClient(app).get(
        f"/auditores/registro/conflictos/{ID_OTRO_AUDITOR}"
    )

    assert respuesta.status_code == 200


def test_postulacion_ajena_devuelve_403(app, sesion):
    sesion.dueno_postulacion = ID_OTRO_AUDITOR
    autenticar(app)

    respuesta = TestClient(app).get(
        f"/auditores/registro/postulacion/{ID_POSTULACION}/estado"
    )

    assert respuesta.status_code == 403


def test_postulacion_propia_pasa_el_control(app, monkeypatch):
    async def _estado(self, id_postulacion):
        return {
            "id_usuario": str(ID_AUDITOR),
            "id_postulacion": str(id_postulacion),
            "nombre": "tester",
            "correo": "tester@example.com",
            "estado_usuario": "Activo",
            "estado_auditor": "ENVIADO",
            "estado_postulacion": "Enviado",
        }

    monkeypatch.setattr(AuditorService, "consultar_estado", _estado)
    autenticar(app)

    respuesta = TestClient(app).get(
        f"/auditores/registro/postulacion/{ID_POSTULACION}/estado"
    )

    assert respuesta.status_code == 200


def test_eliminar_conflicto_de_otro_usuario_devuelve_403(app):
    autenticar(app)

    respuesta = TestClient(app).delete(
        f"/auditores/registro/conflictos/{ID_CONFLICTO}",
        params={"id_usuario": str(ID_OTRO_AUDITOR)},
    )

    assert respuesta.status_code == 403
