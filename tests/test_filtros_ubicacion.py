"""Filtros de ciudad, departamento y país (filtran mientras se escribe).

Se comprueba, con sesiones falsas, que los parámetros nuevos llegan a la
consulta normalizados (sin tildes ni mayúsculas, coincidencia parcial) y que
sin filtros la consulta queda como antes.
"""

import asyncio
import uuid
from datetime import date
from pathlib import Path

from core.filtros_ubicacion import (
    condicion_contiene,
    condiciones_ubicacion_solicitud,
    patron_contiene,
    sql_comparable,
    texto_comparable,
)
from modules.agenda_auditor import agenda_router
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.comite.comite_service import construir_filtro_expedientes
from modules.empresas.empresas_service import EmpresasService
from modules.solicitudes.solicitud_service import SolicitudService
from tests.fake_db import ResultadoFalso

RAIZ = Path(__file__).resolve().parents[1]


class Resultado(ResultadoFalso):
    def scalar_one(self):
        return self.scalar()


class Sesion:
    """Guarda cada consulta y responde con las filas indicadas."""

    def __init__(self, filas=None, escalar=0):
        self.consultas: list[tuple[str, dict]] = []
        self.filas = filas or []
        self.escalar = escalar

    async def execute(self, sentencia, params=None):
        self.consultas.append((" ".join(str(sentencia).split()), dict(params or {})))
        return Resultado(filas=[dict(f) for f in self.filas], escalar=self.escalar)


# ------------------------------------------------------------------ utilidades
def test_texto_comparable_quita_tildes_mayusculas_y_espacios():
    assert texto_comparable("  BOGOTÁ   D.C. ") == "bogota d.c."
    assert texto_comparable("Peñol") == "penol"
    assert texto_comparable(None) == ""


def test_patron_contiene_es_parcial_y_escapa_comodines():
    assert patron_contiene("Bogo") == "%bogo%"
    assert patron_contiene("  ") is None
    assert patron_contiene("50%_x") == "%50\\%\\_x%"


def test_sql_comparable_traduce_tildes_igual_que_python():
    sql = sql_comparable("e.ciudad")
    assert sql.startswith("LOWER(TRANSLATE(COALESCE(e.ciudad, '')")
    assert "ÁÉÍÓÚÜÑ" in sql and "AEIOUUN" in sql
    assert condicion_contiene("e.ciudad", "c").endswith("LIKE :c ESCAPE '\\'")


def test_condiciones_de_solicitud_ciudad_empresa_o_sede_y_departamento_de_sede():
    condiciones, params = condiciones_ubicacion_solicitud("Medellín", "ANTIOQUIA", "colombia")
    assert params == {"ubic_ciudad": "%medellin%", "ubic_departamento": "%antioquia%", "ubic_pais": "%colombia%"}
    assert "e.ciudad" in condiciones[0] and "se_u.ciudad" in condiciones[0]
    assert "se_u.departamento" in condiciones[1] and "ss_u.estado <> 'Excluida'" in condiciones[1]
    assert "se_u.pais" in condiciones[2]
    assert condiciones_ubicacion_solicitud(None, "", "  ") == ([], {})


# ------------------------------------------------------------- asignación
def test_solicitudes_aprobadas_filtra_por_ciudad_departamento_y_pais():
    sesion = Sesion(escalar=0)
    asyncio.run(AsignacionAuditorService(sesion).listar_solicitudes_aprobadas(
        ciudad="Bogotá", departamento="cundi", pais="COLOMBIA"
    ))
    sql, params = sesion.consultas[0]
    assert params["ubic_ciudad"] == "%bogota%"
    assert params["ubic_departamento"] == "%cundi%"
    assert params["ubic_pais"] == "%colombia%"
    assert "solicitud_sede ss_u" in sql


def test_solicitudes_aprobadas_sin_filtro_de_ubicacion_no_toca_las_sedes():
    sesion = Sesion(escalar=0)
    asyncio.run(AsignacionAuditorService(sesion).listar_solicitudes_aprobadas())
    sql, params = sesion.consultas[0]
    assert "solicitud_sede" not in sql
    assert not any(k.startswith("ubic_") for k in params)


def test_candidatos_filtran_por_ciudad_y_departamento_sin_tildes():
    solicitud = {"id_solicitud": uuid.uuid4(), "estado": "Aprobada", "id_empresa": uuid.uuid4(), "id_norma": uuid.uuid4()}

    class SesionCandidatos(Sesion):
        async def execute(self, sentencia, params=None):
            if "WHERE s.id_solicitud = :id_solicitud" in str(sentencia):
                self.consultas.append((" ".join(str(sentencia).split()), dict(params or {})))
                return Resultado(filas=[solicitud])
            return await super().execute(sentencia, params)

    sesion = SesionCandidatos(escalar=0)
    asyncio.run(AsignacionAuditorService(sesion).listar_auditores_elegibles(
        solicitud["id_solicitud"], ciudad="Pereirá", departamento="RISAR"
    ))
    sql, params = sesion.consultas[1]
    assert params["ciudad"] == "%pereira%"
    assert params["departamento"] == "%risar%"
    assert "departamento_residencia" in sql and "TRANSLATE" in sql


# ------------------------------------------------------------------- comité
def test_comite_agrega_condiciones_de_ubicacion_solo_si_hay_texto():
    sin, params_sin = construir_filtro_expedientes("todos")
    assert "solicitud_sede" not in sin and not any(k.startswith("ubic_") for k in params_sin)
    con, params = construir_filtro_expedientes("todos", ciudad="Cali", pais="Colombia")
    assert params["ubic_ciudad"] == "%cali%" and params["ubic_pais"] == "%colombia%"
    assert "ubic_departamento" not in params
    assert "solicitud_sede ss_u" in con


# ------------------------------------------------------------------- agenda
def test_programaciones_admin_filtran_por_ciudad_departamento_y_pais():
    sesion = Sesion()
    asyncio.run(AgendaAuditorService(sesion).listar_todas_programaciones(
        ciudad="Bogotá", departamento="Cundinamarca", pais="Colombia"
    ))
    sql, params = sesion.consultas[0]
    assert params == {"ciudad": "%bogota%", "departamento": "%cundinamarca%", "pais": "%colombia%"}
    assert "LEFT JOIN sede_empresa sede ON sede.id_sede = p.id_sede" in sql
    assert "sede.departamento AS sede_departamento" in sql


def test_calendario_mensual_usa_filtros_de_ubicacion_anclados():
    html = (RAIZ / "static" / "consultar_agenda_auditor.html").read_text(encoding="utf-8")
    assert 'id="monthLocationFilters"' in html
    for id_lista in ("cityFilterLista", "deptFilterLista", "countryFilterLista"):
        assert id_lista not in html
    assert '["ciudad", "departamento", "pais"].forEach(clave => {' in html
    assert "filtrosUbicacionMes.sugerir(clave, [...lugaresCalendario[clave]])" in html


def test_auditorias_del_auditor_mantienen_su_alcance_y_aceptan_departamento():
    id_auditor = uuid.uuid4()
    sesion = Sesion()
    asyncio.run(AgendaAuditorService(sesion).consultar_auditorias_programadas(
        id_auditor, departamento="risaralda"
    ))
    sql, params = sesion.consultas[0]
    assert params["id_usuario"] == str(id_auditor)
    assert params["departamento"] == "%risaralda%"
    assert "ciudad" not in params


def test_endpoint_de_auditorias_solo_pasa_departamento_y_pais_si_llegan():
    recibido = {}

    async def falso(self, id_usuario, desde, hasta, ciudad, modalidad, estado=None, **extra):
        recibido.update(extra)
        return []

    import pytest
    monkey = pytest.MonkeyPatch()
    monkey.setattr(AgendaAuditorService, "consultar_auditorias_programadas", falso)
    try:
        asyncio.run(agenda_router.auditorias_programadas(
            uuid.uuid4(), desde=None, hasta=None, ciudad=None, modalidad=None, estado=None,
            departamento="Valle", pais="  ", usuario={}, db=None,
        ))
    finally:
        monkey.undo()
    assert recibido == {"departamento": "Valle"}


def test_calendario_mensual_filtra_por_departamento_y_pais_de_la_sede():
    from datetime import datetime

    def fila(id_prog, departamento, pais):
        return {
            "id_programacion": id_prog, "id_solicitud": uuid.uuid4(), "id_sede": uuid.uuid4(),
            "fecha_inicio": datetime(2026, 11, 10, 8), "fecha_fin": datetime(2026, 11, 10, 12),
            "modalidad": "Presencial", "ciudad_servicio": "Bogotá", "estado_programacion": "Programada",
            "sede_departamento": departamento, "sede_pais": pais, "id_usuario": None,
        }

    class SesionMes:
        async def execute(self, sentencia, params=None):
            if "FROM programacion_visita p" in str(sentencia):
                return ResultadoFalso(filas=[fila("a", "Cundinamarca", "Colombia"), fila("b", "Lima", "Perú")])
            return ResultadoFalso(filas=[])

    r = asyncio.run(AgendaAuditorService(SesionMes()).ver_disponibilidad_mensual_general(2026, 11, pais="peru"))
    assert [a["id_programacion"] for a in r["auditorias"]] == ["b"]
    r = asyncio.run(AgendaAuditorService(SesionMes()).ver_disponibilidad_mensual_general(2026, 11, departamento="CUNDI"))
    assert [a["id_programacion"] for a in r["auditorias"]] == ["a"]


# --------------------------------------------------- empresas y solicitudes
def test_listado_de_empresas_incluye_la_ubicacion_de_sus_sedes():
    sesion = Sesion(filas=[{"id_empresa": 1, "nombre": "X"}])
    asyncio.run(EmpresasService(sesion).get_all_empresas())
    sql, _ = sesion.consultas[0]
    for alias in ("sedes_ciudades", "sedes_departamentos", "sedes_paises"):
        assert alias in sql


def test_empresas_del_auditor_siguen_limitadas_a_sus_asignaciones():
    sesion = Sesion()
    asyncio.run(EmpresasService(sesion).get_empresas_de_auditor("abc"))
    sql, params = sesion.consultas[0]
    assert params == {"id_auditor": "abc"}
    assert "a.id_auditor = :id_auditor" in sql
    assert "e.correo" not in sql and "e.direccion" not in sql
    assert "sedes_departamentos" in sql


def test_listado_de_solicitudes_agrega_ubicacion_solo_si_se_pide():
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Coordinador"}
    sesion = Sesion()
    asyncio.run(SolicitudService(sesion).listar(usuario))
    assert "sedes_ciudades" not in sesion.consultas[-1][0]
    sesion = Sesion()
    asyncio.run(SolicitudService(sesion).listar(usuario, incluir_ubicacion=True))
    sql = sesion.consultas[-1][0]
    assert "sedes_ciudades" in sql and "ss.estado <> 'Excluida'" in sql
