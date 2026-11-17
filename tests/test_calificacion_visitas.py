"""Calificación de visitas por los auditores y su consulta desde el Comité."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.calificacion_visitas.calificacion_service import (
    MENSAJE_FALTA_SQL,
    CalificacionVisitaService,
    validar_calificacion,
)

AUDITOR = {"id_usuario": str(uuid4()), "nombre": "Ana Auditora", "role_name": "Auditor"}
COMITE = {"id_usuario": str(uuid4()), "nombre": "Carlos Comité", "role_name": "Comité"}
COORDINADOR = {"id_usuario": str(uuid4()), "nombre": "Coordinación", "role_name": "Coordinador"}
AUXILIAR = {"id_usuario": str(uuid4()), "nombre": "Aux", "role_name": "Auxiliar"}
EMPRESA = {"id_usuario": str(uuid4()), "nombre": "Empresa", "role_name": "Empresa"}

VALIDO = {"calificacion": 85, "comentario_visita": "La visita se desarrolló sin contratiempos."}


def _resultado(filas=None):
    resultado = MagicMock()
    filas = filas or []
    resultado.mappings.return_value.first.return_value = filas[0] if filas else None
    resultado.mappings.return_value.all.return_value = filas
    return resultado


class BaseFalsa:
    """Responde según la consulta que llega (solo lo que usa el servicio)."""

    def __init__(self, *, tabla=True, visita=None, solicitud=None, equipo=None):
        self.tabla = tabla
        self.visita = visita
        self.solicitud = solicitud
        self.equipo = equipo or []
        self.sql: list[str] = []
        self.insert_params = None
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, consulta, params=None):
        sql = str(consulta)
        self.sql.append(sql)
        if "to_regclass" in sql:
            return _resultado([{"existe": self.tabla}])
        if "FROM programacion_visita p" in sql and "asignado" in sql:
            return _resultado([self.visita] if self.visita else [])
        if "FROM solicitud" in sql and "FOR UPDATE" in sql:
            return _resultado([self.solicitud] if self.solicitud else [])
        if "INSERT INTO calificacion_visita" in sql:
            self.insert_params = params
            return _resultado([{
                "id_calificacion": uuid4(), "id_programacion": params["id_programacion"],
                "id_solicitud": params["id_solicitud"], "calificacion": params["calificacion"],
                "comentario_visita": params["comentario_visita"],
                "situaciones_encontradas": params["situaciones_encontradas"],
                "oportunidades_mejora": params["oportunidades_mejora"],
                "fecha_registro": datetime.now(), "fecha_actualizacion": None, "creada": True,
            }])
        if "SELECT id_solicitud, estado FROM solicitud" in sql:
            return _resultado([self.solicitud] if self.solicitud else [])
        if "JOIN detalle_programacion_auditor d" in sql and "UNION ALL" in sql:
            return _resultado(self.equipo)
        if "WHERE c.id_auditor" in sql:
            return _resultado([])
        raise AssertionError(f"Consulta inesperada: {sql[:120]}")


def _visita(**cambios):
    visita = {
        "id_programacion": uuid4(), "id_solicitud": uuid4(), "estado": "Confirmada",
        "fecha_inicio": datetime.now() - timedelta(hours=2), "asignado": True,
    }
    visita.update(cambios)
    return visita


# ---------------------------------------------------------------- validación

@pytest.mark.parametrize("valor", [0, 101, -5, 50.5, "abc", None, True, "", "12.3"])
def test_calificacion_fuera_de_rango_o_no_entera_se_rechaza(valor):
    with pytest.raises(HTTPException) as error:
        validar_calificacion({**VALIDO, "calificacion": valor})
    assert error.value.status_code == 422


@pytest.mark.parametrize("valor, esperado", [(1, 1), (100, 100), ("75", 75), (60.0, 60)])
def test_calificacion_valida_de_1_a_100(valor, esperado):
    assert validar_calificacion({**VALIDO, "calificacion": valor})["calificacion"] == esperado


def test_sin_ningun_comentario_se_rechaza():
    with pytest.raises(HTTPException) as error:
        validar_calificacion({"calificacion": 80, "comentario_visita": "   ", "situaciones_encontradas": ""})
    assert error.value.status_code == 422
    assert "al menos un comentario" in error.value.detail


def test_comentario_corto_o_muy_largo_se_rechaza():
    with pytest.raises(HTTPException) as corto:
        validar_calificacion({"calificacion": 80, "oportunidades_mejora": "corto"})
    assert "al menos 10" in corto.value.detail
    with pytest.raises(HTTPException) as largo:
        validar_calificacion({"calificacion": 80, "situaciones_encontradas": "x" * 2001})
    assert "2000" in largo.value.detail


def test_basta_un_comentario_y_los_vacios_quedan_en_null():
    limpio = validar_calificacion({"calificacion": 90, "situaciones_encontradas": "  Se encontró un extintor vencido.  "})
    assert limpio == {
        "calificacion": 90,
        "comentario_visita": None,
        "situaciones_encontradas": "Se encontró un extintor vencido.",
        "oportunidades_mejora": None,
    }


# ---------------------------------------------------------------- guardar (auditor)

@pytest.mark.asyncio
async def test_auditor_asignado_califica_la_visita():
    visita = _visita()
    db = BaseFalsa(visita=visita, solicitud={"estado": "En revision"})
    respuesta = await CalificacionVisitaService(db).guardar(visita["id_programacion"], VALIDO, AUDITOR)
    assert respuesta["mensaje"] == "Calificación registrada."
    assert db.insert_params["id_auditor"] == AUDITOR["id_usuario"]
    assert db.insert_params["id_solicitud"] == str(visita["id_solicitud"])
    assert db.insert_params["calificacion"] == 85
    assert any("ON CONFLICT (id_programacion, id_auditor)" in s for s in db.sql)
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_auditor_no_asignado_no_puede_calificar():
    visita = _visita(asignado=False)
    db = BaseFalsa(visita=visita, solicitud={"estado": "En revision"})
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(visita["id_programacion"], VALIDO, AUDITOR)
    assert error.value.status_code == 403
    assert db.insert_params is None


@pytest.mark.asyncio
@pytest.mark.parametrize("usuario", [COMITE, COORDINADOR, AUXILIAR, EMPRESA])
async def test_solo_el_rol_auditor_califica(usuario):
    db = BaseFalsa(visita=_visita(), solicitud={"estado": "En revision"})
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(uuid4(), VALIDO, usuario)
    assert error.value.status_code == 403
    assert db.sql == []


@pytest.mark.asyncio
async def test_visita_cancelada_no_se_califica():
    visita = _visita(estado="Cancelada")
    db = BaseFalsa(visita=visita, solicitud={"estado": "En revision"})
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(visita["id_programacion"], VALIDO, AUDITOR)
    assert error.value.status_code == 409
    assert "cancelada" in error.value.detail


@pytest.mark.asyncio
async def test_visita_que_no_ha_empezado_no_se_califica_pero_finalizada_si():
    futura = _visita(estado="Programada", fecha_inicio=datetime.now() + timedelta(days=3))
    db = BaseFalsa(visita=futura, solicitud={"estado": "En revision"})
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(futura["id_programacion"], VALIDO, AUDITOR)
    assert error.value.status_code == 409
    assert "no ha empezado" in error.value.detail

    finalizada = _visita(estado="Finalizada", fecha_inicio=datetime.now() + timedelta(days=3))
    db = BaseFalsa(visita=finalizada, solicitud={"estado": "En revision"})
    respuesta = await CalificacionVisitaService(db).guardar(finalizada["id_programacion"], VALIDO, AUDITOR)
    assert respuesta["calificacion"]["calificacion"] == 85


@pytest.mark.asyncio
@pytest.mark.parametrize("estado", ["Aprobada", "APROBADO", "Rechazada", "Cerrada"])
async def test_tras_la_decision_del_comite_queda_bloqueada(estado):
    visita = _visita()
    db = BaseFalsa(visita=visita, solicitud={"estado": estado})
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(visita["id_programacion"], VALIDO, AUDITOR)
    assert error.value.status_code == 409
    assert db.insert_params is None
    # La solicitud se bloquea igual que cuando el Comité decide.
    assert any("FOR UPDATE" in s for s in db.sql)


@pytest.mark.asyncio
async def test_visita_inexistente_da_404():
    db = BaseFalsa(visita=None)
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).guardar(uuid4(), VALIDO, AUDITOR)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_sin_la_tabla_responde_503_claro():
    db = BaseFalsa(tabla=False, visita=_visita(), solicitud={"estado": "En revision"})
    for llamada in (
        CalificacionVisitaService(db).guardar(uuid4(), VALIDO, AUDITOR),
        CalificacionVisitaService(db).mis_calificaciones(AUDITOR),
        CalificacionVisitaService(db).calificaciones_expediente(uuid4(), COMITE),
    ):
        with pytest.raises(HTTPException) as error:
            await llamada
        assert error.value.status_code == 503
        assert error.value.detail == MENSAJE_FALTA_SQL


# ---------------------------------------------------------------- comité

def _equipo(id_prog):
    return [
        {"id_programacion": id_prog, "fecha_inicio": datetime(2026, 11, 10, 8), "fecha_fin": None,
         "estado_visita": "Finalizada", "id_auditor": uuid4(), "nombre": "Zoe Observadora", "rol": "Observador",
         "calificacion": 70, "comentario_visita": "Bien en general.", "situaciones_encontradas": None,
         "oportunidades_mejora": None, "fecha_registro": datetime(2026, 11, 11), "fecha_actualizacion": None},
        {"id_programacion": id_prog, "fecha_inicio": datetime(2026, 11, 10, 8), "fecha_fin": None,
         "estado_visita": "Finalizada", "id_auditor": uuid4(), "nombre": "Ana Líder", "rol": "Auditor Líder",
         "calificacion": 91, "comentario_visita": None, "situaciones_encontradas": "Todo en orden.",
         "oportunidades_mejora": None, "fecha_registro": datetime(2026, 11, 11), "fecha_actualizacion": None},
        {"id_programacion": id_prog, "fecha_inicio": datetime(2026, 11, 10, 8), "fecha_fin": None,
         "estado_visita": "Finalizada", "id_auditor": uuid4(), "nombre": "Bruno Sin Calificar", "rol": "Auditor",
         "calificacion": None, "comentario_visita": None, "situaciones_encontradas": None,
         "oportunidades_mejora": None, "fecha_registro": None, "fecha_actualizacion": None},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("usuario", [COMITE, COORDINADOR])
async def test_comite_y_coordinador_ven_las_calificaciones_y_el_promedio(usuario):
    db = BaseFalsa(solicitud={"id_solicitud": uuid4(), "estado": "En revision"}, equipo=_equipo(uuid4()))
    respuesta = await CalificacionVisitaService(db).calificaciones_expediente(uuid4(), usuario)
    assert respuesta["total_auditores"] == 3
    assert respuesta["calificados"] == 2
    assert respuesta["promedio"] == 80.5
    assert respuesta["auditores"][0]["nombre"] == "Ana Líder"  # el líder primero
    assert respuesta["bloqueada"] is False


@pytest.mark.asyncio
async def test_sin_calificaciones_el_promedio_es_none():
    db = BaseFalsa(solicitud={"id_solicitud": uuid4(), "estado": "En revision"}, equipo=[])
    respuesta = await CalificacionVisitaService(db).calificaciones_expediente(uuid4(), COMITE)
    assert respuesta["promedio"] is None and respuesta["auditores"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("usuario", [AUDITOR, AUXILIAR, EMPRESA])
async def test_otros_roles_no_leen_las_calificaciones_del_expediente(usuario):
    db = BaseFalsa(solicitud={"id_solicitud": uuid4(), "estado": "En revision"}, equipo=_equipo(uuid4()))
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).calificaciones_expediente(uuid4(), usuario)
    assert error.value.status_code == 403
    assert db.sql == []


@pytest.mark.asyncio
async def test_expediente_inexistente_da_404():
    db = BaseFalsa(solicitud=None)
    with pytest.raises(HTTPException) as error:
        await CalificacionVisitaService(db).calificaciones_expediente(uuid4(), COMITE)
    assert error.value.status_code == 404


# ---------------------------------------------------------------- rutas

def test_rutas_registradas_y_503_por_http():
    from main import app

    rutas = app.openapi()["paths"]
    assert "put" in rutas["/calificacion-visitas/programacion/{id_programacion}"]
    assert "get" in rutas["/calificacion-visitas/expediente/{id_solicitud}"]
    assert "get" in rutas["/calificacion-visitas/mias"]

    db = BaseFalsa(tabla=False)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: AUDITOR
    try:
        cliente = TestClient(app)
        respuesta = cliente.put(f"/calificacion-visitas/programacion/{uuid4()}", json=VALIDO)
        assert respuesta.status_code == 503
        assert respuesta.json()["detail"] == MENSAJE_FALTA_SQL
        respuesta = cliente.put(f"/calificacion-visitas/programacion/{uuid4()}", json={"calificacion": 150})
        assert respuesta.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
