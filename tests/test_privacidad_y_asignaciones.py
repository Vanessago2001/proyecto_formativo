"""Regresión de los hallazgos de seguridad del re-test del 05/11/2026.

1. El estado del registro de un auditor exige sesión y solo muestra el propio.
2. Cancelar una asignación es solo del administrador; la empresa pide el
   cambio con una razón justificada y el administrador decide.
3. El auditor solo ve sus propios conflictos de interés.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.asignacion_auditores.asignacion_router import router as asignacion_router
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.auditores.auditor_router import public_router, router as auditor_router
from modules.auditores.auditor_service import AuditorService
from modules.conflictos_auditor.conflictos_router import router as conflictos_router
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_ASIGNACION = uuid.UUID("55555555-5555-5555-5555-555555555555")
ID_CAMBIO = uuid.UUID("66666666-6666-6666-6666-666666666666")
CORREO_PROPIO = "propio@example.com"


class SesionVacia:
    async def execute(self, statement, params=None):
        return ResultadoFalso([])

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def app() -> FastAPI:
    aplicacion = FastAPI()
    aplicacion.include_router(public_router)
    aplicacion.include_router(auditor_router)
    aplicacion.include_router(conflictos_router)
    aplicacion.include_router(asignacion_router)

    async def _db():
        yield SesionVacia()

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def autenticar(app: FastAPI, rol: str, correo: str = CORREO_PROPIO) -> None:
    async def _usuario():
        return {
            "id_usuario": ID_USUARIO,
            "nombre": "tester",
            "correo": correo,
            "estado": "Activo",
            "rol_id": 1,
            "role_name": rol,
        }

    app.dependency_overrides[get_current_user] = _usuario


# ---------------------------------------------------------------
# 1. Estado del registro
# ---------------------------------------------------------------

@pytest.fixture
def estado_falso(monkeypatch):
    async def _estado(self, correo):
        return {"correo": correo, "num_doc": "123"}

    monkeypatch.setattr(AuditorService, "consultar_estado_por_correo", _estado)


def test_estado_registro_sin_sesion_devuelve_401(app, estado_falso):
    respuesta = TestClient(app).get(f"/auditores/registro/estado?correo={CORREO_PROPIO}")
    assert respuesta.status_code == 401


def test_estado_registro_de_otro_correo_devuelve_403(app, estado_falso):
    autenticar(app, "Auditor")
    respuesta = TestClient(app).get("/auditores/registro/estado?correo=otro@example.com")
    assert respuesta.status_code == 403


def test_estado_registro_propio_sin_importar_mayusculas(app, estado_falso):
    autenticar(app, "Auditor")
    respuesta = TestClient(app).get("/auditores/registro/estado?correo=PROPIO@example.com")
    assert respuesta.status_code == 200


def test_administrador_consulta_estado_de_otro(app, estado_falso):
    autenticar(app, "Administrador")
    respuesta = TestClient(app).get("/auditores/registro/estado?correo=otro@example.com")
    assert respuesta.status_code == 200


# ---------------------------------------------------------------
# 3. Conflictos de interés propios
# ---------------------------------------------------------------

@pytest.fixture
def filtro_recibido(monkeypatch):
    recibido = {}

    async def _restringidas(self, id_usuario=None):
        recibido["id_usuario"] = id_usuario
        return []

    monkeypatch.setattr(AuditorService, "consultar_empresas_restringidas", _restringidas)
    return recibido


@pytest.mark.parametrize(
    "ruta",
    ["/conflictos-auditor/empresas-restringidas", "/auditores/registro/empresas-restringidas"],
)
def test_auditor_solo_ve_sus_conflictos(app, filtro_recibido, ruta):
    autenticar(app, "Auditor")
    assert TestClient(app).get(ruta).status_code == 200
    assert str(filtro_recibido["id_usuario"]) == str(ID_USUARIO)


@pytest.mark.parametrize(
    "ruta",
    ["/conflictos-auditor/empresas-restringidas", "/auditores/registro/empresas-restringidas"],
)
def test_administrador_ve_todos_los_conflictos(app, filtro_recibido, ruta):
    autenticar(app, "Administrador")
    assert TestClient(app).get(ruta).status_code == 200
    assert filtro_recibido["id_usuario"] is None


# ---------------------------------------------------------------
# 2. Cancelación y solicitudes de cambio
# ---------------------------------------------------------------

@pytest.fixture
def cancelar_falso(monkeypatch):
    async def _cancelar(self, id_asignacion, confirmar=True, usuario=None, motivo=None):
        return {"mensaje": "Asignación cancelada correctamente."}

    monkeypatch.setattr(AsignacionAuditorService, "cancelar_asignacion", _cancelar)


@pytest.mark.parametrize("rol", ["Empresa", "Auditor", "Auxiliar", "Comité"])
def test_solo_el_administrador_cancela_asignaciones(app, cancelar_falso, rol):
    autenticar(app, rol)
    respuesta = TestClient(app).delete(f"/asignacion-auditores/{ID_ASIGNACION}")
    assert respuesta.status_code == 403


@pytest.mark.parametrize("rol", ["Administrador", "Super Administrador"])
def test_administrador_cancela_asignaciones(app, cancelar_falso, rol):
    autenticar(app, rol)
    respuesta = TestClient(app).delete(f"/asignacion-auditores/{ID_ASIGNACION}")
    assert respuesta.status_code == 200


@pytest.mark.parametrize("rol", ["Empresa", "Auditor", "Comité"])
def test_asignar_exige_rol_de_gestion(app, rol):
    autenticar(app, rol)
    respuesta = TestClient(app).post(
        "/asignacion-auditores/",
        json={"id_solicitud": str(ID_ASIGNACION), "id_auditor": str(ID_USUARIO), "rol_auditor": "Observador"},
    )
    assert respuesta.status_code == 403


def test_empresa_solo_lista_sus_asignaciones(app, monkeypatch):
    recibido = {}

    async def _empresas(self, usuario):
        return ["empresa-propia"]

    async def _listar(self, id_solicitud=None, empresas=None):
        recibido["empresas"] = empresas
        return []

    monkeypatch.setattr(AsignacionAuditorService, "empresas_del_usuario", _empresas)
    monkeypatch.setattr(AsignacionAuditorService, "listar_asignaciones", _listar)
    autenticar(app, "Empresa")

    assert TestClient(app).get("/asignacion-auditores/").status_code == 200
    assert recibido["empresas"] == ["empresa-propia"]


def test_auditor_no_lista_asignaciones(app):
    autenticar(app, "Auditor")
    assert TestClient(app).get("/asignacion-auditores/").status_code == 403


def test_solo_la_empresa_solicita_cambio(app):
    autenticar(app, "Auditor")
    respuesta = TestClient(app).post(
        f"/asignacion-auditores/{ID_ASIGNACION}/solicitar-cambio",
        json={"motivo": "x" * 40},
    )
    assert respuesta.status_code == 403


def test_cambio_sin_razon_suficiente_se_rechaza_en_espanol(app):
    autenticar(app, "Empresa")
    respuesta = TestClient(app).post(
        f"/asignacion-auditores/{ID_ASIGNACION}/solicitar-cambio",
        json={"motivo": "no me gusta"},
    )
    assert respuesta.status_code == 422
    assert "30 caracteres" in respuesta.json()["detail"]


def test_empresa_no_pide_cambio_de_asignacion_ajena(app, monkeypatch):
    async def _empresas(self, usuario):
        return ["empresa-propia"]

    monkeypatch.setattr(AsignacionAuditorService, "empresas_del_usuario", _empresas)
    autenticar(app, "Empresa")
    # La sesión vacía no encuentra la asignación: misma respuesta que si fuera de otra empresa.
    respuesta = TestClient(app).post(
        f"/asignacion-auditores/{ID_ASIGNACION}/solicitar-cambio",
        json={"motivo": "El auditor fue asesor de nuestra empresa el año pasado."},
    )
    assert respuesta.status_code == 404


@pytest.mark.parametrize("rol", ["Empresa", "Auxiliar", "Auditor"])
def test_solo_el_administrador_resuelve_cambios(app, rol):
    autenticar(app, rol)
    respuesta = TestClient(app).post(
        f"/asignacion-auditores/solicitudes-cambio/{ID_CAMBIO}/resolver",
        json={"aprobar": True, "respuesta": "Aprobado por prueba."},
    )
    assert respuesta.status_code == 403


def test_resolver_exige_respuesta_para_la_empresa(app):
    autenticar(app, "Administrador")
    respuesta = TestClient(app).post(
        f"/asignacion-auditores/solicitudes-cambio/{ID_CAMBIO}/resolver",
        json={"aprobar": False, "respuesta": "no"},
    )
    assert respuesta.status_code == 422
    assert "10 caracteres" in respuesta.json()["detail"]
