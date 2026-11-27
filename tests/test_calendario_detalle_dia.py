"""
Detalle del día en los calendarios de programación (modal).

  · Los registros de disponibilidad traen, solo con SELECT, cuándo se
    registraron (historial_disponibilidad_auditor) y el radicado de la
    programación que originó el bloqueo, si existe.
  · El calendario general del Coordinador trae por día el detalle de cada
    bloqueo (auditor, motivo, fechas) y los nombres de los disponibles
    (activos sin bloqueo ni visita, hayan declarado o no).
  · Las auditorías del auditor traen NIT, dirección de la sede y de la
    programación; siguen limitadas a sus propias filas (d.id_usuario).
  · La disponibilidad semanal salió del perfil y vive en su ventana del menú.
"""

import uuid
from datetime import datetime, time
from pathlib import Path

from modules.agenda_auditor.agenda_service import AgendaAuditorService
from tests.fake_db import ResultadoFalso

RAIZ = Path(__file__).resolve().parent.parent
ANA = uuid.uuid4()
LUIS = uuid.uuid4()
ID_PROG = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


class SesionGrabadora:
    def __init__(self, por_tabla=None):
        self.sql, self.params = [], []
        self.por_tabla = por_tabla or {}

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sql.append(sql)
        self.params.append(params or {})
        for clave, filas in self.por_tabla.items():
            if clave in sql:
                return ResultadoFalso(filas)
        return ResultadoFalso([])


async def test_consultar_agenda_trae_registro_y_programacion_solo_con_select():
    db = SesionGrabadora()
    await AgendaAuditorService(db).consultar_agenda(ANA, incluir_inactivos=False)
    sql = db.sql[0]
    assert sql.startswith("SELECT")
    assert "MIN(hd.fecha_evento) FROM historial_disponibilidad_auditor hd" in sql
    assert "AS registrado_en" in sql and "AS radicado_relacionado" in sql
    assert "disponibilidad_auditor.id_programacion" in sql
    assert db.params[0]["id_usuario"] == str(ANA)  # el auditor solo ve lo suyo
    for palabra in ("INSERT", "UPDATE", "DELETE"):
        assert palabra not in sql


async def test_general_sin_auditor_detalla_bloqueos_y_disponibles_por_dia():
    disponibilidad = [
        {"id_disponibilidad": 1, "id_usuario": LUIS, "tipo_registro": "Horario Semanal", "dia_semana": 5,
         "fecha_inicio": datetime(2026, 11, 1), "fecha_fin": None, "hora_inicio": time(8), "hora_fin": time(12),
         "motivo": None, "estado": "Activo", "auditor_nombre": "Luis"},
        {"id_disponibilidad": 2, "id_usuario": ANA, "tipo_registro": "Bloqueo Fecha", "dia_semana": None,
         "fecha_inicio": datetime(2026, 11, 13), "fecha_fin": datetime(2026, 11, 13, 23, 59),
         "hora_inicio": None, "hora_fin": None, "motivo": "Cita médica", "estado": "Activo",
         "auditor_nombre": "Ana", "registrado_en": datetime(2026, 11, 2, 10, 30),
         "id_programacion": ID_PROG, "radicado_relacionado": "SOL-2026-0003"},
    ]
    activos = [{"id_usuario": ANA, "nombre": "Ana"}, {"id_usuario": LUIS, "nombre": "Luis"}]
    db = SesionGrabadora({"FROM disponibilidad_auditor da": disponibilidad, "FROM usuario u WHERE": activos})
    r = await AgendaAuditorService(db).ver_disponibilidad_mensual_general(2026, 11)

    sql_disp = next(s for s in db.sql if "FROM disponibilidad_auditor da" in s)
    assert "AS registrado_en" in sql_disp and "da.id_programacion" in sql_disp
    dias = {d["fecha"]: d for d in r["dias"]}
    viernes_13 = dias["2026-11-13"]
    assert viernes_13["nombres_disponibles"] == ["Luis"]
    [bloqueo] = viernes_13["bloqueos"]
    assert bloqueo["auditor_nombre"] == "Ana" and bloqueo["motivo"] == "Cita médica"
    assert bloqueo["registrado_en"] == datetime(2026, 11, 2, 10, 30)
    assert bloqueo["radicado_relacionado"] == "SOL-2026-0003"
    # Regla única: sin bloqueos ni visitas ambos están disponibles el jueves,
    # aunque ninguno declaró disponibilidad ese día.
    assert dias["2026-11-12"]["bloqueos"] == [] and dias["2026-11-12"]["nombres_disponibles"] == ["Ana", "Luis"]


async def test_auditorias_del_auditor_traen_nit_y_direcciones_sin_salir_de_lo_suyo():
    db = SesionGrabadora()
    await AgendaAuditorService(db).consultar_auditorias_programadas(ANA)
    sql = db.sql[0]
    assert "e.nit AS empresa_nit" in sql
    assert "sede.direccion AS sede_direccion" in sql
    assert "p.direccion_servicio AS direccion_programacion" in sql
    assert "AS equipo" in sql and "num_doc" not in sql  # sin documentos de compañeros
    assert "d.id_usuario = :id_usuario" in sql and db.params[0]["id_usuario"] == str(ANA)


def test_disponibilidad_semanal_esta_en_su_ventana_y_no_en_el_perfil():
    perfil = (RAIZ / "static" / "perfil_auditor.html").read_text(encoding="utf-8")
    assert "mi_disponibilidad.js" not in perfil and 'id="miDisponibilidad"' not in perfil
    assert 'href="/disponibilidad-auditor#configurar-horario"' in perfil

    pagina = (RAIZ / "static" / "disponibilidad_auditor.html").read_text(encoding="utf-8")
    assert 'data-seccion="configurar-horario" class="active">Mi disponibilidad semanal</a>' in pagina
    assert 'id="miDisponibilidad"' in pagina and "hashchange" in pagina

    componente = (RAIZ / "static" / "mi_disponibilidad.js").read_text(encoding="utf-8")
    for fragmento in ('aria-modal", "true"', "showModal()", 'e.key !== "Tab"', "data-md-dia", "Ver detalle del "):
        assert fragmento in componente


def test_agenda_coordinador_muestra_disponibilidad_semanal_en_calendario():
    pagina = (RAIZ / "static" / "consultar_agenda_auditor.html").read_text(encoding="utf-8")
    assert ".weekly-calendar {" in pagina
    assert 'role="group" aria-label="Horario semanal del auditor"' in pagina
    assert "renderWeeklyAvailability(filas)" in pagina
    for dia in ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"):
        assert dia in pagina
    assert "Fechas puntuales y otros registros" in pagina
