"""
Agenda (20/11/2026): si la visita ya tiene auditor el botón es
"Reemplazar auditor"; si no, "Agregar auditor".

Reemplazar cambia el auditor en todas las visitas vigentes de la
solicitud, cancela la asignación anterior y registra la nueva (un
auditor por solicitud). Todo con bases simuladas.
"""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException

from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from tests.fake_db import ResultadoFalso

ANA = uuid.uuid4()
LUIS = uuid.uuid4()
SOLICITUD = uuid.uuid4()
VISITA = uuid.uuid4()
OTRA_VISITA = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


class SesionReemplazo:
    def __init__(self, en_visita, estado_solicitud="Aprobada", luis_asignado=False):
        self.en_visita = en_visita
        self.estado_solicitud = estado_solicitud
        self.luis_asignado = luis_asignado
        self.sentencias = []
        self.commits = 0

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append((sql, params or {}))
        if sql.startswith("SELECT id_programacion, id_solicitud, estado FROM programacion_visita"):
            return ResultadoFalso([{"id_programacion": VISITA, "id_solicitud": SOLICITUD, "estado": "Programada"}])
        if "FROM solicitud WHERE id_solicitud" in sql:
            return ResultadoFalso([{"estado": self.estado_solicitud, "numero_radicado": "SOL-2026-000009"}])
        if "FROM detalle_programacion_auditor d LEFT JOIN usuario" in sql:
            return ResultadoFalso([{"id_usuario": i, "nombre": "Ana"} for i in self.en_visita])
        if "FROM usuario WHERE id_usuario" in sql:
            return ResultadoFalso([{"id_usuario": LUIS, "nombre": "Luis", "estado": "Activo", "estado_auditor": "Activo"}])
        if "SELECT DISTINCT pv.id_programacion" in sql:
            return ResultadoFalso([
                {"id_programacion": VISITA, "fecha_inicio": datetime(2099, 1, 7, 9), "fecha_fin": datetime(2099, 1, 7, 11)},
                {"id_programacion": OTRA_VISITA, "fecha_inicio": datetime(2099, 1, 8, 9), "fecha_fin": datetime(2099, 1, 8, 11)},
            ])
        if sql.startswith("SELECT 1 FROM auditores_solicitud a"):
            return ResultadoFalso([{"?column?": 1}] if self.luis_asignado else [])
        if sql.startswith(("DELETE", "UPDATE", "INSERT")):
            return ResultadoFalso([])
        raise AssertionError("Consulta inesperada: " + sql[:160])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


@pytest.fixture(autouse=True)
def _dependencias(monkeypatch):
    async def _elegible(self, id_solicitud, id_auditor, **_):
        return {"competencia_norma": True, "conflicto_interes": False, "rol_auditor": "Auditor"}

    async def _libre(self, *args, **kwargs):
        return None

    async def _estado(self, _id):
        return "Programada"

    monkeypatch.setattr(AsignacionAuditorService, "validar_auditor", _elegible)
    monkeypatch.setattr(AgendaAuditorService, "verificar_franja_auditor", _libre)
    monkeypatch.setattr(AgendaAuditorService, "_crear_notificacion", _libre)
    monkeypatch.setattr(AgendaAuditorService, "_estado_final_programacion", _estado)


def _sentencias(db, inicio):
    return [s for s, _ in db.sentencias if s.startswith(inicio)]


async def test_reemplazar_cambia_el_auditor_en_todas_las_visitas_de_la_solicitud():
    db = SesionReemplazo(en_visita=[ANA])

    respuesta = await AgendaAuditorService(db).reemplazar_auditor_de_programacion(VISITA, LUIS)

    assert respuesta["visitas_actualizadas"] == 2
    assert "Luis reemplazó a Ana" in respuesta["mensaje"]
    assert len(_sentencias(db, "DELETE FROM detalle_programacion_auditor")) == 2
    inserciones = [p for s, p in db.sentencias if s.startswith("INSERT INTO detalle_programacion_auditor")]
    assert {p["id_programacion"] for p in inserciones} == {str(VISITA), str(OTRA_VISITA)}
    assert all(p["id_usuario"] == str(LUIS) for p in inserciones)
    # La asignación anterior se cancela y se registra la del auditor nuevo.
    assert any("SET estado_asignacion = 'Cancelada'" in s for s, _ in db.sentencias)
    assert len(_sentencias(db, "INSERT INTO auditores_solicitud")) == 1
    assert db.commits == 1


async def test_reemplazar_no_duplica_la_asignacion_si_ya_existe():
    db = SesionReemplazo(en_visita=[ANA], luis_asignado=True)
    await AgendaAuditorService(db).reemplazar_auditor_de_programacion(VISITA, LUIS)
    assert not _sentencias(db, "INSERT INTO auditores_solicitud")


async def test_reemplazar_una_visita_sin_auditor_pide_usar_agregar():
    db = SesionReemplazo(en_visita=[])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).reemplazar_auditor_de_programacion(VISITA, LUIS)
    assert error.value.status_code == 409
    assert "Agregar auditor" in error.value.detail
    assert db.commits == 0


async def test_reemplazar_por_el_mismo_auditor_responde_409():
    db = SesionReemplazo(en_visita=[LUIS])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).reemplazar_auditor_de_programacion(VISITA, LUIS)
    assert error.value.status_code == 409
    assert not _sentencias(db, "DELETE")


async def test_reemplazar_respeta_el_cruce_de_horario_del_auditor_nuevo(monkeypatch):
    async def _ocupado(self, id_usuario, inicio, fin, excluir=None, nombre=None):
        return {"motivo": "Luis ya tiene otra visita en esa franja."}

    monkeypatch.setattr(AgendaAuditorService, "verificar_franja_auditor", _ocupado)
    db = SesionReemplazo(en_visita=[ANA])
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).reemplazar_auditor_de_programacion(VISITA, LUIS)
    assert error.value.status_code == 409
    assert "otra visita" in error.value.detail
    assert not _sentencias(db, "DELETE")
    assert db.commits == 0
