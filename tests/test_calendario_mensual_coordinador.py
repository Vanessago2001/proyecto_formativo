"""
Calendario mensual del Coordinador y bloqueo automático por auditorías.

  · /agenda-auditor/disponibilidad-mensual-general devuelve UNA entrada por
    programación (antes una por auditor y el calendario repetía la visita),
    con equipo, sede, NIT y observaciones; cada día lista las programaciones
    que lo cubren (visitas de varios días incluidas, recortadas al mes).
  · Filtros: auditor (con su disponibilidad y bloqueos por día), ciudad y
    modalidad sin distinguir tildes, canceladas solo si se piden.
  · Las fechas con una auditoría no cancelada quedan bloqueadas para cada
    auditor del equipo sin registro manual: todo sale de consultas sobre
    programacion_visita, de modo que reprogramar mueve el bloqueo y cancelar
    lo libera.
"""

import uuid
from datetime import date, datetime, time

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

ID_PROG = uuid.uuid4()
ID_PROG_2 = uuid.uuid4()
ANA = uuid.uuid4()
LUIS = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


def _fila(id_prog, id_usuario, nombre, rol, **extra):
    base = {
        "id_programacion": id_prog, "id_solicitud": uuid.uuid4(), "id_sede": uuid.uuid4(),
        "fecha_inicio": datetime(2026, 10, 28, 8, 0), "fecha_fin": datetime(2026, 11, 3, 16, 0),
        "modalidad": "Presencial", "ciudad_servicio": "Bogotá", "estado_programacion": "Confirmada",
        "direccion_servicio": None, "motivo_reprogramacion": None, "motivo_cancelacion": None,
        "observaciones_finalizacion": None, "estado_solicitud_reprogramacion": None,
        "motivo_solicitud_reprogramacion": None, "notificacion_enviada": True,
        "numero_radicado": "SOL-2026-0003", "estado_solicitud": "Aprobada",
        "id_empresa": uuid.uuid4(), "empresa_nombre": "Café del Eje", "empresa_nit": "900123",
        "empresa_direccion": "Calle 1", "empresa_ciudad": "Pereira",
        "sede_nombre": "Sede norte", "sede_direccion": "Carrera 8 # 20-45", "sede_ciudad": "Bogotá",
        "id_usuario": id_usuario, "rol_auditor": rol, "confirmado": False,
        "auditor_nombre": nombre, "auditor_correo": f"{nombre.lower()}@x.co",
    }
    base.update(extra)
    return base


class SesionMes:
    """Devuelve disponibilidad y programaciones según la consulta."""

    def __init__(self, disponibilidad=None, programaciones=None, activos=None):
        self.disponibilidad = disponibilidad or []
        self.programaciones = programaciones or []
        # Auditores activos y aprobados (los que pueden estar disponibles).
        self.activos = activos if activos is not None else [
            {"id_usuario": ANA, "nombre": "Ana"}, {"id_usuario": LUIS, "nombre": "Luis"}]
        self.sql = []
        self.params = []

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sql.append(sql)
        self.params.append(params or {})
        if "FROM disponibilidad_auditor da" in sql:
            return ResultadoFalso(self.disponibilidad)
        if "FROM programacion_visita p" in sql:
            return ResultadoFalso(self.programaciones)
        if "FROM usuario u WHERE" in sql:
            assert "estado_auditor" in sql
            return ResultadoFalso(self.activos)
        raise AssertionError("Consulta inesperada: " + sql[:160])


def _programaciones_base():
    return [
        _fila(ID_PROG, LUIS, "Luis", "Observador"),
        _fila(ID_PROG, ANA, "Ana", "Auditor Líder", confirmado=True),
        _fila(ID_PROG_2, ANA, "Ana", "Auditor Líder", fecha_inicio=datetime(2026, 11, 20, 9),
              fecha_fin=datetime(2026, 11, 20, 12), modalidad="Remota", ciudad_servicio="Pereira",
              sede_nombre=None, sede_ciudad=None, direccion_servicio="Calle 99"),
    ]


async def test_una_entrada_por_programacion_con_equipo_y_dias_de_la_visita():
    db = SesionMes(programaciones=_programaciones_base())
    r = await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11)

    assert [str(a["id_programacion"]) for a in r["auditorias"]] == [str(ID_PROG), str(ID_PROG_2)]
    visita = r["auditorias"][0]
    # Rol único "Auditor": el equipo va por nombre y los roles viejos se leen
    # como "Auditor"; datos de sede y NIT para el detalle.
    assert [(e["nombre"], e["rol_auditor"]) for e in visita["equipo"]] == [("Ana", "Auditor"), ("Luis", "Auditor")]
    assert visita["equipo"][0]["confirmado"] is True
    assert visita["sede_nombre"] == "Sede norte" and visita["empresa_nit"] == "900123"
    assert visita["direccion"] == "Carrera 8 # 20-45"  # sin dirección propia: la de la sede
    assert "auditor_nombre" not in visita

    dias = {d["fecha"]: d for d in r["dias"]}
    assert len(dias) == 30
    # Visita del 28/10 al 03/11: ocupa del 1 al 3 de noviembre (recortada al mes).
    for f in ("2026-11-01", "2026-11-02", "2026-11-03"):
        assert dias[f]["auditorias"] == [str(ID_PROG)] and dias[f]["ocupado"]
    assert dias["2026-11-04"]["auditorias"] == []
    assert dias["2026-11-20"]["auditorias"] == [str(ID_PROG_2)]
    # Las canceladas no aparecen salvo que se pidan; las finalizadas sí.
    sql_prog = next(s for s in db.sql if "FROM programacion_visita p" in s)
    assert "NOT IN ('CANCELADA', 'CANCELADO')" in sql_prog
    assert "FINALIZADA" not in sql_prog


async def test_incluir_canceladas_quita_el_filtro_de_estado():
    db = SesionMes(programaciones=[])
    await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11, incluir_canceladas=True)
    sql_prog = next(s for s in db.sql if "FROM programacion_visita p" in s)
    assert "CANCELADA" not in sql_prog


@pytest.mark.parametrize("ciudad, modalidad, esperadas", [
    ("bogota", None, [ID_PROG]),          # sin tilde encuentra 'Bogotá'
    ("PEREIRA", None, [ID_PROG_2]),
    (None, "remota", [ID_PROG_2]),
    (None, "Híbrida", []),
])
async def test_filtros_de_ciudad_y_modalidad_sin_tildes(ciudad, modalidad, esperadas):
    db = SesionMes(programaciones=_programaciones_base())
    r = await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11, ciudad=ciudad, modalidad=modalidad)
    assert [a["id_programacion"] for a in r["auditorias"]] == esperadas
    if not esperadas:
        assert all(d["auditorias"] == [] for d in r["dias"])


async def test_con_auditor_filtra_su_equipo_y_trae_disponibilidad_y_bloqueos():
    disponibilidad = [
        {"id_disponibilidad": 1, "id_usuario": ANA, "tipo_registro": "Horario Semanal", "dia_semana": 1,
         "fecha_inicio": datetime(2026, 11, 1), "fecha_fin": None, "hora_inicio": time(8), "hora_fin": time(17),
         "motivo": None, "estado": "Activo", "auditor_nombre": "Ana"},
        {"id_disponibilidad": 2, "id_usuario": ANA, "tipo_registro": "Bloqueo Fecha", "dia_semana": None,
         "fecha_inicio": datetime(2026, 11, 9), "fecha_fin": datetime(2026, 11, 9, 23, 59),
         "hora_inicio": None, "hora_fin": None, "motivo": "Cita médica", "estado": "Activo", "auditor_nombre": "Ana"},
    ]
    db = SesionMes(disponibilidad=disponibilidad, programaciones=_programaciones_base())
    r = await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11, id_usuario=ANA)

    assert not any("FROM usuario u WHERE" in sql for sql in db.sql)
    for sql, params in zip(db.sql, db.params):
        assert params["id_usuario"] == str(ANA)
        if "FROM programacion_visita p" in sql:
            assert "EXISTS (SELECT 1 FROM detalle_programacion_auditor dx" in sql
        else:
            assert "da.id_usuario = :id_usuario" in sql
    dias = {d["fecha"]: d for d in r["dias"]}
    lunes_2 = dias["2026-11-02"]
    assert lunes_2["declarado"] and lunes_2["ocupado"] and not lunes_2["bloqueado"]
    assert dias["2026-11-09"]["bloqueado"] and not dias["2026-11-09"]["declarado"]
    assert dias["2026-11-09"]["disponibilidad"][0]["motivo"] == "Cita médica"
    assert not dias["2026-11-04"]["declarado"]  # miércoles sin horario
    # Regla única: sin bloqueo ni visita está disponible aunque no declare nada.
    assert dias["2026-11-04"]["disponible"]
    assert not lunes_2["disponible"] and not dias["2026-11-09"]["disponible"]


async def test_sin_auditor_cuenta_disponibles_y_bloqueados_por_dia():
    disponibilidad = [
        {"id_disponibilidad": 1, "id_usuario": ANA, "tipo_registro": "Disponibilidad Extra", "dia_semana": None,
         "fecha_inicio": datetime(2026, 1, 1), "fecha_fin": datetime(2027, 12, 31), "hora_inicio": None,
         "hora_fin": None, "motivo": None, "estado": "Activo", "auditor_nombre": "Ana"},
        {"id_disponibilidad": 2, "id_usuario": LUIS, "tipo_registro": "Horario Semanal", "dia_semana": 5,
         "fecha_inicio": datetime(2026, 11, 1), "fecha_fin": None, "hora_inicio": time(8), "hora_fin": time(12),
         "motivo": None, "estado": "Activo", "auditor_nombre": "Luis"},
        {"id_disponibilidad": 3, "id_usuario": ANA, "tipo_registro": "Bloqueo Fecha", "dia_semana": None,
         "fecha_inicio": datetime(2026, 11, 13), "fecha_fin": datetime(2026, 11, 13, 23, 59),
         "hora_inicio": None, "hora_fin": None, "motivo": "x", "estado": "Activo", "auditor_nombre": "Ana"},
    ]
    db = SesionMes(disponibilidad=disponibilidad, programaciones=_programaciones_base())
    r = await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11)
    dias = {d["fecha"]: d for d in r["dias"]}
    # Regla única: cuentan todos los activos sin bloqueo ni visita ese día,
    # hayan declarado o no (Luis solo declaró los viernes).
    assert dias["2026-11-12"]["auditores_disponibles"] == 2
    assert dias["2026-11-12"]["nombres_disponibles"] == ["Ana", "Luis"]
    assert dias["2026-11-12"]["nombres_con_declaracion"] == ["Ana"]
    viernes_13 = dias["2026-11-13"]                                  # Ana bloqueó ese viernes
    assert viernes_13["auditores_disponibles"] == 1 and viernes_13["auditores_bloqueados"] == 1
    assert viernes_13["nombres_bloqueados"] == ["Ana"] and viernes_13["nombres_disponibles"] == ["Luis"]
    assert "disponibilidad" not in viernes_13
    # Días con visita: el equipo queda ocupado (01–03/11 Ana y Luis; 20/11 Ana).
    assert dias["2026-11-02"]["auditores_disponibles"] == 0 and dias["2026-11-02"]["auditores_ocupados"] == 2
    assert dias["2026-11-20"]["nombres_disponibles"] == ["Luis"]


async def test_sin_auditor_una_visita_cancelada_no_ocupa():
    canceladas = [_fila(ID_PROG, ANA, "Ana", "Auditor", estado_programacion="Cancelada")]
    r = await AgendaAuditorService(SesionMes(programaciones=canceladas)).ver_disponibilidad_mensual_general(
        2026, 11, incluir_canceladas=True)
    dias = {d["fecha"]: d for d in r["dias"]}
    assert dias["2026-11-02"]["auditorias"] == [str(ID_PROG)]          # se muestra
    assert dias["2026-11-02"]["auditores_disponibles"] == 2             # pero no ocupa


async def test_el_endpoint_pasa_auditor_y_canceladas_al_servicio(monkeypatch):
    recibido = {}

    async def falso(self, **kwargs):
        recibido.update(kwargs)
        return {"dias": [], "auditorias": []}

    monkeypatch.setattr(AgendaAuditorService, "ver_disponibilidad_mensual_general", falso)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {"id_usuario": str(uuid.uuid4()), "role_name": "Coordinador"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            r = await cliente.get(
                "/agenda-auditor/disponibilidad-mensual-general",
                params={"anio": 2026, "mes": 11, "id_usuario": str(ANA), "incluir_canceladas": "true", "ciudad": "Bogotá"},
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert recibido == {"anio": 2026, "mes": 11, "ciudad": "Bogotá", "modalidad": None,
                        "id_usuario": ANA, "incluir_canceladas": True}


# ------------------------------------------------- bloqueo automático por auditorías


class SesionSql:
    def __init__(self, filas=None):
        self.sql, self.params, self.filas = [], [], filas or []

    async def execute(self, sentencia, params=None):
        self.sql.append(_plano(sentencia))
        self.params.append(params or {})
        return ResultadoFalso(self.filas)


async def test_el_choque_sale_de_programaciones_no_canceladas_y_excluye_la_propia():
    db = SesionSql()
    await AgendaAuditorService(db)._buscar_cruce(ANA, datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 11), ID_PROG)
    sql = db.sql[0]
    # Cancelar libera (estado Cancelada) y reprogramar mueve (fechas de la programación).
    assert "FROM detalle_programacion_auditor d INNER JOIN programacion_visita p" in sql
    assert "NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')" in sql
    assert "p.fecha_inicio < :fecha_fin AND p.fecha_fin > :fecha_inicio" in sql
    assert db.params[0]["excluir"] == str(ID_PROG)
    assert "disponibilidad_auditor" not in sql  # no depende de filas de "fecha bloqueada"


async def test_los_candidatos_ocupados_salen_de_programaciones_no_canceladas():
    db = SesionSql()
    await AgendaAuditorService(db)._ids_con_cruce([str(ANA)], datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 11))
    assert "NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')" in db.sql[0]
    assert "disponibilidad_auditor" not in db.sql[0]


class SesionUsuarioActivo:
    async def execute(self, sentencia, params=None):
        return ResultadoFalso([{"estado": "Activo", "estado_auditor": "Activo"}])


async def test_comprobar_disponibilidad_al_editar_no_choca_con_la_misma_visita(monkeypatch):
    excluidas = []

    async def cruce(self, id_usuario, inicio, fin, excluir=None):
        excluidas.append(excluir)
        return None

    async def sin_bloqueo(self, *a, **k):
        return None

    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", cruce)
    monkeypatch.setattr(AgendaAuditorService, "_bloqueo_en_franja", sin_bloqueo)
    r = await AgendaAuditorService(SesionUsuarioActivo()).consultar_disponibilidad(
        ANA, date(2026, 11, 2), datetime(2026, 11, 2, 9), datetime(2026, 11, 2, 11), excluir_programacion=ID_PROG
    )
    assert r["disponible"] is True and excluidas == [ID_PROG]


async def test_comprobar_disponibilidad_recibe_excluir_por_query(monkeypatch):
    recibido = {}

    async def falso(self, id_usuario, fecha, inicio, fin, excluir_programacion=None):
        recibido["excluir"] = excluir_programacion
        return {"disponible": True}

    monkeypatch.setattr(AgendaAuditorService, "consultar_disponibilidad", falso)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {"id_usuario": str(uuid.uuid4()), "role_name": "Coordinador"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            r = await cliente.get(f"/agenda-auditor/{ANA}/disponibilidad", params={
                "fecha": "2026-11-02", "hora_inicio": "09:00", "hora_fin": "11:00",
                "excluir_programacion": str(ID_PROG)})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert recibido["excluir"] == ID_PROG


class SesionReprogramar:
    """Para reprogramar_programacion: un auditor activo en la visita."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.updates = []

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        if "FROM detalle_programacion_auditor d WHERE d.id_programacion" in sql:
            return ResultadoFalso([(str(ANA),)])
        if "FROM usuario" in sql:
            return ResultadoFalso([{"estado": "Activo", "estado_auditor": "Activo"}])
        if sql.startswith("UPDATE programacion_visita"):
            self.updates.append(params)
            return ResultadoFalso([(ID_PROG,)])
        if "INSERT INTO" in sql or "notificacion" in sql.lower():
            return ResultadoFalso([])
        raise AssertionError("Consulta inesperada: " + sql[:160])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


async def test_reprogramar_rechaza_con_409_si_el_nuevo_horario_se_cruza(monkeypatch):
    llamadas = []

    async def cruce(self, id_usuario, inicio, fin, excluir=None):
        llamadas.append(excluir)
        return {"fecha_inicio": inicio, "fecha_fin": fin}

    async def sin_bloqueo(self, *a, **k):
        return None

    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", cruce)
    monkeypatch.setattr(AgendaAuditorService, "_bloqueo_en_franja", sin_bloqueo)
    db = SesionReprogramar()
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(db).reprogramar_programacion(
            ID_PROG, datetime(2026, 11, 20, 9), datetime(2026, 11, 20, 11), "Cambio")
    assert error.value.status_code == 409
    assert error.value.detail == "No se puede reprogramar: El auditor ya tiene otra visita el 20/11/2026 de 09:00 a 11:00."
    assert llamadas == [ID_PROG]          # la propia visita no cuenta
    assert db.updates == [] and db.commits == 0


async def test_reprogramar_mueve_las_fechas_de_la_misma_programacion(monkeypatch):
    async def sin_cruce(self, *a, **k):
        return None

    async def notificar(self, *a, **k):
        return None

    monkeypatch.setattr(AgendaAuditorService, "_buscar_cruce", sin_cruce)
    monkeypatch.setattr(AgendaAuditorService, "_bloqueo_en_franja", sin_cruce)
    monkeypatch.setattr(AgendaAuditorService, "_crear_notificacion", notificar)
    db = SesionReprogramar()
    await AgendaAuditorService(db).reprogramar_programacion(
        ID_PROG, datetime(2026, 11, 20, 9), datetime(2026, 11, 20, 11), "Cambio")
    # El bloqueo "se mueve" porque la ocupación se calcula con estas fechas.
    assert db.updates[0]["fecha_inicio"] == datetime(2026, 11, 20, 9)
    assert db.updates[0]["id"] == str(ID_PROG) and db.commits == 1
