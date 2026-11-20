"""
Pantalla unificada "Solicitudes" (18/11/2026).

"Revisión de solicitudes" y "Asignación de auditores" son ahora una sola
pantalla (/solicitudes) con etapas: Radicadas, En revisión, Por asignar
auditor, Con auditores y Todas. Se comprueba:
  · las direcciones anteriores redirigen (sin fragmento, para conservar el #);
  · la página lleva la guardia de sesión y los botones de etapa del menú;
  · el menú común tiene el grupo "Solicitudes" con sus cinco opciones;
  · el contador de etapas: permisos y consultas de solo lectura.
"""

import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from tests.fake_db import ResultadoFalso

RAIZ = Path(__file__).resolve().parents[1]
ETAPAS = ["radicadas", "revision", "por-asignar", "con-auditores", "todas"]


class ResultadoConteo(ResultadoFalso):
    def scalar_one(self):
        return self._escalar


class SesionConteo:
    def __init__(self):
        self.sentencias: list[str] = []

    async def execute(self, sentencia, params=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append(sql)
        if "AS radicadas" in sql:
            return ResultadoConteo([{"radicadas": 3, "revision": 2, "por_asignar": 1, "todas": 9}])
        if "FROM auditores_solicitud a" in sql:
            return ResultadoConteo(escalar=4)
        raise AssertionError("Consulta inesperada: " + sql[:120])


async def _get(ruta, usuario=None, db=None):
    if usuario is not None:
        app.dependency_overrides[get_current_user] = lambda: usuario
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await cliente.get(ruta)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("vieja,etapa", [
    ("/revision-solicitudes", "radicadas"),
    ("/asignacion-auditores", "por-asignar"),
])
async def test_direcciones_anteriores_redirigen_a_su_etapa(vieja, etapa):
    respuesta = await _get(vieja)
    assert respuesta.status_code == 302
    # Sin "#": así el navegador conserva el fragmento antiguo (#revision, #todas...).
    assert respuesta.headers["location"] == f"/solicitudes?etapa={etapa}"


async def test_la_api_de_asignacion_no_cambia_de_ruta():
    """GET /asignacion-auditores/ (con barra) sigue siendo la API, no la redirección."""
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}
    respuesta = await _get("/asignacion-auditores/", usuario=usuario, db=SesionConteo())
    assert respuesta.status_code == 403


async def test_la_pagina_lleva_guardia_y_botones_de_etapa():
    respuesta = await _get("/solicitudes")
    assert respuesta.status_code == 200
    html = respuesta.text
    assert '<script src="/static/requiere-sesion.js"></script>' in html
    for etapa in ETAPAS:
        assert f'data-etapa="{etapa}"' in html
        assert f'data-contador="{etapa}"' in html
    for script in ("solicitudes-revision.js", "solicitudes-asignacion.js", "solicitudes.js", "nav.js"):
        assert f"/static/{script}" in html
    # Lo que tenían las dos pantallas sigue en la nueva.
    for id_ in ("assignmentForm", "assignmentsToggle", "assignmentsPager", "changeTableBody", "modalAdvertencia",
                "retiroConflictoModal", "solicitudesRevisionBody", "detailPanel", "filtrosUbicacion", "decisionModal"):
        assert f'id="{id_}"' in html, id_


def test_las_paginas_viejas_ya_no_existen():
    assert not (RAIZ / "static/revision-solicitudes.html").exists()
    assert not (RAIZ / "static/asignacion-auditores.html").exists()


def test_menu_comun_tiene_el_grupo_solicitudes():
    nav = (RAIZ / "static/nav.js").read_text(encoding="utf-8")
    assert 'grupo: "Solicitudes"' in nav
    assert "\"/solicitudes#\" + e[0]" in nav
    assert "button[data-etapa=" in nav
    for etapa in ETAPAS:
        assert f'["{etapa}",' in nav
    assert 'href: "/asignacion-auditores"' not in nav
    assert 'href: "/revision-solicitudes"' not in nav


def test_aprobar_ofrece_ir_a_asignar_y_auxiliar_ve_pendiente():
    js = (RAIZ / "static/solicitudes-revision.js").read_text(encoding="utf-8")
    assert '"/solicitudes/" + id + "/estado", "PATCH"' in js
    assert "status === 202" in js            # Auxiliar con SOL-054 "requiere aprobación"
    assert "Ir a asignar auditor" in js
    assert 'SolicitudesEtapas.ir("por-asignar"' in js


@pytest.mark.parametrize("rol", ["Coordinador", "Administrador", "Auxiliar"])
async def test_conteo_de_etapas(rol):
    db = SesionConteo()
    # El Auxiliar, con SOL-006 delegado por el Coordinador (regla_auxiliar).
    respuesta = await _get("/asignacion-auditores/conteo-etapas",
                           usuario={"id_usuario": str(uuid.uuid4()), "role_name": rol,
                                    "permisos_delegados": ("SOL-006",)}, db=db)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"radicadas": 3, "revision": 2, "por_asignar": 1, "con_auditores": 4, "todas": 9}
    assert all(sql.startswith("SELECT") for sql in db.sentencias)
    # "Por asignar" usa la misma regla de equipo completo que la lista.
    assert "NOT EXISTS ( SELECT 1 FROM auditores_solicitud a" in db.sentencias[0]


@pytest.mark.parametrize("rol", ["Empresa", "Auditor", "Comite", "Auxiliar"])
async def test_conteo_de_etapas_solo_gestion(rol):
    """El Auxiliar sin permisos delegados tampoco (no tiene permisos propios)."""
    respuesta = await _get("/asignacion-auditores/conteo-etapas",
                           usuario={"id_usuario": str(uuid.uuid4()), "role_name": rol}, db=SesionConteo())
    assert respuesta.status_code == 403
