"""
QA 18/11/2026: huecos de visibilidad.

1. El Auditor solo ve las solicitudes en las que está asignado y los
   certificados de esas solicitudes; no recibe alertas de vencimiento; el
   auditor no aprobado recibe 403. Los demás roles no cambian.
2. Imparcialidad: el miembro del Comité impedido no ve el expediente en
   GET /solicitudes/ ni en los reportes (certificados vigentes, apelaciones).
3. Cabecera pública con sesión: "Ir a mi panel" y "Cerrar sesión".
4. La API pública ya no devuelve alcance_certificacion.
"""

import asyncio
import inspect
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from modules.auth import dependencies
from modules.certificados import certificados_permissions as permisos_cer
from modules.certificados.certificados_service import CertificadosService
from modules.reportes.reportes_service import ReportesService
from modules.solicitudes.solicitud_service import SolicitudService
from tests.fake_db import SesionFalsa

ID_AUDITOR = str(uuid.uuid4())
AUDITOR = {"id_usuario": ID_AUDITOR, "role_name": "Auditor"}
COMITE = {"id_usuario": str(uuid.uuid4()), "role_name": "Comité"}
COORDINADOR = {"id_usuario": str(uuid.uuid4()), "role_name": "Coordinador"}
RAIZ = Path(__file__).resolve().parent.parent


def _no_aprobado(monkeypatch):
    async def _acceso(_db, _id):
        return {"aprobado": False, "estado_postulacion": "En revisión", "estado_auditor": "Inactivo"}

    monkeypatch.setattr(dependencies, "consultar_acceso_auditor", _acceso)


class BaseQueAnota:
    """Guarda cada consulta y responde vacío."""

    def __init__(self, fila=None):
        self.sql: list[tuple[str, dict]] = []
        self.fila = fila

    async def execute(self, sentencia, parametros=None):
        self.sql.append((" ".join(str(sentencia).split()), dict(parametros or {})))
        resultado = MagicMock()
        resultado.mappings.return_value.all.return_value = []
        resultado.mappings.return_value.first.return_value = self.fila
        return resultado

    def ultima(self):
        return self.sql[-1]


# ------------------------------------------------------------------
# 1. Auditor: solicitudes
# ------------------------------------------------------------------

def _sesion_con_dos_solicitudes():
    sesion = SesionFalsa()
    asignada = sesion.sembrar(estado="Radicada")
    sesion.sembrar(estado="Borrador")
    sesion.asignar_auditor(ID_AUDITOR, asignada["id_solicitud"])
    return sesion, asignada


def test_el_auditor_solo_lista_las_solicitudes_asignadas():
    sesion, asignada = _sesion_con_dos_solicitudes()
    filas = asyncio.run(SolicitudService(sesion).listar(AUDITOR))
    assert [f["id_solicitud"] for f in filas] == [asignada["id_solicitud"]]


def test_el_coordinador_sigue_viendo_todas_las_solicitudes():
    sesion, _ = _sesion_con_dos_solicitudes()
    assert len(asyncio.run(SolicitudService(sesion).listar(COORDINADOR))) == 2


def test_el_auditor_no_abre_el_detalle_de_una_solicitud_no_asignada():
    sesion, asignada = _sesion_con_dos_solicitudes()
    otra = next(f for f in sesion.solicitudes.values() if f["id_solicitud"] != asignada["id_solicitud"])
    servicio = SolicitudService(sesion)
    assert asyncio.run(servicio.consultar(asignada["id_solicitud"], AUDITOR))["id_solicitud"] == asignada["id_solicitud"]
    with pytest.raises(HTTPException) as error:
        asyncio.run(servicio.consultar(otra["id_solicitud"], AUDITOR))
    assert error.value.status_code == 404


def test_el_auditor_no_aprobado_recibe_403_en_el_listado(monkeypatch):
    _no_aprobado(monkeypatch)
    sesion, _ = _sesion_con_dos_solicitudes()
    with pytest.raises(HTTPException) as error:
        asyncio.run(SolicitudService(sesion).listar(AUDITOR))
    assert error.value.status_code == 403
    assert error.value.detail == dependencies.MENSAJE_AUDITOR_NO_APROBADO


def test_la_asignacion_cancelada_no_da_acceso():
    sql = dependencies.sql_auditor_asignado("s.id_solicitud")
    assert "auditores_solicitud" in sql and "NOT IN" in sql
    for estado in ("CANCELADA", "REASIGNADO", "RECHAZADA"):
        assert f"'{estado}'" in sql


# ------------------------------------------------------------------
# 1. Auditor: certificados y alertas
# ------------------------------------------------------------------

def test_el_auditor_solo_lista_certificados_de_sus_solicitudes():
    db = BaseQueAnota()
    asyncio.run(CertificadosService(db).listar(AUDITOR))
    sql, params = db.ultima()
    assert "FROM auditores_solicitud aud_a WHERE aud_a.id_solicitud = c.id_solicitud" in sql
    assert params["aud_usuario"] == ID_AUDITOR


def test_el_auditor_no_aprobado_no_lista_certificados(monkeypatch):
    _no_aprobado(monkeypatch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(CertificadosService(BaseQueAnota()).listar(AUDITOR))
    assert error.value.status_code == 403


@pytest.mark.parametrize("usuario", [COORDINADOR, {"id_usuario": str(uuid.uuid4()), "role_name": "Auxiliar"}])
def test_coordinador_y_auxiliar_listan_certificados_sin_filtro_de_auditor(usuario):
    db = BaseQueAnota()
    asyncio.run(CertificadosService(db).listar(usuario))
    assert "auditores_solicitud" not in db.ultima()[0]


def test_las_alertas_de_vencimiento_no_son_para_el_auditor():
    assert not permisos_cer.tiene_permiso("CER-027", "Auditor")
    for rol in ("Coordinador", "Auxiliar", "Empresa"):
        assert permisos_cer.tiene_permiso("CER-027", rol)


# ------------------------------------------------------------------
# 2. Imparcialidad del Comité en el listado y en los reportes
# ------------------------------------------------------------------

def test_el_comite_no_lista_solicitudes_en_las_que_esta_impedido():
    db = BaseQueAnota()
    asyncio.run(SolicitudService(db).listar(COMITE))
    sql, params = db.ultima()
    assert "FROM apelacion ap" in sql and "comite_accion ca" in sql and "IS NULL" in sql
    assert params["imp_usuario"] == COMITE["id_usuario"]


def test_el_coordinador_no_lleva_filtro_de_imparcialidad_en_solicitudes():
    db = BaseQueAnota()
    asyncio.run(SolicitudService(db).listar(COORDINADOR))
    sql, params = db.ultima()
    assert "comite_accion" not in sql and "imp_usuario" not in params


@pytest.mark.parametrize("codigo", ["certificados-vigentes", "apelaciones-fallos"])
def test_los_reportes_del_comite_excluyen_expedientes_impedidos(codigo):
    db = BaseQueAnota()
    asyncio.run(ReportesService(db, COMITE).ejecutar(codigo))
    sql, params = db.ultima()
    assert "comite_accion ca" in sql and "IS NULL" in sql
    assert params["imp_usuario"] == COMITE["id_usuario"]


def test_en_apelaciones_y_fallos_el_comite_conserva_la_apelacion_que_decidio():
    db = BaseQueAnota()
    asyncio.run(ReportesService(db, COMITE).ejecutar("apelaciones-fallos"))
    # Alias distinto del "ap" interno del SQL de imparcialidad.
    assert "ap.id <> apl.id" in db.ultima()[0]


@pytest.mark.parametrize("codigo", ["certificados-vigentes", "apelaciones-fallos", "preventivo-conflictos"])
def test_los_reportes_del_coordinador_no_cambian(codigo):
    db = BaseQueAnota()
    asyncio.run(ReportesService(db, COORDINADOR).ejecutar(codigo))
    sql, params = db.ultima()
    assert "comite_accion" not in sql and "auditores_solicitud aud_a" not in sql
    assert "imp_usuario" not in params


def test_el_reporte_de_certificados_vigentes_del_auditor_solo_trae_sus_solicitudes():
    db = BaseQueAnota()
    asyncio.run(ReportesService(db, AUDITOR).ejecutar("certificados-vigentes"))
    sql, params = db.ultima()
    assert "auditores_solicitud aud_a" in sql and params["aud_usuario"] == ID_AUDITOR


# ------------------------------------------------------------------
# 3. Cabecera pública con sesión (static/session.js)
# ------------------------------------------------------------------

PAGINAS_PUBLICAS = [
    "buscar_e", "login", "register", "reset-password", "cuenta_inactiva",
    "cambiar_password", "vigencia", "validar", "consulta_norma", "constancia",
    "index", "certificados",
]


def test_session_js_cambia_la_cabecera_publica_con_sesion():
    js = (RAIZ / "static" / "session.js").read_text(encoding="utf-8")
    assert "Ir a mi panel" in js and "Cerrar sesión" in js
    assert '".header-buttons a[href], .mobile-menu a[href]"' in js
    # Mismo destino que el logo.
    assert "var destino = destinoDelLogo();" in js


@pytest.mark.parametrize("pagina", PAGINAS_PUBLICAS)
def test_las_paginas_publicas_cargan_la_version_nueva_de_session_js(pagina):
    html = (RAIZ / "static" / f"{pagina}.html").read_text(encoding="utf-8")
    assert "/static/session.js?v=20261118pub" in html


# ------------------------------------------------------------------
# 4. Sin alcance en la API pública
# ------------------------------------------------------------------

def test_la_api_publica_no_devuelve_el_alcance():
    from modules.consultas_p import consultas_service

    assert "alcance_certificacion" not in inspect.getsource(consultas_service)
    fila = consultas_service._fila_sin_tramite({}, "SIN_TRAMITE", "N/A", "")
    assert "alcance_certificacion" not in fila
