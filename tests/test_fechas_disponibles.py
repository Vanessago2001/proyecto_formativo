"""
Programar una auditoría: por qué un auditor "no está disponible" y qué
fechas sí lo están.

Caso real (17/11/2026): una fecha a ~3 meses se rechazaba sin explicación
porque el auditor solo tenía vigente un horario semanal de miércoles y el
resto de su disponibilidad vencía antes. La regla de disponibilidad era
correcta; ahora el mensaje dice el motivo y la pantalla ofrece fechas.
"""

import uuid
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.agenda_auditor import fechas_disponibles as fd
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

HOY = date(2026, 11, 17)  # martes
ANA, LUIS = str(uuid.uuid4()), str(uuid.uuid4())


def semanal(dia, desde, hasta=None, hi=time(8), hf=time(17), estado="Activo"):
    return {"tipo_registro": "Horario Semanal", "dia_semana": dia,
            "fecha_inicio": datetime.combine(desde, time.min),
            "fecha_fin": datetime.combine(hasta, time.max) if hasta else None,
            "hora_inicio": hi, "hora_fin": hf, "estado": estado}


def bloqueo(dia_fecha, motivo="Cita médica"):
    return {"tipo_registro": "Bloqueo Fecha", "dia_semana": dia_fecha.isoweekday(),
            "fecha_inicio": datetime.combine(dia_fecha, time.min),
            "fecha_fin": datetime.combine(dia_fecha, time.max),
            "hora_inicio": None, "hora_fin": None, "estado": "Activo", "motivo": motivo}


# ------------------------------------------------------------ regla pura


@pytest.mark.parametrize("offset", range(7))
def test_cada_dia_de_la_semana_usa_iso_lunes_1(offset):
    fecha = date(2027, 2, 15) + timedelta(days=offset)  # lunes 15/02/2027
    registros = [semanal(fecha.isoweekday(), HOY)]
    assert fd.cubre_franja(registros, fecha, time(9), time(12))
    otro = [semanal(fecha.isoweekday() % 7 + 1, HOY)]
    assert not fd.cubre_franja(otro, fecha, time(9), time(12))


def test_domingo_guardado_como_cero_cuenta():
    assert fd.cubre_franja([semanal(0, HOY)], date(2027, 2, 21), time(9), time(12))


@pytest.mark.parametrize("fecha", [HOY + timedelta(days=7), HOY + timedelta(days=91)])
def test_vigencia_abierta_cubre_una_semana_y_tres_meses(fecha):
    registros = [semanal(fecha.isoweekday(), HOY)]
    assert fd.cubre_franja(registros, fecha, time(9), time(12))


def test_vigencia_vencida_no_cubre_y_el_motivo_dice_la_fecha():
    registros = [semanal(d, HOY, date(2026, 11, 30)) for d in range(1, 6)]
    fecha = date(2027, 2, 17)
    assert fd.cubre_franja(registros, HOY + timedelta(days=7), time(9), time(12))
    assert not fd.cubre_franja(registros, fecha, time(9), time(12))
    motivo = fd.explicar_no_disponible(registros, fecha, time(9), time(12), "Leonel")
    assert motivo.startswith("La disponibilidad declarada de Leonel vence el 30/11/2026")


def test_motivo_dia_no_declarado_lista_los_dias_vigentes():
    registros = [semanal(3, HOY), semanal(1, HOY, date(2026, 11, 27))]
    motivo = fd.explicar_no_disponible(registros, date(2027, 2, 15), time(9), time(12), "Leonel")
    assert "no declaró disponibilidad los lunes" in motivo and "miércoles" in motivo


def test_motivo_horas_fuera_y_bloqueo_y_sin_declarar():
    fecha = date(2027, 2, 17)
    assert "08:00–17:00" in fd.explicar_no_disponible([semanal(3, HOY)], fecha, time(7), time(12), "Ana")
    m = fd.explicar_no_disponible([semanal(3, HOY), bloqueo(fecha)], fecha, time(9), time(12), "Ana")
    assert "no disponible (Cita médica)" in m
    assert "no ha declarado disponibilidad" in fd.explicar_no_disponible([], fecha, time(9), time(12), "Ana")
    assert fd.explicar_no_disponible([semanal(3, HOY)], fecha, time(9), time(12), "Ana") is None


def test_registros_cancelados_y_horas_como_texto():
    r = semanal(3, HOY, estado="Cancelado")
    assert not fd.cubre_franja([r], date(2026, 11, 25), time(9), time(12))
    r = {**semanal(3, HOY), "hora_inicio": "08:00:00", "hora_fin": "17:00:00", "estado": " activa "}
    assert fd.cubre_franja([r], date(2026, 11, 25), time(9), time(12))


# ------------------------------------------------------------ sugerencias


class Sesion:
    def __init__(self, registros, ocupaciones=(), usuarios=None):
        self.registros, self.ocupaciones = registros, list(ocupaciones)
        self.usuarios = usuarios or [
            {"id_usuario": i, "nombre": n, "estado": "Activo", "estado_auditor": "Activo"}
            for i, n in ((ANA, "Ana"), (LUIS, "Luis"))
        ]
        self.sql = []

    async def execute(self, sentencia, params=None):
        sql = " ".join(str(sentencia).split())
        self.sql.append(sql)
        assert not sql.upper().startswith(("INSERT", "UPDATE", "DELETE"))
        if "FROM usuario" in sql:
            return ResultadoFalso([u for u in self.usuarios if u["id_usuario"] in params["ids"]])
        if "FROM disponibilidad_auditor" in sql:
            return ResultadoFalso([r for r in self.registros if r["id_usuario"] in params["ids"]])
        if "FROM detalle_programacion_auditor" in sql:
            return ResultadoFalso(self.ocupaciones)
        raise AssertionError(sql[:120])


def _servicio(db, validar=None):
    """Servicio con las validaciones reales de programar simuladas."""
    servicio = AgendaAuditorService(db)
    validar = validar or (lambda i, f, hi, hf: fd.cubre_franja(
        [r for r in db.registros if r["id_usuario"] == str(i)], f, hi, hf))
    llamadas = []

    async def tiene(i, f, hi, hf):
        llamadas.append(("disp", str(i), f, hi, hf))
        return validar(i, f, hi, hf)

    async def cruce(i, ini, fin, excluir=None):
        llamadas.append(("cruce", str(i), ini, fin))
        return next(({"x": 1} for o in db.ocupaciones
                     if o["id_usuario"] == str(i) and o["fecha_inicio"] < fin and o["fecha_fin"] > ini), None)

    servicio._tiene_disponibilidad_fecha = tiene
    servicio._buscar_cruce = cruce
    return servicio, llamadas


def _con(id_usuario, registro):
    return {**registro, "id_usuario": id_usuario}


async def test_sugiere_solo_dias_comunes_y_cada_opcion_pasa_la_validacion_de_programar():
    db = Sesion([_con(ANA, semanal(3, HOY)), _con(ANA, semanal(5, HOY)),
                 _con(LUIS, semanal(3, HOY, hi=time(10), hf=time(18)))])
    servicio, llamadas = _servicio(db)
    r = await fd.sugerir_fechas(servicio, [ANA, LUIS], hora_inicio=time(9), hora_fin=time(12), hoy=HOY, limite=5)
    assert [o["dia_semana"] for o in r["opciones"]] == ["miércoles"] * 5
    # A las 09:00 Luis no puede: se propone su primera hora común (10:00).
    assert r["opciones"][0] == {**r["opciones"][0], "fecha": "2026-11-18", "hora_inicio": "10:00", "hora_fin": "13:00"}
    # Cada opción devuelta se confirmó con las funciones de crear_programacion.
    for op in r["opciones"]:
        f = date.fromisoformat(op["fecha"])
        for i in (ANA, LUIS):
            assert ("disp", i, f, time(10), time(13)) in llamadas


async def test_respeta_la_hora_preferida_bloqueos_y_choques():
    miercoles = date(2026, 11, 18)
    db = Sesion(
        [_con(ANA, semanal(3, HOY)), _con(ANA, bloqueo(miercoles + timedelta(days=7)))],
        ocupaciones=[{"id_usuario": ANA, "fecha_inicio": datetime(2026, 12, 2, 9),
                      "fecha_fin": datetime(2026, 12, 2, 11)}],
    )
    servicio, _ = _servicio(db)
    r = await fd.sugerir_fechas(servicio, [ANA], hora_inicio=time(9), hora_fin=time(11), hoy=HOY, limite=3)
    assert [(o["fecha"], o["hora_inicio"]) for o in r["opciones"]] == [
        ("2026-11-18", "09:00"),       # hora pedida
        ("2026-12-02", "11:00"),       # 25/11 bloqueado; el 02/12 tras la otra visita
        ("2026-12-09", "09:00"),
    ]


async def test_tres_meses_despues_con_vigencia_abierta():
    db = Sesion([_con(ANA, semanal(1, HOY))])
    servicio, _ = _servicio(db)
    r = await fd.sugerir_fechas(servicio, [ANA], desde=date(2027, 2, 15), hasta=date(2027, 3, 1), hoy=HOY)
    assert [o["fecha"] for o in r["opciones"]] == ["2027-02-15", "2027-02-22", "2027-03-01"]
    assert r["duracion_minutos"] == 240


async def test_si_la_validacion_real_rechaza_no_se_ofrece():
    db = Sesion([_con(ANA, semanal(3, HOY))])
    rechazada = date(2026, 11, 18)
    servicio, _ = _servicio(db, validar=lambda i, f, hi, hf: f != rechazada)
    r = await fd.sugerir_fechas(servicio, [ANA], hora_inicio=time(9), hora_fin=time(10), hoy=HOY, limite=2)
    assert rechazada.isoformat() not in [o["fecha"] for o in r["opciones"]]
    assert len(r["opciones"]) == 2


async def test_sin_opciones_explica_por_auditor():
    db = Sesion(
        [_con(ANA, semanal(3, HOY, date(2026, 11, 30)))],
        usuarios=[{"id_usuario": ANA, "nombre": "Ana", "estado": "Activo", "estado_auditor": "Activo"},
                  {"id_usuario": LUIS, "nombre": "Luis", "estado": "Activo", "estado_auditor": "Activo"}],
    )
    servicio, _ = _servicio(db)
    r = await fd.sugerir_fechas(servicio, [ANA, LUIS], desde=date(2027, 2, 1), hoy=HOY)
    assert r["opciones"] == []
    motivos = {a["nombre"]: a["motivo"] for a in r["auditores"]}
    assert "vence el 30/11/2026" in motivos["Ana"]
    assert "no ha declarado disponibilidad" in motivos["Luis"]


async def test_auditor_no_aprobado_no_recibe_sugerencias():
    db = Sesion([_con(ANA, semanal(3, HOY))],
                usuarios=[{"id_usuario": ANA, "nombre": "Ana", "estado": "Activo", "estado_auditor": "Postulante"}])
    servicio, llamadas = _servicio(db)
    r = await fd.sugerir_fechas(servicio, [ANA], hoy=HOY)
    assert r["opciones"] == [] and llamadas == []
    assert "no está activo/aprobado" in r["auditores"][0]["motivo"]


async def test_rango_maximo_180_dias_y_horas_invertidas():
    servicio, _ = _servicio(Sesion([]))
    r = await fd.sugerir_fechas(servicio, [ANA], desde=HOY, hasta=HOY + timedelta(days=400), hoy=HOY)
    assert r["hasta"] == (HOY + timedelta(days=180)).isoformat()
    with pytest.raises(HTTPException):
        await fd.sugerir_fechas(servicio, [ANA], hora_inicio=time(12), hora_fin=time(9), hoy=HOY)


# ------------------------------------------------------------ mensajes al programar


async def test_comprobar_disponibilidad_dice_el_motivo(monkeypatch):
    class SesionMotivo:
        async def execute(self, sentencia, params=None):
            sql = " ".join(str(sentencia).split())
            if "FROM usuario" in sql:
                return ResultadoFalso([{"estado": "Activo", "estado_auditor": "Activo", "nombre": "Leonel"}])
            if "FROM disponibilidad_auditor" in sql:
                return ResultadoFalso([{**semanal(3, HOY), "id_usuario": ANA}])
            raise AssertionError(sql[:100])

    async def no(self, *a, **k):
        return False

    async def sin_cruce(self, *a, **k):
        return None

    monkeypatch.setattr(AgendaAuditorService, "_tiene_disponibilidad_fecha", no)
    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", sin_cruce)
    f = date(2027, 2, 15)
    r = await AgendaAuditorService(SesionMotivo()).consultar_disponibilidad(
        ANA, f, datetime.combine(f, time(9)), datetime.combine(f, time(12)))
    assert r["disponible"] is False
    assert r["motivo"].startswith("Leonel no declaró disponibilidad los lunes")


# ------------------------------------------------------------ endpoint


async def test_endpoint_solo_coordinador_y_pasa_parametros(monkeypatch):
    recibido = {}

    async def falso(self, auditores, **opciones):
        recibido.update(opciones, auditores=[str(a) for a in auditores])
        return {"opciones": []}

    monkeypatch.setattr(AgendaAuditorService, "sugerir_fechas_disponibles", falso)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        for rol, esperado in (("Coordinador", 200), ("Auditor", 403)):
            app.dependency_overrides[get_current_user] = lambda rol=rol: {"id_usuario": str(uuid.uuid4()), "role_name": rol}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
                r = await cliente.get("/agenda-auditor/programacion/fechas-disponibles", params=[
                    ("auditores", ANA), ("auditores", LUIS), ("hora_inicio", "09:00"), ("hora_fin", "12:00")])
            assert r.status_code == esperado, r.text
    finally:
        app.dependency_overrides.clear()
    assert recibido["auditores"] == [ANA, LUIS]
    assert recibido["hora_inicio"] == time(9) and recibido["limite"] == 10
