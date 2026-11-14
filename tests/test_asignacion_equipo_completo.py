"""
Una solicitud con su equipo de auditores completo no se vuelve a ofrecer.

Antes, "Asignación de auditores" listaba toda solicitud Aprobada: el backend
no miraba `auditores_solicitud`, así que las que ya tenían auditor seguían
saliendo para asignar. La regla del dominio: varios auditores por solicitud
(líder, experto técnico, auditor integral, observador) pero un solo líder, que
es el único rol obligatorio. El equipo queda completo con un líder activo; las
solicitudes que solo tienen asignaciones canceladas vuelven a estar disponibles.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.asignacion_auditores import asignacion_service as servicio_mod
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from tests.fake_db import ResultadoFalso


def _plano(sql) -> str:
    return " ".join(str(sql).split())


class SesionGrabadora:
    """Devuelve respuestas en orden y guarda cada SQL ejecutado."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.sentencias: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, sentencia, parametros=None):
        self.sentencias.append(_plano(sentencia))
        if not self.respuestas:
            raise AssertionError("Consulta inesperada: " + self.sentencias[-1][:200])
        return self.respuestas.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class ResultadoConteo(ResultadoFalso):
    def scalar_one(self):
        return self._escalar


# ---------------------------------------------------------------- filtro


async def test_el_listado_excluye_solicitudes_con_auditor_lider_activo():
    fila = {"id_solicitud": uuid.uuid4(), "numero_radicado": "SOL-1", "auditores_asignados": 0}
    db = SesionGrabadora([ResultadoConteo(escalar=1), ResultadoFalso([fila])])

    respuesta = await AsignacionAuditorService(db).listar_solicitudes_aprobadas()

    assert respuesta["total"] == 1
    conteo, listado = db.sentencias
    for sql in (conteo, listado):
        # El conteo y el listado aplican el mismo filtro (el paginador cuadra).
        assert "NOT EXISTS ( SELECT 1 FROM auditores_solicitud a WHERE a.id_solicitud = s.id_solicitud" in sql
        assert "LOWER(TRIM(COALESCE(a.especialidad, ''))) IN ('auditor líder', 'auditor lider')" in sql
        assert "UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) IN" in sql
    # El listado informa cuántos auditores activos tiene cada solicitud.
    assert "AS auditores_asignados" in listado


def test_las_asignaciones_canceladas_no_cuentan_como_activas():
    activa = servicio_mod.SQL_ASIGNACION_ACTIVA
    # Comparación sin mayúsculas ni espacios y sin estados terminales.
    assert "UPPER(TRIM(" in activa
    for estado in ("CANCELADA", "CANCELADO", "REASIGNADO"):
        assert estado not in activa
    for estado in ("AGENDADA", "PROGRAMADA", "CONFIRMADO"):
        assert f"'{estado}'" in activa
    # El equipo completo exige estado activo Y rol líder.
    completo = servicio_mod.SQL_SOLICITUD_CON_EQUIPO_COMPLETO
    assert activa in completo and servicio_mod.SQL_ROL_LIDER in completo


@pytest.mark.parametrize(
    "estado, cuenta",
    [("Agendada", True), ("  programada ", True), ("Confirmado", True),
     ("Cancelada", False), ("CANCELADA", False), ("Reasignado", False)],
)
def test_estado_activo_se_evalua_como_en_postgres(estado, cuenta):
    """Reproduce en Python la condición SQL: UPPER(TRIM(estado)) IN (...)."""
    import re

    valores = re.findall(r"'([A-Z]+)'", servicio_mod.SQL_ASIGNACION_ACTIVA)
    assert (estado.strip().upper() in valores) is cuenta


# ---------------------------------------------------------------- 409


async def test_validar_equipo_incompleto_rechaza_con_409_si_ya_hay_lider():
    db = SesionGrabadora([ResultadoFalso([{"numero_radicado": "SOL-2026-0001", "lider_nombre": "Ana Auditora"}])])

    with pytest.raises(HTTPException) as error:
        await AsignacionAuditorService(db).validar_equipo_incompleto(uuid.uuid4())

    assert error.value.status_code == 409
    assert "SOL-2026-0001" in error.value.detail
    assert "Ana Auditora" in error.value.detail
    assert "ya tiene su equipo asignado" in error.value.detail


async def test_validar_equipo_incompleto_deja_pasar_si_no_hay_lider_activo():
    db = SesionGrabadora([ResultadoFalso([])])
    await AsignacionAuditorService(db).validar_equipo_incompleto(uuid.uuid4())


async def test_asignar_a_solicitud_completa_no_inserta_nada():
    db = SesionGrabadora([
        ResultadoFalso([]),  # sin programación activa
        ResultadoFalso([{"numero_radicado": "SOL-9", "lider_nombre": "Líder"}]),  # equipo completo
    ])
    data = servicio_mod.AsignacionAuditorCrear(
        id_solicitud=uuid.uuid4(), id_auditor=uuid.uuid4(), rol_auditor="Observador"
    )

    with pytest.raises(HTTPException) as error:
        await AsignacionAuditorService(db).asignar(data, usuario={})

    assert error.value.status_code == 409
    assert not any("INSERT INTO auditores_solicitud" in sql for sql in db.sentencias)
    assert db.commits == 0


async def test_post_asignacion_responde_409_por_la_api():
    db = SesionGrabadora([
        ResultadoFalso([]),
        ResultadoFalso([{"numero_radicado": "SOL-9", "lider_nombre": "Líder"}]),
    ])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"role_name": "Coordinador", "user_id": str(uuid.uuid4())}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            respuesta = await cliente.post(
                "/asignacion-auditores/",
                json={
                    "id_solicitud": str(uuid.uuid4()),
                    "id_auditor": str(uuid.uuid4()),
                    "rol_auditor": "Auditor líder",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 409
    assert "ya tiene su equipo asignado" in respuesta.json()["detail"]


# ---------------------------------------------------------------- listado de asignados


async def test_asignacion_cancelada_no_hereda_la_visita_de_otro_equipo():
    """El retest del 05/11 veía asignaciones canceladas como 'Confirmada'."""
    db = SesionGrabadora([ResultadoFalso([])])
    await AsignacionAuditorService(db).listar_asignaciones()
    sql = db.sentencias[0]
    assert "UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'REASIGNADO', 'REASIGNADA')" in sql
