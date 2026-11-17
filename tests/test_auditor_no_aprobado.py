"""Auditor no aprobado: solo su proceso de registro.

Pedido de la usuaria (17/11/2026): "Si el auditor está en revisión o no está
aprobado como auditor, no se le debe permitir ver el resto de acciones o
módulos a los que los auditores tienen acceso, solo a su proceso mientras se
le aprueba."

· Regla de aprobado = la de la asignación (CTE_AUDITORES): postulación
  Aprobado/Aprobada + usuario.estado 'Activo' + usuario.estado_auditor 'Activo'.
· `require_auditor_aprobado` responde 403 a un Auditor no aprobado en los
  módulos restringidos y deja pasar su proceso y a los demás roles.
"""

import asyncio
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.auth import dependencies
from modules.auth.dependencies import MENSAJE_AUDITOR_NO_APROBADO, require_auditor_aprobado
from modules.agenda_auditor.agenda_router import router as agenda_router
from modules.auditores import auditor_router as auditor_router_mod
from modules.auditorias.auditoria_router import router as auditorias_router
from modules.calificacion_visitas.calificacion_router import router as calificacion_router
from modules.competencias_auditor.competencias_router import router as competencias_router
from modules.conflictos_auditor.conflictos_router import router as conflictos_router
from modules.reportes.reportes_router import router as reportes_router
from modules.reportes_auditor.reporte_router import router as reporte_auditor_router
from tests.fake_db import ResultadoFalso

ID_AUDITOR = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_X = uuid.UUID("22222222-2222-2222-2222-222222222222")


def correr(coro):
    return asyncio.run(coro)


class SesionVacia:
    """Base simulada: toda consulta vuelve vacía."""

    def __init__(self, fila_usuario=None):
        self.fila_usuario = fila_usuario
        self.sql = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.sql.append(sql)
        if self.fila_usuario is not None and "tiene_postulacion_aprobada" in sql:
            return ResultadoFalso([self.fila_usuario])
        return ResultadoFalso([], escalar=0)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _fijar_acceso(monkeypatch, aprobado: bool, estado_postulacion="En Revisión", estado_auditor="Postulante"):
    llamadas = []

    async def _acceso(_db, id_usuario):
        llamadas.append(id_usuario)
        return {
            "aprobado": aprobado,
            "estado_postulacion": "Aprobado" if aprobado else estado_postulacion,
            "estado_auditor": "Activo" if aprobado else estado_auditor,
        }

    monkeypatch.setattr(dependencies, "consultar_acceso_auditor", _acceso)
    monkeypatch.setattr(auditor_router_mod, "consultar_acceso_auditor", _acceso)
    return llamadas


def _usuario(rol="Auditor"):
    return {
        "id_usuario": ID_AUDITOR,
        "nombre": "Prueba",
        "correo": "auditor@example.com",
        "estado": "Activo",
        "rol_id": 1,
        "role_name": rol,
    }


@pytest.fixture
def app():
    aplicacion = FastAPI()
    for r in (
        auditor_router_mod.public_router,
        auditor_router_mod.router,
        agenda_router,
        calificacion_router,
        conflictos_router,
        competencias_router,
        reporte_auditor_router,
        reportes_router,
        auditorias_router,
    ):
        aplicacion.include_router(r)

    async def _db():
        yield SesionVacia()

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def _sesion(app, rol="Auditor"):
    app.dependency_overrides[get_current_user] = lambda: _usuario(rol)
    return TestClient(app, raise_server_exceptions=False)


# Endpoints de los módulos restringidos que usan las pantallas del auditor.
RESTRINGIDOS = [
    ("GET", f"/agenda-auditor/{ID_AUDITOR}/auditorias-programadas"),
    ("GET", f"/agenda-auditor/{ID_AUDITOR}/disponibilidades"),
    ("GET", f"/agenda-auditor/{ID_AUDITOR}/disponibilidad-mensual?anio=2026&mes=11"),
    ("POST", f"/agenda-auditor/{ID_AUDITOR}/no-disponible"),
    ("POST", f"/agenda-auditor/programacion/{ID_X}/confirmar"),
    ("GET", f"/agenda-auditor/{ID_AUDITOR}/programacion/{ID_X}/dias"),
    ("GET", "/calificacion-visitas/mias"),
    ("PUT", f"/calificacion-visitas/programacion/{ID_X}"),
    ("GET", f"/conflictos-auditor/usuario/{ID_AUDITOR}"),
    ("POST", f"/conflictos-auditor/usuario/{ID_AUDITOR}"),
    ("GET", "/conflictos-auditor/empresas-restringidas"),
    ("POST", "/conflictos-auditor/validar-asignacion-nit"),
    ("GET", f"/auditores/registro/conflictos/{ID_AUDITOR}"),
    ("DELETE", f"/auditores/registro/conflictos/{ID_X}?id_usuario={ID_AUDITOR}"),
    ("GET", "/auditores/registro/empresas-restringidas"),
    ("POST", "/auditores/registro/validar-conflicto"),
    ("GET", f"/reportes-auditor/historial-academico/{ID_AUDITOR}"),
    ("GET", "/api/reportes"),
    ("GET", "/api/reportes/operativo-auditores"),
    ("GET", "/auditorias/historial"),
]


@pytest.mark.parametrize("metodo,ruta", RESTRINGIDOS)
def test_auditor_no_aprobado_recibe_403_en_modulos_restringidos(app, monkeypatch, metodo, ruta):
    _fijar_acceso(monkeypatch, aprobado=False)
    respuesta = _sesion(app).request(metodo, ruta, json={})
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json()["detail"] == MENSAJE_AUDITOR_NO_APROBADO


@pytest.mark.parametrize("metodo,ruta", RESTRINGIDOS)
def test_auditor_aprobado_pasa_el_filtro(app, monkeypatch, metodo, ruta):
    _fijar_acceso(monkeypatch, aprobado=True)
    respuesta = _sesion(app).request(metodo, ruta, json={})
    # Lo que pase después depende de cada endpoint y de la base simulada;
    # aquí solo importa que la regla de aprobación no lo frene.
    assert not (respuesta.status_code == 403 and respuesta.json().get("detail") == MENSAJE_AUDITOR_NO_APROBADO)


@pytest.mark.parametrize("rol", ["Coordinador", "Auxiliar", "Comite", "Empresa"])
def test_otros_roles_no_consultan_la_aprobacion(app, monkeypatch, rol):
    llamadas = _fijar_acceso(monkeypatch, aprobado=False)
    cliente = _sesion(app, rol)
    for metodo, ruta in RESTRINGIDOS:
        respuesta = cliente.request(metodo, ruta, json={})
        assert respuesta.status_code != 403 or respuesta.json().get("detail") != MENSAJE_AUDITOR_NO_APROBADO, (rol, ruta)
    assert llamadas == []


def test_catalogo_de_reportes_200_para_aprobado(app, monkeypatch):
    _fijar_acceso(monkeypatch, aprobado=True)
    assert _sesion(app).get("/api/reportes").status_code == 200


# Su proceso: formulario de registro (con competencias, documentos y
# conflictos de interés de la postulación), estado, notificaciones y perfil.
PROCESO = [
    ("GET", "/auditores/mi-acceso"),
    ("GET", f"/auditores/{ID_AUDITOR}/notificaciones"),
    ("GET", "/competencias-auditor/catalogo"),
    ("GET", f"/competencias-auditor/usuario/{ID_AUDITOR}"),
]


@pytest.mark.parametrize("metodo,ruta", PROCESO)
def test_auditor_no_aprobado_usa_su_proceso(app, monkeypatch, metodo, ruta):
    _fijar_acceso(monkeypatch, aprobado=False)
    respuesta = _sesion(app).request(metodo, ruta)
    assert respuesta.status_code == 200, respuesta.text


RUTAS_DEL_PROCESO = [
    ("GET", "/auditores/registro/estado"),
    ("GET", "/auditores/registro/{id_usuario}"),
    ("PUT", "/auditores/registro/{id_usuario}/perfil"),
    ("POST", "/auditores/registro/{id_usuario}/competencias"),
    ("POST", "/auditores/registro/{id_usuario}/documento"),
    ("DELETE", "/auditores/registro/{id_usuario}/conflictos"),
    ("PUT", "/auditores/registro/{id_usuario}/conflictos/{id_conflicto}"),
    ("POST", "/auditores/registro/{id_usuario}/conflictos"),
    ("POST", "/auditores/registro/enviar"),
    ("POST", "/auditores/registro/nueva-postulacion"),
    ("GET", "/auditores/registro/historial-academico/{id_usuario}"),
    ("GET", "/auditores/{id_usuario}/notificaciones"),
    ("PATCH", "/auditores/{id_usuario}/notificaciones/marcar-todas-leidas"),
    ("GET", "/auditores/mi-acceso"),
    # Catálogo de competencias: el auditor no aprobado registra sus
    # certificaciones vigentes durante el registro (decisión 17/11/2026).
    ("GET", "/auditores/registro/{id_usuario}/certificaciones"),
    ("POST", "/auditores/registro/{id_usuario}/certificaciones"),
    ("DELETE", "/auditores/registro/{id_usuario}/certificaciones/{id_certificacion}"),
]


def _depende_de_aprobacion(ruta: APIRoute) -> bool:
    pendientes = list(ruta.dependant.dependencies)
    while pendientes:
        d = pendientes.pop()
        if d.call is require_auditor_aprobado:
            return True
        pendientes.extend(d.dependencies)
    return False


@pytest.mark.parametrize("metodo,ruta", RUTAS_DEL_PROCESO)
def test_rutas_del_proceso_no_exigen_aprobacion(metodo, ruta):
    rutas = [
        r for r in auditor_router_mod.router.routes
        if isinstance(r, APIRoute) and r.path == ruta and metodo in r.methods
    ]
    assert rutas, (metodo, ruta)
    assert not any(_depende_de_aprobacion(r) for r in rutas)


def test_mi_acceso_informa_el_estado(app, monkeypatch):
    _fijar_acceso(monkeypatch, aprobado=False, estado_postulacion="Correcciones")
    datos = _sesion(app).get("/auditores/mi-acceso").json()
    assert datos == {"aprobado": False, "estado_postulacion": "Correcciones", "estado_auditor": "Postulante"}


def test_mi_acceso_otro_rol_siempre_aprobado(app, monkeypatch):
    llamadas = _fijar_acceso(monkeypatch, aprobado=False)
    assert _sesion(app, "Coordinador").get("/auditores/mi-acceso").json()["aprobado"] is True
    assert llamadas == []


# ---- Regla de aprobado (la consulta real, con la fila simulada) ----

@pytest.mark.parametrize(
    "fila,esperado",
    [
        ({"estado": "Activo", "estado_auditor": "Activo", "estado_postulacion": "Aprobado", "tiene_postulacion_aprobada": True}, True),
        ({"estado": "Activo", "estado_auditor": "Postulante", "estado_postulacion": "Aprobado", "tiene_postulacion_aprobada": True}, False),
        ({"estado": "Activo", "estado_auditor": "Postulante", "estado_postulacion": "En Revisión", "tiene_postulacion_aprobada": False}, False),
        ({"estado": "Activo", "estado_auditor": "Activo", "estado_postulacion": "Borrador", "tiene_postulacion_aprobada": False}, False),
        ({"estado": "Inactivo", "estado_auditor": "Activo", "estado_postulacion": "Aprobado", "tiene_postulacion_aprobada": True}, False),
    ],
)
def test_regla_de_aprobado(monkeypatch, fila, esperado):
    monkeypatch.undo()  # la consulta real, no el doble de conftest
    acceso = correr(dependencies.consultar_acceso_auditor(SesionVacia(fila), ID_AUDITOR))
    assert acceso["aprobado"] is esperado
    assert acceso["estado_postulacion"] == fila["estado_postulacion"]


def test_regla_sin_usuario(monkeypatch):
    monkeypatch.undo()
    assert correr(dependencies.consultar_acceso_auditor(SesionVacia(), ID_AUDITOR))["aprobado"] is False


def test_dependencia_directa(monkeypatch):
    _fijar_acceso(monkeypatch, aprobado=False)
    with pytest.raises(HTTPException) as error:
        correr(require_auditor_aprobado(_usuario("Auditor"), SesionVacia()))
    assert error.value.status_code == 403
    assert correr(require_auditor_aprobado(_usuario("Coordinador"), SesionVacia()))["role_name"] == "Coordinador"
