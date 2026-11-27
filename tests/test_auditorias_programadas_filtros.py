"""Filtros de "Consultar auditorías programadas" (vista del auditor).

El listado recibía `estado` desde la pantalla pero el endpoint no lo aceptaba,
así que elegir "Confirmada" mostraba también la cancelada. Sin estado ("Todos")
deben llegar todas, incluida la Cancelada.
"""

import asyncio
import uuid
from datetime import date
from pathlib import Path

import pytest

from modules.agenda_auditor import agenda_router
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

ID_AUDITOR = uuid.UUID("9532b5e5-b065-44f1-aac0-996483a838bd")
RAIZ = Path(__file__).resolve().parents[1]

PROGRAMACIONES = [
    {"id_programacion": uuid.uuid4(), "id_usuario": ID_AUDITOR, "estado": "Confirmada"},
    {"id_programacion": uuid.uuid4(), "id_usuario": ID_AUDITOR, "estado": "Cancelada"},
]


class SesionProgramaciones:
    """Aplica en memoria el filtro de estado que arma la consulta."""

    def __init__(self):
        self.sql = ""
        self.params = {}

    async def execute(self, statement, params=None):
        self.sql = " ".join(str(statement).split())
        self.params = params or {}
        filas = PROGRAMACIONES
        if "estado" in self.params:
            buscado = self.params["estado"].strip().upper()
            filas = [f for f in filas if f["estado"].strip().upper() == buscado]
        return ResultadoFalso(filas=[dict(f) for f in filas])


def consultar(**filtros):
    sesion = SesionProgramaciones()
    filas = asyncio.run(
        AgendaAuditorService(sesion).consultar_auditorias_programadas(ID_AUDITOR, **filtros)
    )
    return sesion, filas


def test_sin_estado_devuelve_todas_incluida_la_cancelada():
    sesion, filas = consultar()
    assert {f["estado"] for f in filas} == {"Confirmada", "Cancelada"}
    assert "estado" not in sesion.params


def test_filtra_por_estado_sin_distinguir_mayusculas():
    sesion, filas = consultar(estado="  confirmada ")
    assert [f["estado"] for f in filas] == ["Confirmada"]
    assert "UPPER(TRIM(COALESCE(p.estado, ''))) = UPPER(:estado)" in sesion.sql
    assert sesion.params["estado"] == "confirmada"


def test_estado_vacio_equivale_a_todos():
    _, filas = consultar(estado="  ")
    assert len(filas) == 2


@pytest.mark.parametrize("pagina", [
    "consultar_auditorias_programadas.html",
    "consultar_auditorias_programadas_admin.html",
])
def test_filtros_de_ubicacion_usan_desplegables_anclados(pagina):
    html = (RAIZ / "static" / pagina).read_text(encoding="utf-8")
    assert 'id="filtrosUbicacionProgramadas"' in html
    assert "<datalist" not in html.lower()
    for campo in ("ciudad", "departamento", "pais"):
        assert f"filtrosUbicacionProgramadas.sugerir('{campo}'" in html


def test_el_endpoint_acepta_y_pasa_el_estado(monkeypatch):
    recibido = {}

    async def falso(self, id_usuario, desde, hasta, ciudad, modalidad, estado=None):
        recibido.update(desde=desde, hasta=hasta, estado=estado)
        return []

    monkeypatch.setattr(AgendaAuditorService, "consultar_auditorias_programadas", falso)
    respuesta = asyncio.run(
        agenda_router.auditorias_programadas(
            ID_AUDITOR,
            desde=date(2026, 11, 1),
            hasta=date(2026, 11, 30),
            ciudad=None,
            modalidad=None,
            estado="Cancelada",
            usuario={"id_usuario": str(ID_AUDITOR)},
            db=None,
        )
    )
    assert respuesta == {"auditorias": []}
    assert recibido["estado"] == "Cancelada"


def test_conteo_reprogramaciones_usa_programaciones_unicas_y_pendientes():
    class ResultadoConteo:
        def scalar_one(self):
            return 3

    class SesionConteo:
        sql = ""

        async def execute(self, statement):
            self.sql = " ".join(str(statement).split())
            return ResultadoConteo()

    sesion = SesionConteo()
    total = asyncio.run(AgendaAuditorService(sesion).contar_reprogramaciones_pendientes())

    assert total == 3
    assert "COUNT(DISTINCT id_programacion)" in sesion.sql
    assert "estado_solicitud_reprogramacion" in sesion.sql
    assert "= 'PENDIENTE'" in sesion.sql


def test_endpoint_conteo_reprogramaciones_pendientes(monkeypatch):
    async def falso(self):
        return 4

    monkeypatch.setattr(AgendaAuditorService, "contar_reprogramaciones_pendientes", falso)
    respuesta = asyncio.run(
        agenda_router.contar_reprogramaciones_pendientes(
            usuario={"role_name": "Coordinador"},
            db=None,
        )
    )

    assert respuesta == {"total": 4}


def test_resumen_administrativo_incluye_pendientes_con_enlaces_directos():
    html = (RAIZ / "static" / "dashboard.html").read_text(encoding="utf-8")

    assert 'id="notificationCards"' in html
    assert 'id="notificationStatus"' in html
    for href in (
        "/solicitudes#radicadas",
        "/solicitudes#revision",
        "/solicitudes#por-asignar",
        "/solicitudes#con-auditores",
        "/consultar-auditorias-programadas-admin#reprogramaciones",
    ):
        assert href in html
