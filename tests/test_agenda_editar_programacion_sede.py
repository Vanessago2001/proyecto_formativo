"""
Editar la programación de la sede seleccionada (Programar una auditoría, 18/11/2026).

  · La edición actualiza solo la fila ``id_programacion`` enviada y nunca
    cambia ``id_sede``.
  · Si el cliente envía ``id_solicitud``/``id_sede`` deben ser los de esa
    programación: con otra solicitud u otra sede responde 409 sin escribir
    (un formulario desincronizado no edita la visita de otra sede).
  · PUT /agenda-auditor/programacion/{id} pasa esos identificadores al
    servicio (422 si vienen mal formados); reprogramar valida lo mismo.
"""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

ID_PROG = uuid.uuid4()
SOLICITUD = uuid.uuid4()
OTRA_SOLICITUD = uuid.uuid4()
SEDE = uuid.uuid4()
OTRA_SEDE = uuid.uuid4()
AUDITOR = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


class SesionEditar:
    """Una programación de SOLICITUD en SEDE con un auditor activo."""

    def __init__(self):
        self.updates = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        if sql.startswith("SELECT id_programacion, id_solicitud, id_sede") or sql.startswith("SELECT id_solicitud, id_sede"):
            assert params["id"] == str(ID_PROG)
            return ResultadoFalso([{
                "id_programacion": ID_PROG, "id_solicitud": SOLICITUD, "id_sede": SEDE,
                "fecha_inicio": datetime(2026, 11, 20, 14, 55), "fecha_fin": datetime(2026, 11, 20, 17, 55),
                "estado": "Confirmada",
            }])
        if "FROM detalle_programacion_auditor d WHERE d.id_programacion" in sql:
            return ResultadoFalso([(str(AUDITOR),)])
        if "FROM usuario" in sql:
            return ResultadoFalso([{"estado": "Activo", "estado_auditor": "Activo", "nombre": "Milena"}])
        if sql.startswith("UPDATE programacion_visita"):
            self.updates.append((sql, params))
            return ResultadoFalso([(ID_PROG,)])
        raise AssertionError("Consulta inesperada: " + sql[:160])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def sin_efectos(monkeypatch):
    async def nada(self, *a, **k):
        return None

    monkeypatch.setattr(AgendaAuditorService, "verificar_franja_auditor", nada)
    monkeypatch.setattr(AgendaAuditorService, "_crear_notificacion", nada)


async def test_editar_aplica_a_la_programacion_de_la_sede_seleccionada(sin_efectos):
    db = SesionEditar()
    resultado = await AgendaAuditorService(db).editar_programacion(
        ID_PROG, "Remota", None,
        datetime(2026, 11, 27, 9), datetime(2026, 11, 27, 12),
        None, "Cambio pedido por la empresa",
        id_solicitud=SOLICITUD, id_sede=SEDE,
    )
    assert "reprogramada" in resultado["mensaje"].lower()
    assert len(db.updates) == 1 and db.commits == 1
    sql, params = db.updates[0]
    assert params["id"] == str(ID_PROG)                       # solo esa fila
    assert "WHERE id_programacion = :id" in sql
    assert "id_sede" not in sql                               # la sede no cambia
    assert params["fecha_inicio"] == datetime(2026, 11, 27, 9)
    assert params["modalidad"] == "Remota"


async def test_editar_sin_identificadores_sigue_funcionando(sin_efectos):
    db = SesionEditar()
    await AgendaAuditorService(db).editar_programacion(ID_PROG, "Híbrida", None)
    assert db.updates and db.updates[0][1]["id"] == str(ID_PROG) and db.commits == 1


@pytest.mark.parametrize("solicitud, sede, texto", [
    (SOLICITUD, OTRA_SEDE, "no corresponde a la sede seleccionada"),
    (OTRA_SOLICITUD, SEDE, "no pertenece a la solicitud seleccionada"),
])
async def test_editar_rechaza_otra_sede_u_otra_solicitud(sin_efectos, solicitud, sede, texto):
    db = SesionEditar()
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).editar_programacion(
            ID_PROG, "Remota", None, datetime(2026, 11, 27, 9), datetime(2026, 11, 27, 12),
            id_solicitud=solicitud, id_sede=sede,
        )
    assert error.value.status_code == 409
    assert texto in error.value.detail
    assert db.updates == [] and db.commits == 0 and db.rollbacks == 1


async def test_reprogramar_rechaza_otra_sede(sin_efectos):
    db = SesionEditar()
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).reprogramar_programacion(
            ID_PROG, datetime(2026, 11, 27, 9), datetime(2026, 11, 27, 12), "Cambio",
            id_solicitud=SOLICITUD, id_sede=OTRA_SEDE,
        )
    assert error.value.status_code == 409
    assert db.updates == [] and db.commits == 0


async def test_reprogramar_con_su_sede_actualiza_esa_programacion(sin_efectos):
    db = SesionEditar()
    await AgendaAuditorService(db).reprogramar_programacion(
        ID_PROG, datetime(2026, 11, 27, 9), datetime(2026, 11, 27, 12), "Cambio",
        id_solicitud=SOLICITUD, id_sede=SEDE,
    )
    assert db.updates[0][1]["id"] == str(ID_PROG) and db.commits == 1


async def _put(cuerpo):
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {"id_usuario": str(uuid.uuid4()), "role_name": "Coordinador"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await cliente.put(f"/agenda-auditor/programacion/{ID_PROG}", json=cuerpo)
    finally:
        app.dependency_overrides.clear()


async def test_put_envia_solicitud_y_sede_al_servicio(monkeypatch):
    recibido = {}

    async def falso(self, id_programacion, *args, **kwargs):
        recibido.update(id=id_programacion, args=args, **kwargs)
        return {"mensaje": "ok"}

    monkeypatch.setattr(AgendaAuditorService, "editar_programacion", falso)
    r = await _put({
        "modalidad": "Remota", "fecha_inicio": "2026-11-27T09:00:00", "fecha_fin": "2026-11-27T12:00:00",
        "observacion": "Cambio", "id_solicitud": str(SOLICITUD), "id_sede": str(SEDE),
    })
    assert r.status_code == 200, r.text
    assert recibido["id"] == ID_PROG
    assert recibido["id_solicitud"] == SOLICITUD and recibido["id_sede"] == SEDE
    assert recibido["args"][0] == "Remota"


async def test_put_rechaza_identificador_de_sede_invalido(monkeypatch):
    async def no_debe_llamarse(self, *a, **k):
        raise AssertionError("no debe editar")

    monkeypatch.setattr(AgendaAuditorService, "editar_programacion", no_debe_llamarse)
    r = await _put({"modalidad": "Remota", "id_sede": "no-es-uuid"})
    assert r.status_code == 422
    assert "id_sede" in r.json()["detail"]
