"""
Decisiones del equipo (18/11/2026):

  A) "Solo un auditor por solicitud." Asignación, Agenda (programar, otra
     sede, agregar auditor) y la vía SOL-047/048 responden 409 si se intenta
     sumar un segundo auditor o programar con uno distinto al asignado.
  B) "El acta la genera y la firma el líder." Generar y firmar el acta: 403
     para cualquiera que no sea el líder del comité del expediente (incluido
     el Coordinador). La lista marca al líder qué le toca en cada expediente.

Todo con bases simuladas: nada toca la base real.
"""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.agenda_auditor.agenda_schema import ProgramacionAuditoriaCrear
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.asignacion_auditores import asignacion_service as asignacion_mod
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.comite import comite_acta_service as acta_mod
from modules.comite import comite_router
from modules.comite.comite_acta_service import ComiteActaService
from modules.solicitudes.auditor_service import AuditorSolicitudService
from tests.fake_db import ResultadoFalso

ANA = uuid.uuid4()
LUIS = uuid.uuid4()
SOLICITUD = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


@pytest.fixture(autouse=True)
def _sede_de_la_solicitud_valida(monkeypatch):
    """La regla de la sede de la visita tiene sus propias pruebas; aquí se da por cumplida."""
    from modules.agenda_auditor import agenda_service

    async def _ok(*a, **k):
        return None

    monkeypatch.setattr(agenda_service, "exigir_sede_de_la_solicitud", _ok, raising=False)


# ================================================================ A · Asignación


class SesionLista:
    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.sentencias = []
        self.commits = 0

    async def execute(self, sentencia, params=None):
        self.sentencias.append(_plano(sentencia))
        return self.resultados.pop(0) if self.resultados else ResultadoFalso([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


async def test_asignacion_segundo_auditor_responde_409():
    db = SesionLista([
        ResultadoFalso([]),  # sin programación activa
        ResultadoFalso([{"numero_radicado": "SOL-1", "auditor_nombre": "Ana", "total": 1}]),
    ])
    data = asignacion_mod.AsignacionAuditorCrear(id_solicitud=SOLICITUD, id_auditor=LUIS)
    with pytest.raises(HTTPException) as error:
        await AsignacionAuditorService(db).asignar(data, usuario={})
    assert error.value.status_code == 409
    assert "Solo un auditor por solicitud" in error.value.detail and "Ana" in error.value.detail
    assert not any("INSERT INTO auditores_solicitud" in s for s in db.sentencias)


# ================================================================ A · Agenda


class SesionAgenda:
    """Responde a crear_programacion con la solicitud aprobada y sus asignaciones activas."""

    def __init__(self, activos):
        self.activos = activos  # [(id, nombre)]
        self.sentencias = []

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append(sql)
        if "FROM solicitud s WHERE s.id_solicitud" in sql:
            return ResultadoFalso([{"id_solicitud": SOLICITUD, "estado": "Aprobada", "id_empresa": uuid.uuid4()}])
        if "FROM programacion_visita p LEFT JOIN solicitud" in sql:
            return ResultadoFalso([])
        if "SELECT DISTINCT a.id_auditor, u.nombre FROM auditores_solicitud a" in sql:
            return ResultadoFalso([{"id_auditor": i, "nombre": n} for i, n in self.activos])
        if "FROM usuario WHERE id_usuario" in sql:
            return ResultadoFalso([{"id_usuario": params["id_usuario"], "nombre": "Ana", "estado": "Activo",
                                    "estado_auditor": "Activo"}])
        if "FROM auditores_solicitud a WHERE a.id_solicitud" in sql:
            return ResultadoFalso([{"especialidad": "Auditor", "estado_asignacion": "Agendada"}])
        raise AssertionError("Consulta inesperada: " + sql[:140])

    async def commit(self):
        raise AssertionError("No debe confirmar")

    async def rollback(self):
        pass


def _programar(*auditores):
    return ProgramacionAuditoriaCrear(
        id_solicitud=SOLICITUD,
        auditores=[{"id_usuario": str(a)} for a in auditores],
        direccion_servicio="Calle 1 # 2-3",
        ciudad_servicio="Pereira",
        fecha_inicio=datetime(2099, 1, 7, 9, 0),
        fecha_fin=datetime(2099, 1, 7, 11, 0),
        asignar_auditores_adicionales=True,  # obsoleto: ya no suma a nadie
    )


async def test_agenda_programar_con_dos_auditores_responde_409():
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionAgenda([(ANA, "Ana")])).crear_programacion(_programar(ANA, LUIS))
    assert error.value.status_code == 409
    assert "Solo un auditor por solicitud" in error.value.detail


async def test_agenda_programar_con_auditor_distinto_al_asignado_responde_409():
    db = SesionAgenda([(ANA, "Ana Auditora")])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).crear_programacion(_programar(LUIS))
    assert error.value.status_code == 409
    assert "Solo un auditor por solicitud" in error.value.detail and "Ana Auditora" in error.value.detail
    assert not any("INSERT INTO" in s for s in db.sentencias)


async def test_agenda_programar_sin_auditor_asignado_responde_409():
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionAgenda([])).crear_programacion(_programar(ANA))
    assert error.value.status_code == 409
    assert "no tiene un auditor asignado" in error.value.detail


async def test_agenda_programar_con_el_auditor_asignado_pasa_la_regla(monkeypatch):
    """Con el auditor asignado se sigue a validar su franja (bloqueos/cruces)."""
    async def franja(self, *a, **k):
        return {"motivo": "Ana tiene otra visita."}

    monkeypatch.setattr(AgendaAuditorService, "verificar_franja_auditor", franja)
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionAgenda([(ANA, "Ana")])).crear_programacion(_programar(ANA))
    assert error.value.detail == "No se puede programar: Ana tiene otra visita."


async def test_agenda_datos_anteriores_con_dos_auditores_programa_con_uno_de_ellos(monkeypatch):
    async def franja(self, *a, **k):
        return {"motivo": "llegó a validar la franja"}

    monkeypatch.setattr(AgendaAuditorService, "verificar_franja_auditor", franja)
    db = SesionAgenda([(ANA, "Ana"), (LUIS, "Luis")])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).crear_programacion(_programar(LUIS))
    assert "llegó a validar la franja" in error.value.detail


class SesionAgregar:
    def __init__(self, auditores_en_visita, activos):
        self.en_visita = auditores_en_visita
        self.activos = activos
        self.sentencias = []

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append(sql)
        if "FROM programacion_visita WHERE id_programacion" in sql:
            return ResultadoFalso([{"id_programacion": uuid.uuid4(), "id_solicitud": SOLICITUD,
                                    "id_empresa": uuid.uuid4(), "estado": "Programada",
                                    "fecha_inicio": datetime(2099, 1, 7, 9), "fecha_fin": datetime(2099, 1, 7, 11)}])
        if "FROM solicitud WHERE id_solicitud" in sql:
            return ResultadoFalso([{"id_solicitud": SOLICITUD, "id_empresa": uuid.uuid4(), "id_norma": uuid.uuid4(),
                                    "estado": "Aprobada"}])
        if "FROM usuario WHERE id_usuario" in sql:
            return ResultadoFalso([{"id_usuario": LUIS, "nombre": "Luis", "estado": "Activo", "estado_auditor": "Activo"}])
        if "SELECT COUNT(*) AS total FROM detalle_programacion_auditor" in sql:
            return ResultadoFalso([{"total": self.en_visita}])
        if "SELECT DISTINCT a.id_auditor, u.nombre FROM auditores_solicitud a" in sql:
            return ResultadoFalso([{"id_auditor": i, "nombre": n} for i, n in self.activos])
        raise AssertionError("Consulta inesperada: " + sql[:140])

    async def commit(self):
        raise AssertionError("No debe confirmar")

    async def rollback(self):
        pass


async def test_agenda_agregar_segundo_auditor_a_la_visita_responde_409():
    db = SesionAgregar(auditores_en_visita=1, activos=[(ANA, "Ana")])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).agregar_auditor_a_programacion(uuid.uuid4(), LUIS)
    assert error.value.status_code == 409
    assert "Solo un auditor por solicitud" in error.value.detail
    assert not any("INSERT INTO" in s for s in db.sentencias)


async def test_agenda_agregar_cuando_la_solicitud_tiene_otro_auditor_responde_409():
    db = SesionAgregar(auditores_en_visita=0, activos=[(ANA, "Ana")])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).agregar_auditor_a_programacion(uuid.uuid4(), LUIS)
    assert error.value.status_code == 409 and "Ana" in error.value.detail


# ================================================================ A · SOL-047/048


class SesionProponer:
    def __init__(self, otra_vigente):
        self.otra = otra_vigente
        self.sentencias = []

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append((sql, params or {}))
        if sql.startswith("SELECT id FROM auditores_solicitud") and "id_auditor = :id_auditor" in sql:
            return ResultadoFalso(escalar=None)  # no es el mismo auditor
        if sql.startswith("SELECT id FROM auditores_solicitud"):
            return ResultadoFalso(escalar=uuid.uuid4() if self.otra else None)
        return ResultadoFalso([])

    async def commit(self):
        raise AssertionError("No debe confirmar")

    async def rollback(self):
        pass


async def test_proponer_segundo_auditor_responde_409(monkeypatch):
    async def solicitud(self, *a, **k):
        return {"id_solicitud": SOLICITUD, "id_empresa": uuid.uuid4()}

    monkeypatch.setattr(AuditorSolicitudService, "_solicitud", solicitud)
    db = SesionProponer(otra_vigente=True)
    with pytest.raises(HTTPException) as error:
        await AuditorSolicitudService(db).proponer(SOLICITUD, LUIS, {"id_usuario": str(uuid.uuid4())})
    assert error.value.status_code == 409 and "Solo un auditor por solicitud" in error.value.detail
    assert not any(s.startswith("INSERT INTO auditores_solicitud") for s, _ in db.sentencias)
    consulta = [p for s, p in db.sentencias if "excluir_auditor" in s][0]
    assert consulta["excluir_auditor"] == str(LUIS) and "PROPUESTO" in consulta["vigentes"]


# ================================================================ B · acta


EXPEDIENTE = {"id_solicitud": SOLICITUD, "estado": "Aprobada", "numero_radicado": "SOL-1",
              "alcance_certificacion": None, "observaciones": None, "empresa": "E", "nit": "1",
              "norma_codigo": "ISO", "norma_nombre": "N", "norma_version": "1"}


class SesionActa:
    def __init__(self):
        self.sentencias = []
        self.commits = 0

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append(sql)
        if "FROM solicitud s" in sql and "FOR UPDATE OF s" in sql:
            return ResultadoFalso([EXPEDIENTE])
        raise AssertionError("No debe seguir: " + sql[:120])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _lider(id_usuario, nombre="Comité Prueba"):
    async def lider(db, id_solicitud, bloquear=False):
        return {"id_usuario": id_usuario, "nombre": nombre, "correo": "c@x.co"} if id_usuario else None
    return lider


async def test_generar_acta_otro_miembro_403(monkeypatch):
    monkeypatch.setattr(acta_mod, "lider_de_expediente", _lider(ANA))
    db = SesionActa()
    with pytest.raises(HTTPException) as error:
        await ComiteActaService(db).generar(SOLICITUD, "x", {"id_usuario": str(LUIS)})
    assert error.value.status_code == 403
    assert "Solo el líder del comité" in error.value.detail and "Comité Prueba" in error.value.detail
    assert db.commits == 0


async def test_generar_acta_sin_lider_409(monkeypatch):
    monkeypatch.setattr(acta_mod, "lider_de_expediente", _lider(None))
    with pytest.raises(HTTPException) as error:
        await ComiteActaService(SesionActa()).generar(SOLICITUD, "x", {"id_usuario": str(LUIS)})
    assert error.value.status_code == 409 and "Coordinador" in error.value.detail


async def test_firmar_acta_otro_miembro_403(monkeypatch):
    monkeypatch.setattr(acta_mod, "lider_de_expediente", _lider(ANA))
    with pytest.raises(HTTPException) as error:
        await ComiteActaService(SesionActa()).firmar(SOLICITUD, "clave", {"id_usuario": str(LUIS)})
    assert error.value.status_code == 403


@pytest.mark.parametrize("rol", ["Coordinador", "Comité"])
async def test_api_generar_y_firmar_acta_no_lider_403(monkeypatch, rol):
    async def sin_impedimento(*a, **k):
        return None

    monkeypatch.setattr(comite_router, "exigir_imparcialidad", sin_impedimento)
    monkeypatch.setattr(acta_mod, "lider_de_expediente", _lider(ANA))
    app.dependency_overrides[get_db] = lambda: SesionActa()
    app.dependency_overrides[get_current_user] = lambda: {"id_usuario": str(LUIS), "role_name": rol}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            generar = await cliente.post("/comite/acta-definitiva",
                                         json={"expediente_id": str(SOLICITUD), "comentario": "Acta"})
            firmar = await cliente.post("/comite/firmar-acta",
                                        json={"expediente_id": str(SOLICITUD), "password_firma": "x"})
    finally:
        app.dependency_overrides.clear()
    assert generar.status_code == 403 and firmar.status_code == 403


# ================================================================ B · lo que ve el líder


def _fila(**extra):
    base = {"id": SOLICITUD, "codigo": "SOL-1", "estado": "Aprobada", "accion": "aprobar",
            "estado_acta": None, "estado_certificado": None, "certificado_firmado": None,
            "lider_id": ANA, "lider_nombre": "Comité Prueba", "lider_por_expediente": False,
            "impedimento": None}
    base.update(extra)
    return comite_router._fila_expediente_unificada(base)


@pytest.mark.parametrize(
    "extra,generar,firmar,certificado",
    [
        ({}, True, False, False),                                         # Generar acta
        ({"estado_acta": "GENERADA"}, False, True, False),                # Firmar acta
        ({"estado_acta": "FIRMADA"}, False, False, False),                # Ver acta firmada
        ({"estado_acta": "FIRMADA", "estado_certificado": "PENDIENTE_FIRMA"}, False, False, True),
        ({"estado": "Cerrada"}, False, False, False),                     # ya no se genera (409)
        ({"accion": None}, False, False, False),                          # sin decisión del Comité
    ],
)
def test_lider_ve_lo_que_le_toca_segun_el_estado(extra, generar, firmar, certificado):
    fila = _fila(**extra)
    comite_router._marcar_mi_liderazgo([fila], {"id_usuario": str(ANA)})
    assert fila["es_mi_liderazgo"] is True
    assert (fila["lider_acta_por_generar"], fila["lider_acta_por_firmar"], fila["lider_certificado_por_firmar"]) == (
        generar, firmar, certificado)
    assert fila["lider_pendiente"] is (generar or firmar or certificado)


def test_otro_miembro_no_ve_acciones_de_lider_y_el_filtro_solo_trae_lo_del_lider():
    mia, ajena = _fila(), _fila(lider_id=LUIS)
    comite_router._marcar_mi_liderazgo([mia, ajena], {"id_usuario": str(ANA)})
    assert ajena["es_mi_liderazgo"] is False and ajena["lider_pendiente"] is False
    assert comite_router._filtrar_por_decision_y_firma([mia, ajena], None, "lider-pendiente") == [mia]
