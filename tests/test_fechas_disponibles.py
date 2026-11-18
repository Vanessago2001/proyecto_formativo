"""
Regla única de disponibilidad para programar una auditoría (18/11/2026).

Pedido de la usuaria: "para programar una auditoría revise la disponibilidad
solo si hay días ocupados con visita o bloqueados; si el auditor no ha puesto
días disponibles se debe contar como si estuviera disponible hasta que el
auditor lo bloquee o lo ocupe con visita".

  · Sin declaración, con la vigencia vencida o fuera del horario declarado
    el auditor está DISPONIBLE.
  · Un día (o parte de la franja) bloqueado → no disponible, con el motivo.
  · Otra visita no cancelada ni finalizada que se cruce → no disponible.
  · Las sugerencias son las franjas sin bloqueos ni choques para todo el
    equipo, y cada una se confirma con `verificar_franja_auditor`, la misma
    función que usa programar.
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
TERMINALES = {"CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO"}


def semanal(dia, desde, hasta=None, hi=time(8), hf=time(17), estado="Activo"):
    return {"tipo_registro": "Horario Semanal", "dia_semana": dia,
            "fecha_inicio": datetime.combine(desde, time.min),
            "fecha_fin": datetime.combine(hasta, time.max) if hasta else None,
            "hora_inicio": hi, "hora_fin": hf, "estado": estado}


def bloqueo(dia_fecha, motivo="Cita médica", hi=None, hf=None, estado="Activo"):
    return {"tipo_registro": "Bloqueo Fecha", "dia_semana": dia_fecha.isoweekday(),
            "fecha_inicio": datetime.combine(dia_fecha, time.min),
            "fecha_fin": datetime.combine(dia_fecha, time.max),
            "hora_inicio": hi, "hora_fin": hf, "estado": estado, "motivo": motivo}


def _franja(fecha, hi, hf):
    return datetime.combine(fecha, hi), datetime.combine(fecha, hf)


# ------------------------------------------------------------ regla pura


def test_sin_declaracion_esta_disponible():
    assert fd.bloqueo_en_franja([], *_franja(date(2027, 2, 15), time(9), time(12))) is None
    assert fd.cubre_franja([], date(2027, 2, 15), time(9), time(12))


def test_vigencia_vencida_o_fuera_de_horario_no_restringe():
    vencida = [semanal(d, HOY, date(2026, 11, 30)) for d in range(1, 6)]
    assert fd.cubre_franja(vencida, date(2027, 2, 17), time(9), time(12))
    # Horario declarado 08:00–17:00 los miércoles: 06:00–20:00 un lunes también vale.
    assert fd.cubre_franja([semanal(3, HOY)], date(2027, 2, 15), time(6), time(20))
    assert fd.explicar_no_disponible(vencida, date(2027, 2, 17), time(9), time(12), "Leonel") is None


def test_dia_bloqueado_no_esta_disponible_y_el_motivo_lo_dice():
    fecha = date(2027, 2, 17)
    registros = [semanal(3, HOY), bloqueo(fecha)]
    assert not fd.cubre_franja(registros, fecha, time(9), time(12))
    assert fd.explicar_no_disponible(registros, fecha, time(9), time(12), "Ana") == (
        "Ana tiene bloqueado el 17/02/2027 (Cita médica)."
    )
    assert fd.cubre_franja(registros, fecha + timedelta(days=1), time(9), time(12))


def test_bloqueo_parcial_solo_choca_con_las_horas_que_toca():
    fecha = date(2027, 2, 17)
    registros = [bloqueo(fecha, "Médico", time(8), time(10))]
    assert not fd.cubre_franja(registros, fecha, time(9), time(11))
    assert fd.cubre_franja(registros, fecha, time(10), time(12))
    assert fd.explicar_no_disponible(registros, fecha, time(9), time(11), "Ana") == (
        "Ana tiene bloqueado el 17/02/2027 de 08:00 a 10:00 (Médico)."
    )


def test_bloqueo_inactivo_no_cuenta_y_visita_de_varios_dias_revisa_cada_dia():
    fecha = date(2027, 2, 17)
    assert fd.cubre_franja([bloqueo(fecha, estado="Inactivo")], fecha, time(9), time(12))
    inicio, fin = datetime(2027, 2, 16, 9), datetime(2027, 2, 18, 12)
    hallado = fd.bloqueo_en_franja([bloqueo(fecha)], inicio, fin)
    assert hallado and hallado[0] == fecha


def test_mensaje_de_choque_con_otra_visita():
    cruce = {"numero_radicado": "SOL-2026-0007", "fecha_inicio": datetime(2027, 2, 17, 8),
             "fecha_fin": datetime(2027, 2, 17, 12), "empresa_nombre": "Café del Eje"}
    assert fd.mensaje_cruce("Jairo", cruce) == "Jairo ya tiene la visita SOL-2026-0007 el 17/02/2027 de 08:00 a 12:00."


# ------------------------------------------------------------ función única


class SesionAgenda:
    """Base simulada: bloqueos, usuarios y visitas (aplica el filtro de estado
    y el de 'excluir' igual que el SQL real)."""

    def __init__(self, registros=(), visitas=(), usuarios=None):
        self.registros, self.visitas = list(registros), list(visitas)
        self.usuarios = usuarios or [
            {"id_usuario": i, "nombre": n, "estado": "Activo", "estado_auditor": "Activo"}
            for i, n in ((ANA, "Ana"), (LUIS, "Luis"))
        ]
        self.sql = []

    async def execute(self, sentencia, params=None):
        sql = " ".join(str(sentencia).split())
        params = params or {}
        self.sql.append(sql)
        assert not sql.upper().startswith(("INSERT", "UPDATE", "DELETE"))
        if "FROM usuario" in sql:
            if "ids" in params:
                return ResultadoFalso([u for u in self.usuarios if u["id_usuario"] in params["ids"]])
            return ResultadoFalso([u for u in self.usuarios if u["id_usuario"] == params["id_usuario"]])
        if "FROM disponibilidad_auditor" in sql:
            assert "'bloqueo fecha'" in sql and "horario semanal" not in sql
            return ResultadoFalso([r for r in self.registros if r["id_usuario"] in params["ids"]])
        if "FROM detalle_programacion_auditor" in sql:
            assert "NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')" in sql
            vigentes = [v for v in self.visitas if v.get("estado", "Programada").upper() not in TERMINALES
                        and str(v.get("id_programacion")) != str(params.get("excluir"))]
            if "id_usuario" in params:  # _buscar_cruce
                return ResultadoFalso([
                    v for v in vigentes if v["id_usuario"] == params["id_usuario"]
                    and v["fecha_inicio"] < params["fecha_fin"] and v["fecha_fin"] > params["fecha_inicio"]
                ][:1])
            return ResultadoFalso([v for v in vigentes if v["id_usuario"] in params["ids"]])
        raise AssertionError(sql[:120])


def _con(id_usuario, registro):
    return {**registro, "id_usuario": id_usuario}


def _visita(id_usuario, inicio, fin, estado="Programada", radicado="SOL-2026-0007"):
    return {"id_usuario": id_usuario, "id_programacion": uuid.uuid4(), "fecha_inicio": inicio,
            "fecha_fin": fin, "estado": estado, "numero_radicado": radicado, "empresa_nombre": "Empresa X"}


@pytest.mark.parametrize("registros", [
    [],                                                       # sin declaración
    [_con(ANA, semanal(3, HOY, date(2026, 11, 30)))],         # vigencia vencida
    [_con(ANA, semanal(1, HOY, hi=time(14), hf=time(16)))],   # fuera del horario declarado
])
async def test_verificar_franja_disponible_sin_restriccion_de_lo_declarado(registros):
    servicio = AgendaAuditorService(SesionAgenda(registros))
    assert await servicio.verificar_franja_auditor(ANA, datetime(2027, 2, 15, 9), datetime(2027, 2, 15, 12), None, "Ana") is None


async def test_verificar_franja_dia_bloqueado():
    db = SesionAgenda([_con(ANA, bloqueo(date(2027, 2, 15), "Vacaciones"))])
    r = await AgendaAuditorService(db).verificar_franja_auditor(
        ANA, datetime(2027, 2, 15, 9), datetime(2027, 2, 15, 12), None, "Ana")
    assert r["bloqueado"] is True and r["motivo"] == "Ana tiene bloqueado el 15/02/2027 (Vacaciones)."


async def test_verificar_franja_choque_con_otra_visita_y_excluir_la_propia():
    visita = _visita(ANA, datetime(2027, 2, 15, 10), datetime(2027, 2, 15, 14))
    servicio = AgendaAuditorService(SesionAgenda(visitas=[visita]))
    r = await servicio.verificar_franja_auditor(ANA, datetime(2027, 2, 15, 9), datetime(2027, 2, 15, 12), None, "Ana")
    assert r["ocupado"] is True
    assert r["motivo"] == "Ana ya tiene la visita SOL-2026-0007 el 15/02/2027 de 10:00 a 14:00."
    # Al editar esa misma visita no choca consigo misma.
    assert await servicio.verificar_franja_auditor(
        ANA, datetime(2027, 2, 15, 9), datetime(2027, 2, 15, 12), visita["id_programacion"], "Ana") is None


@pytest.mark.parametrize("estado", ["Cancelada", "Finalizada"])
async def test_visita_cancelada_o_finalizada_no_bloquea(estado):
    visita = _visita(ANA, datetime(2027, 2, 15, 10), datetime(2027, 2, 15, 14), estado=estado)
    servicio = AgendaAuditorService(SesionAgenda(visitas=[visita]))
    assert await servicio.verificar_franja_auditor(ANA, datetime(2027, 2, 15, 9), datetime(2027, 2, 15, 12)) is None


async def test_comprobar_disponibilidad_usa_la_regla_unica():
    db = SesionAgenda([_con(ANA, bloqueo(date(2027, 2, 16), "Cita médica"))])
    servicio = AgendaAuditorService(db)
    f = date(2027, 2, 15)
    libre = await servicio.consultar_disponibilidad(ANA, f, datetime.combine(f, time(6)), datetime.combine(f, time(20)))
    assert libre["disponible"] is True and "sin bloqueos ni otras visitas" in libre["motivo"]
    f = date(2027, 2, 16)
    r = await servicio.consultar_disponibilidad(ANA, f, datetime.combine(f, time(9)), datetime.combine(f, time(12)))
    assert r == {**r, "disponible": False, "bloqueado": True,
                 "motivo": "Ana tiene bloqueado el 16/02/2027 (Cita médica)."}


# ------------------------------------------------------------ sugerencias


async def test_sin_declaracion_sugiere_los_dias_siguientes_con_la_hora_pedida():
    servicio = AgendaAuditorService(SesionAgenda())
    r = await fd.sugerir_fechas(servicio, [ANA, LUIS], hora_inicio=time(9), hora_fin=time(12), hoy=HOY, limite=3)
    assert [(o["fecha"], o["hora_inicio"], o["hora_fin"]) for o in r["opciones"]] == [
        ("2026-11-18", "09:00", "12:00"), ("2026-11-19", "09:00", "12:00"), ("2026-11-20", "09:00", "12:00")]
    assert all(a["motivo"] is None for a in r["auditores"])


async def test_sugerencias_saltan_bloqueos_y_choques_de_cualquiera_del_equipo():
    db = SesionAgenda(
        [_con(ANA, bloqueo(date(2026, 11, 18), "Viaje")), _con(LUIS, semanal(1, HOY, date(2026, 11, 20)))],
        visitas=[_visita(LUIS, datetime(2026, 11, 19, 9), datetime(2026, 11, 19, 11)),
                 _visita(LUIS, datetime(2026, 11, 20, 9), datetime(2026, 11, 20, 11), estado="Cancelada")],
    )
    servicio = AgendaAuditorService(db)
    llamadas = []
    original = servicio.verificar_franja_auditor

    async def espia(*a, **k):
        llamadas.append(a[:3])
        return await original(*a, **k)

    servicio.verificar_franja_auditor = espia
    r = await fd.sugerir_fechas(servicio, [ANA, LUIS], hora_inicio=time(9), hora_fin=time(11), hoy=HOY, limite=3)
    assert [(o["fecha"], o["hora_inicio"]) for o in r["opciones"]] == [
        ("2026-11-19", "11:00"),   # 18: Ana bloqueada; 19: Luis ocupado 09–11 → tras la visita
        ("2026-11-20", "09:00"),   # la visita cancelada no ocupa
        ("2026-11-21", "09:00"),
    ]
    # Cada opción se confirmó, para cada auditor, con la función de programar.
    for o in r["opciones"]:
        inicio = datetime.fromisoformat(f"{o['fecha']}T{o['hora_inicio']}")
        for i in (ANA, LUIS):
            assert (i, inicio, inicio + timedelta(hours=2)) in llamadas


async def test_tres_meses_despues_sin_declaracion_esta_disponible():
    servicio = AgendaAuditorService(SesionAgenda())
    r = await fd.sugerir_fechas(servicio, [ANA], desde=date(2027, 2, 15), hasta=date(2027, 2, 17), hoy=HOY)
    assert [o["fecha"] for o in r["opciones"]] == ["2027-02-15", "2027-02-16", "2027-02-17"]
    assert r["duracion_minutos"] == 240 and r["opciones"][0]["hora_inicio"] == "08:00"


async def test_si_la_validacion_real_rechaza_no_se_ofrece():
    servicio = AgendaAuditorService(SesionAgenda())
    rechazada = date(2026, 11, 18)

    async def validar(i, inicio, fin, excluir=None, nombre=None):
        return {"motivo": "x"} if inicio.date() == rechazada else None

    servicio.verificar_franja_auditor = validar
    r = await fd.sugerir_fechas(servicio, [ANA], hora_inicio=time(9), hora_fin=time(10), hoy=HOY, limite=2)
    assert rechazada.isoformat() not in [o["fecha"] for o in r["opciones"]]
    assert len(r["opciones"]) == 2


async def test_sin_opciones_explica_solo_causas_reales():
    desde = date(2027, 2, 1)
    db = SesionAgenda([_con(ANA, {**bloqueo(desde, "Licencia"), "fecha_fin": datetime(2027, 3, 31, 23, 59)})])
    r = await fd.sugerir_fechas(AgendaAuditorService(db), [ANA, LUIS], desde=desde, hasta=date(2027, 2, 10), hoy=HOY)
    assert r["opciones"] == []
    motivos = {a["nombre"]: a["motivo"] for a in r["auditores"]}
    assert "bloqueados u ocupados" in motivos["Ana"] and motivos["Luis"] is None
    texto = " ".join(filter(None, motivos.values())) + r["mensaje"]
    assert "declar" not in texto and "vence" not in texto


async def test_auditor_no_aprobado_no_recibe_sugerencias():
    db = SesionAgenda(usuarios=[{"id_usuario": ANA, "nombre": "Ana", "estado": "Activo", "estado_auditor": "Postulante"}])
    r = await fd.sugerir_fechas(AgendaAuditorService(db), [ANA], hoy=HOY)
    assert r["opciones"] == []
    assert "no está activo/aprobado" in r["auditores"][0]["motivo"]


async def test_rango_maximo_180_dias_y_horas_invertidas():
    servicio = AgendaAuditorService(SesionAgenda())
    r = await fd.sugerir_fechas(servicio, [ANA], desde=HOY, hasta=HOY + timedelta(days=400), hoy=HOY, limite=1)
    assert r["hasta"] == (HOY + timedelta(days=180)).isoformat()
    with pytest.raises(HTTPException):
        await fd.sugerir_fechas(servicio, [ANA], hora_inicio=time(12), hora_fin=time(9), hoy=HOY)


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


# ------------------------------------------------------------ otros filtros con la misma regla


async def test_candidatos_por_sede_solo_descarta_bloqueados_en_la_franja():
    """`listar_auditores_disponibles_para_sede` aplica la regla en bloque."""
    fecha = date(2027, 2, 15)
    db = SesionAgenda([_con(ANA, bloqueo(fecha, "Viaje")), _con(LUIS, semanal(3, HOY, date(2026, 11, 30)))])
    bloqueados = await AgendaAuditorService(db)._ids_bloqueados([ANA, LUIS], *_franja(fecha, time(9), time(12)))
    assert bloqueados == {ANA}  # Luis con la vigencia vencida sigue disponible




# ---------------------------------------------------------------
# 18/11/2026: hora mínima de inicio ("Buscar visitas desde las") y
# búsqueda en todos los días de la semana.
# ---------------------------------------------------------------

def test_inicios_candidatos_respeta_la_hora_minima():
    from datetime import date, time, timedelta
    from modules.agenda_auditor.fechas_disponibles import _inicios_candidatos

    sabado = date(2027, 2, 20)  # sábado: también se busca
    horas = _inicios_candidatos(sabado, timedelta(hours=2), None, [[]], [], minima=time(10, 0))
    assert horas and min(horas) >= time(10, 0)

    # Una hora preferida anterior a la mínima no se ofrece.
    horas = _inicios_candidatos(sabado, timedelta(hours=2), time(7, 0), [[]], [], minima=time(9, 30))
    assert time(7, 0) not in horas and min(horas) >= time(9, 30)


def test_sin_hora_minima_empieza_en_la_jornada():
    from datetime import date, timedelta
    from modules.agenda_auditor.fechas_disponibles import HORA_JORNADA, _inicios_candidatos

    domingo = date(2027, 2, 21)
    horas = _inicios_candidatos(domingo, timedelta(hours=4), None, [[]], [])
    assert horas[0] == HORA_JORNADA
