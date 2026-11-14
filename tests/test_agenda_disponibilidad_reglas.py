"""
Reglas de la agenda al programar y al configurar disponibilidad.

  · Solo el propio auditor crea/edita/elimina su disponibilidad semanal
    (403 para otros auditores y para el Coordinador).
  · Programar exige solicitud 'Aprobada' (canon de M5: el literal 'APROBADO'
    rechazaba toda programación real) y responde 409 con el nombre del
    auditor y el choque (otra auditoría, día bloqueado o fuera de horario).
  · Un hueco ocupado por una auditoría nunca se ofrece como libre, aunque el
    auditor haya declarado disponibilidad en él.
  · El horario semanal ('Horario Semanal') cuenta como disponibilidad.
"""

import uuid
from datetime import date, datetime, time

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.agenda_auditor.agenda_schema import DisponibilidadSemanalCrear, ProgramacionAuditoriaCrear
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

ID_AUDITOR = uuid.uuid4()
ID_SOLICITUD = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


# ---------------------------------------------------------------- 403


@pytest.fixture
def cliente_con(monkeypatch):
    llamadas = []

    async def falso_configurar(self, id_usuario, data):
        llamadas.append(str(id_usuario))
        return {"mensaje": "ok", "registros": [], "ocupados": []}

    async def falso_editar(self, id_usuario, id_disp, data):
        llamadas.append("editar")
        return {"mensaje": "ok"}

    async def falso_eliminar(self, id_usuario, id_disp):
        llamadas.append("eliminar")
        return {"mensaje": "ok"}

    monkeypatch.setattr(AgendaAuditorService, "configurar_disponibilidad_semanal", falso_configurar)
    monkeypatch.setattr(AgendaAuditorService, "editar_disponibilidad", falso_editar)
    monkeypatch.setattr(AgendaAuditorService, "eliminar_disponibilidad", falso_eliminar)

    def preparar(usuario):
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[get_current_user] = lambda: usuario
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    yield preparar, llamadas
    app.dependency_overrides.clear()


CUERPO_SEMANAL = {
    "fecha_inicio": "2099-01-05",
    "dias": [{"dia_semana": "lunes", "hora_inicio": "08:00", "hora_fin": "12:00"}],
}


async def test_el_auditor_configura_su_propia_disponibilidad(cliente_con):
    preparar, llamadas = cliente_con
    async with preparar({"id_usuario": str(ID_AUDITOR), "role_name": "Auditor"}) as cliente:
        r = await cliente.post(f"/agenda-auditor/{ID_AUDITOR}/disponibilidad-semanal", json=CUERPO_SEMANAL)
    assert r.status_code == 201, r.text
    assert llamadas == [str(ID_AUDITOR)]


async def test_otro_auditor_no_configura_disponibilidad_ajena(cliente_con):
    preparar, llamadas = cliente_con
    async with preparar({"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}) as cliente:
        r = await cliente.post(f"/agenda-auditor/{ID_AUDITOR}/disponibilidad-semanal", json=CUERPO_SEMANAL)
    assert r.status_code == 403
    assert llamadas == []


@pytest.mark.parametrize("rol", ["Coordinador", "Administrador"])
async def test_el_coordinador_solo_consulta_la_disponibilidad_semanal(cliente_con, rol):
    preparar, llamadas = cliente_con
    id_disp = uuid.uuid4()
    async with preparar({"id_usuario": str(uuid.uuid4()), "role_name": rol}) as cliente:
        crear = await cliente.post(f"/agenda-auditor/{ID_AUDITOR}/disponibilidad-semanal", json=CUERPO_SEMANAL)
        editar = await cliente.put(
            f"/agenda-auditor/{ID_AUDITOR}/disponibilidad/{id_disp}",
            json={"fecha_inicio": "2099-01-05", "hora_inicio": "08:00", "hora_fin": "12:00"},
        )
        eliminar = await cliente.delete(f"/agenda-auditor/{ID_AUDITOR}/disponibilidad/{id_disp}")
    assert (crear.status_code, editar.status_code, eliminar.status_code) == (403, 403, 403)
    assert "propio auditor" in crear.json()["detail"]
    assert llamadas == []


# ---------------------------------------------------------------- programar: 409


class SesionProgramar:
    """Responde según la consulta de crear_programacion."""

    def __init__(self, estado_solicitud="Aprobada"):
        self.estado = estado_solicitud
        self.sentencias = []
        self.rollbacks = 0

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append(sql)
        if "FROM solicitud s WHERE s.id_solicitud" in sql:
            return ResultadoFalso([{"id_solicitud": ID_SOLICITUD, "estado": self.estado, "id_empresa": uuid.uuid4()}])
        if "FROM programacion_visita p LEFT JOIN solicitud" in sql:
            return ResultadoFalso([])  # sede libre
        if "FROM usuario WHERE id_usuario" in sql:
            return ResultadoFalso([{"id_usuario": ID_AUDITOR, "nombre": "Ana Auditora", "estado": "Activo", "estado_auditor": "Activo"}])
        if "FROM auditores_solicitud" in sql:
            return ResultadoFalso([{"especialidad": "Auditor líder", "estado_asignacion": "Agendada"}])
        raise AssertionError("Consulta inesperada: " + sql[:160])

    async def commit(self):
        raise AssertionError("No debe confirmar nada cuando hay choque.")

    async def rollback(self):
        self.rollbacks += 1


def _datos():
    return ProgramacionAuditoriaCrear(
        id_solicitud=ID_SOLICITUD,
        auditores=[{"id_usuario": str(ID_AUDITOR), "rol_auditor": "Auditor líder"}],
        direccion_servicio="Calle 1 # 2-3",
        ciudad_servicio="Pereira",
        fecha_inicio=datetime(2099, 1, 7, 9, 0),
        fecha_fin=datetime(2099, 1, 7, 11, 0),
    )


async def test_programar_rechaza_choque_con_otra_auditoria(monkeypatch):
    async def disponible(self, *a, **k):
        return True

    async def cruce(self, *a, **k):
        return {"fecha_inicio": datetime(2099, 1, 7, 8, 0), "fecha_fin": datetime(2099, 1, 7, 12, 0), "empresa_nombre": "Café del Eje"}

    monkeypatch.setattr(AgendaAuditorService, "_tiene_disponibilidad_fecha", disponible)
    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", cruce)
    db = SesionProgramar()
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).crear_programacion(_datos())
    assert error.value.status_code == 409
    detalle = error.value.detail
    assert isinstance(detalle, str)  # antes era un dict y la pantalla mostraba JSON
    assert "Ana Auditora" in detalle and "07/01/2099 de 08:00 a 12:00" in detalle and "Café del Eje" in detalle


async def test_programar_rechaza_dia_bloqueado_o_fuera_de_horario(monkeypatch):
    async def no_disponible(self, *a, **k):
        return False

    monkeypatch.setattr(AgendaAuditorService, "_tiene_disponibilidad_fecha", no_disponible)
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionProgramar()).crear_programacion(_datos())
    assert error.value.status_code == 409
    assert "Ana Auditora no tiene disponibilidad el 07/01/2099 de 09:00 a 11:00" in error.value.detail


@pytest.mark.parametrize("estado", ["Aprobada", "APROBADA", "Aprobado"])
async def test_programar_acepta_la_solicitud_aprobada_en_su_forma_canonica(monkeypatch, estado):
    """Con 'Aprobada' se llega a validar al auditor (antes: 409 'solicitud aprobada')."""
    async def no_disponible(self, *a, **k):
        return False

    monkeypatch.setattr(AgendaAuditorService, "_tiene_disponibilidad_fecha", no_disponible)
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionProgramar(estado)).crear_programacion(_datos())
    assert "solicitud aprobada" not in error.value.detail


async def test_programar_rechaza_solicitud_no_aprobada():
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(SesionProgramar("Radicada")).crear_programacion(_datos())
    assert error.value.status_code == 409
    assert "solicitud aprobada" in error.value.detail


async def test_la_sede_principal_solo_choca_con_visitas_de_la_misma_solicitud():
    class Sesion:
        sql = ""

        async def execute(self, sentencia, params=None):
            Sesion.sql = _plano(sentencia)
            return ResultadoFalso([])

    await AgendaAuditorService(Sesion()).\
        _validar_sede_disponible(ID_SOLICITUD, None, datetime(2099, 1, 7, 9), datetime(2099, 1, 7, 11))
    assert "p.id_solicitud = CAST(:id_solicitud AS UUID)" in Sesion.sql


# ---------------------------------------------------------------- ocupado != libre


class SesionUsuarioActivo:
    async def execute(self, sentencia, params=None):
        return ResultadoFalso([{"estado": "Activo", "estado_auditor": "Activo"}])


async def test_comprobar_disponibilidad_marca_ocupado_aunque_haya_horario_declarado(monkeypatch):
    async def declarado(self, *a, **k):
        return True

    async def cruce(self, *a, **k):
        return {"fecha_inicio": datetime(2099, 1, 7, 9), "fecha_fin": datetime(2099, 1, 7, 10), "empresa_nombre": "Empresa X"}

    monkeypatch.setattr(AgendaAuditorService, "_tiene_disponibilidad_fecha", declarado)
    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", cruce)
    r = await AgendaAuditorService(SesionUsuarioActivo()).consultar_disponibilidad(
        ID_AUDITOR, date(2099, 1, 7), datetime(2099, 1, 7, 9), datetime(2099, 1, 7, 11)
    )
    assert r["disponible"] is False and r["ocupado"] is True
    assert r["motivo"].startswith("Ocupado:") and "Empresa X" in r["motivo"]


async def test_el_horario_semanal_cuenta_como_disponibilidad():
    class Sesion:
        sql = ""

        async def execute(self, sentencia, params=None):
            Sesion.sql = _plano(sentencia)
            return ResultadoFalso(escalar=True)

    async def con_horas(self, tabla, columna):
        return True

    servicio = AgendaAuditorService(Sesion())
    servicio._tabla_tiene_columna = con_horas.__get__(servicio)
    await servicio._tiene_disponibilidad_fecha(ID_AUDITOR, date(2099, 1, 7), time(9), time(11))
    assert "'horario semanal'" in Sesion.sql


async def test_calendario_mensual_marca_ocupado_sobre_disponibilidad_declarada(monkeypatch):
    async def agenda(self, *a, **k):
        return [
            {"tipo_registro": "Horario Semanal", "dia_semana": 3, "fecha_inicio": datetime(2099, 1, 1),
             "fecha_fin": None, "hora_inicio": time(8), "hora_fin": time(17)},
            {"tipo_registro": "Bloqueo Fecha", "dia_semana": None, "fecha_inicio": datetime(2099, 1, 9),
             "fecha_fin": datetime(2099, 1, 9, 23, 59)},
        ]

    async def auditorias(self, *a, **k):
        return [{"fecha_inicio": datetime(2099, 1, 7, 9), "fecha_fin": datetime(2099, 1, 7, 11),
                 "estado": "Confirmada", "empresa_nombre": "Empresa X"}]

    monkeypatch.setattr(AgendaAuditorService, "consultar_agenda", agenda)
    monkeypatch.setattr(AgendaAuditorService, "consultar_auditorias_programadas", auditorias)
    r = await AgendaAuditorService(None).ver_disponibilidad_mensual(ID_AUDITOR, 2099, 1)
    dias = {d["fecha"]: d for d in r["dias"]}
    miercoles = dias["2099-01-07"]   # declarado y con auditoría
    assert miercoles["declarado"] and miercoles["ocupado"]
    assert dias["2099-01-14"]["declarado"] and not dias["2099-01-14"]["ocupado"]
    assert dias["2099-01-09"]["bloqueado"] and not dias["2099-01-09"]["declarado"]


async def test_configurar_horario_avisa_las_franjas_ya_ocupadas(monkeypatch):
    async def auditorias(self, *a, **k):
        return [
            {"fecha_inicio": datetime(2099, 1, 7, 9), "fecha_fin": datetime(2099, 1, 7, 11), "estado": "Confirmada", "empresa_nombre": "Empresa X"},
            {"fecha_inicio": datetime(2099, 1, 8, 9), "fecha_fin": datetime(2099, 1, 8, 11), "estado": "Confirmada", "empresa_nombre": "Jueves no declarado"},
            {"fecha_inicio": datetime(2099, 1, 14, 9), "fecha_fin": datetime(2099, 1, 14, 11), "estado": "Cancelada", "empresa_nombre": "Cancelada"},
        ]

    monkeypatch.setattr(AgendaAuditorService, "consultar_auditorias_programadas", auditorias)
    data = DisponibilidadSemanalCrear(
        fecha_inicio=date(2099, 1, 5), fecha_fin=date(2099, 1, 31),
        dias=[{"dia_semana": "miércoles", "hora_inicio": "08:00", "hora_fin": "17:00"}],
    )
    ocupados = await AgendaAuditorService(None)._franjas_ocupadas_en_horario(ID_AUDITOR, data)
    assert ocupados == [{"fecha": "2099-01-07", "hora_inicio": "09:00", "hora_fin": "11:00",
                         "empresa_nombre": "Empresa X", "numero_radicado": None}]
