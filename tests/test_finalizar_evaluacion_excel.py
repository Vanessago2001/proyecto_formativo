"""
Finalizar la visita = evaluación (1–100 %) + Excel de la calificación (18/11/2026).

Todo con una base simulada (sin la base real ni el lifespan de la app) y el
almacén de archivos solo en un directorio temporal.
"""

import io
import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

from core import almacen_archivos
from core.database import get_db
from core.security import get_current_user
from main import app
from modules.calificacion_visitas import evaluacion_excel
from tests.fake_db import ResultadoFalso

AUDITOR = {"id_usuario": str(uuid4()), "nombre": "Ana Auditora", "role_name": "Auditor"}
OTRO_AUDITOR = {"id_usuario": str(uuid4()), "nombre": "Otro", "role_name": "Auditor"}
COORDINADOR = {"id_usuario": str(uuid4()), "nombre": "Coordinación", "role_name": "Coordinador"}
COMITE = {"id_usuario": str(uuid4()), "nombre": "Carlos Comité", "role_name": "Comité"}

EVALUACION = {
    "calificacion": "87",
    "comentario_visita": "La visita se desarrolló según el plan.",
    "situaciones_encontradas": "",
    "oportunidades_mejora": "Mejorar el control documental.",
    "observaciones": "Sin novedades de cierre.",
}
TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx() -> bytes:
    libro = Workbook()
    libro.active["A1"] = "Requisito"
    libro.active["B1"] = "Puntaje"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


class BaseFinalizacion:
    """Lo justo de PostgreSQL para finalizar, calificar y que el Comité lo vea."""

    def __init__(self, estado_visita="Confirmada", estado_solicitud="Aprobada",
                 comite_decidio=False, otras_pendientes=0, empezo=True, impedido=None):
        self.id_programacion = str(uuid4())
        self.id_solicitud = str(uuid4())
        self.visita = {
            "id_programacion": self.id_programacion,
            "id_solicitud": self.id_solicitud,
            "estado": estado_visita,
            "fecha_inicio": datetime.now() + (timedelta(hours=-3) if empezo else timedelta(days=3)),
        }
        self.solicitud = {"estado": estado_solicitud, "comite_decidio": comite_decidio}
        self.otras_pendientes = otras_pendientes
        self.impedido = impedido
        self.calificacion = None
        self.sentencias: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.historial = []
        self.bitacora = []

    async def execute(self, sentencia, params=None):
        sql = str(sentencia)
        params = params or {}
        self.sentencias.append(sql)
        if "AS impedimento" in sql:
            return ResultadoFalso([{"impedimento": self.impedido}])
        if "SELECT id_programacion, estado FROM programacion_visita" in sql:
            return ResultadoFalso([dict(self.visita)])
        if "FROM detalle_programacion_auditor d" in sql and "LEFT JOIN usuario" in sql and "rol_auditor" in sql:
            return ResultadoFalso([{"id_usuario": AUDITOR["id_usuario"], "nombre": "Ana", "correo": "a@x.co",
                                    "rol_auditor": "Auditor"}])
        if "UPDATE programacion_visita" in sql:
            self.visita["estado"] = re.search(r"SET estado = '(\w+)'", sql).group(1)
            self.visita["observaciones_finalizacion"] = params.get("observaciones")
            return ResultadoFalso([])
        if "to_regclass('public.calificacion_visita')" in sql:
            return ResultadoFalso([{"existe": True}])
        if "FROM programacion_visita p" in sql and "AS asignado" in sql:
            return ResultadoFalso([{**self.visita, "asignado": params["id_auditor"] == AUDITOR["id_usuario"]}])
        if "FROM solicitud s" in sql and "FOR UPDATE OF s" in sql:
            return ResultadoFalso([dict(self.solicitud)])
        if "INSERT INTO calificacion_visita" in sql:
            self.calificacion = {
                "id_calificacion": uuid4(), "id_programacion": params["id_programacion"],
                "id_solicitud": params["id_solicitud"], "id_auditor": params["id_auditor"],
                "calificacion": params["calificacion"],
                "comentario_visita": params["comentario_visita"],
                "situaciones_encontradas": params["situaciones_encontradas"],
                "oportunidades_mejora": params["oportunidades_mejora"],
                "fecha_registro": datetime.now(), "fecha_actualizacion": None,
            }
            return ResultadoFalso([{**self.calificacion, "creada": True}])
        if "AS pendientes" in sql:
            return ResultadoFalso([{**self.solicitud, "pendientes": self.otras_pendientes}])
        if "UPDATE solicitud SET estado" in sql:
            self.solicitud["estado"] = params["estado"]
            return ResultadoFalso([])
        if "INSERT INTO historial_estado" in sql:
            self.historial.append(params)
            return ResultadoFalso([])
        if "INSERT INTO bitacora_solicitud" in sql:
            self.bitacora.append(params)
            return ResultadoFalso([])
        # ---- Comité
        if "SELECT id_solicitud, estado FROM solicitud" in sql:
            return ResultadoFalso([{"id_solicitud": self.id_solicitud, "estado": self.solicitud["estado"]}])
        if "json_agg" in sql:
            evaluaciones = []
            if self.calificacion:
                evaluaciones = [{**self.calificacion, "nombre": "Ana Auditora", "rol": "Auditor",
                                 "id_auditor": self.calificacion["id_auditor"]}]
            return ResultadoFalso([{
                "id_programacion": self.id_programacion, "fecha_inicio": self.visita["fecha_inicio"],
                "fecha_fin": None, "estado_visita": self.visita["estado"], "auditores_asignados": 1,
                "evaluaciones": evaluaciones,
            }])
        if "JOIN solicitud s ON s.id_solicitud = p.id_solicitud" in sql:
            coincide = (params["id_programacion"] == self.id_programacion
                        and params["id_solicitud"] == self.id_solicitud
                        and params["id_auditor"] == AUDITOR["id_usuario"])
            return ResultadoFalso([{"id_programacion": self.id_programacion}] if coincide else [])
        raise AssertionError(f"Consulta inesperada: {sql[:160]}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def almacen_temporal(monkeypatch, tmp_path):
    monkeypatch.setattr(almacen_archivos, "RAIZ_PROYECTO", tmp_path)
    return tmp_path


@pytest.fixture
def cliente(almacen_temporal):
    def preparar(db, usuario):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: usuario
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    yield preparar
    app.dependency_overrides.clear()


async def _finalizar(cliente, db, usuario=AUDITOR, datos=None, archivo=("evaluacion.xlsx", None, TIPO_XLSX)):
    datos = EVALUACION if datos is None else datos
    files = None
    if archivo is not None:
        nombre, contenido, tipo = archivo
        files = {"archivo": (nombre, _xlsx() if contenido is None else contenido, tipo)}
    async with cliente(db, usuario) as http:
        return await http.post(
            f"/agenda-auditor/programacion/{db.id_programacion}/finalizar",
            data=datos, files=files or {"_": ("", b"", "application/octet-stream")},
        )


def _archivos(raiz: Path) -> list[Path]:
    return [p for p in (raiz / "storage").rglob("*") if p.is_file()] if (raiz / "storage").exists() else []


# ---------------------------------------------------------------- obligatorios (422)

async def test_sin_calificacion_responde_422_y_no_finaliza(cliente, almacen_temporal):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db, datos={**EVALUACION, "calificacion": ""})
    assert respuesta.status_code == 422
    assert "calificación" in respuesta.json()["detail"]
    assert db.commits == 0 and db.rollbacks >= 1
    assert db.calificacion is None
    assert _archivos(almacen_temporal) == []


async def test_sin_comentarios_responde_422(cliente):
    db = BaseFinalizacion()
    datos = {**EVALUACION, "comentario_visita": "", "oportunidades_mejora": ""}
    respuesta = await _finalizar(cliente, db, datos=datos)
    assert respuesta.status_code == 422
    assert "al menos un comentario" in respuesta.json()["detail"]


async def test_sin_excel_responde_422(cliente, almacen_temporal):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db, archivo=None)
    assert respuesta.status_code == 422
    assert "Excel" in respuesta.json()["detail"] and "obligatorio" in respuesta.json()["detail"]
    assert db.commits == 0
    assert _archivos(almacen_temporal) == []


async def test_json_sin_archivo_tambien_es_422(cliente):
    db = BaseFinalizacion()
    async with cliente(db, AUDITOR) as http:
        respuesta = await http.post(
            f"/agenda-auditor/programacion/{db.id_programacion}/finalizar", json={"observaciones": "x"}
        )
    assert respuesta.status_code == 422


@pytest.mark.parametrize("nombre, contenido, fragmento", [
    ("evaluacion.pdf", b"%PDF-1.4 algo", "no es un Excel"),
    ("evaluacion.csv", b"a;b\n1;2", "no es un Excel"),
    ("evaluacion.xlsx", b"esto no es un libro", "no corresponde"),
    ("evaluacion.xls", b"PK\x03\x04 zip disfrazado", "no corresponde"),
    ("evaluacion.xlsx", b"", "vacío"),
])
async def test_excel_con_extension_o_contenido_invalido_es_422(cliente, almacen_temporal, nombre, contenido, fragmento):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db, archivo=(nombre, contenido, "application/octet-stream"))
    assert respuesta.status_code == 422, respuesta.text
    assert fragmento in respuesta.json()["detail"]
    assert db.commits == 0
    assert _archivos(almacen_temporal) == []


def test_un_docx_renombrado_a_xlsx_no_pasa():
    salida = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(salida, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w/>")
    with pytest.raises(Exception) as error:
        evaluacion_excel.validar_excel("x.xlsx", salida.getvalue())
    assert error.value.status_code == 422


def test_excel_de_mas_de_10_mb_es_422():
    with pytest.raises(Exception) as error:
        evaluacion_excel.validar_excel("x.xls", evaluacion_excel.FIRMA_OLE2 + b"0" * (10 * 1024 * 1024))
    assert error.value.status_code == 422
    assert "10 MB" in error.value.detail


def test_xls_real_por_firma_ole2_es_valido():
    excel = evaluacion_excel.validar_excel("Calificación visita.xls", evaluacion_excel.FIRMA_OLE2 + b"\x00" * 512)
    assert excel.extension == ".xls"
    assert excel.nombre == "Calificacion visita.xls"


# ---------------------------------------------------------------- permisos y estados

async def test_otro_auditor_recibe_403(cliente, almacen_temporal):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db, usuario=OTRO_AUDITOR)
    assert respuesta.status_code == 403
    assert "asignado" in respuesta.json()["detail"]
    assert db.commits == 0 and db.calificacion is None
    assert _archivos(almacen_temporal) == []


async def test_el_coordinador_no_finaliza_por_el_auditor(cliente):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db, usuario=COORDINADOR)
    assert respuesta.status_code == 403


async def test_visita_cancelada_es_409(cliente):
    db = BaseFinalizacion(estado_visita="Cancelada")
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 409
    assert "cancelada" in respuesta.json()["detail"]


async def test_visita_ya_finalizada_es_409(cliente):
    db = BaseFinalizacion(estado_visita="Ejecutada")
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 409


async def test_visita_que_no_ha_empezado_es_409_y_no_queda_nada(cliente, almacen_temporal):
    db = BaseFinalizacion(empezo=False)
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 409
    assert "todavía no ha empezado" in respuesta.json()["detail"]
    assert db.commits == 0 and db.rollbacks >= 1
    assert _archivos(almacen_temporal) == []


async def test_con_decision_del_comite_es_409(cliente):
    db = BaseFinalizacion(estado_solicitud="Aprobada", comite_decidio=True)
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 409


# ---------------------------------------------------------------- todo correcto

async def test_con_evaluacion_y_excel_finaliza_registra_y_pasa_al_comite(cliente, almacen_temporal):
    db = BaseFinalizacion()
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "Finalizada"
    assert db.visita["estado"] == "Ejecutada"  # valor que admite chk_estado_visita
    assert db.visita["observaciones_finalizacion"] == "Sin novedades de cierre."
    assert db.calificacion["calificacion"] == 87
    assert db.calificacion["id_auditor"] == AUDITOR["id_usuario"]
    assert db.commits == 1 and db.rollbacks == 0
    # Excel en la ruta derivada + metadatos.
    excel = almacen_temporal / evaluacion_excel.ruta_excel(db.id_programacion, AUDITOR["id_usuario"], ".xlsx")
    meta = almacen_temporal / evaluacion_excel.ruta_metadatos(db.id_programacion, AUDITOR["id_usuario"])
    assert excel.is_file() and excel.read_bytes().startswith(b"PK")
    assert meta.is_file() and "evaluacion.xlsx" in meta.read_text(encoding="utf-8")
    assert cuerpo["excel"]["nombre"] == "evaluacion.xlsx"
    # Última visita: Aprobada (Coordinador) → En revision (bandeja del Comité).
    assert cuerpo["paso_a_comite"] is True
    assert db.solicitud["estado"] == "En revision"
    assert db.historial and db.historial[0]["estado"] == "En revision"
    assert db.bitacora


async def test_con_otras_visitas_pendientes_no_cambia_la_solicitud(cliente):
    db = BaseFinalizacion(otras_pendientes=1)
    respuesta = await _finalizar(cliente, db)
    assert respuesta.status_code == 200
    assert respuesta.json()["paso_a_comite"] is False
    assert db.solicitud["estado"] == "Aprobada"
    assert "1 visita pendiente" in respuesta.json()["mensaje"]


# ---------------------------------------------------------------- Comité

async def test_el_comite_ve_la_evaluacion_y_descarga_el_excel(cliente, almacen_temporal):
    db = BaseFinalizacion()
    assert (await _finalizar(cliente, db)).status_code == 200

    async with cliente(db, COMITE) as http:
        datos = (await http.get(f"/calificacion-visitas/expediente/{db.id_solicitud}")).json()
        evaluacion = datos["visitas"][0]["evaluaciones"][0]
        assert evaluacion["calificacion"] == 87
        assert evaluacion["excel"]["nombre"] == "evaluacion.xlsx"
        assert datos["faltantes"] == []

        url = (f"/calificacion-visitas/expediente/{db.id_solicitud}/visita/{db.id_programacion}"
               f"/excel/{AUDITOR['id_usuario']}")
        descarga = await http.get(url)
    assert descarga.status_code == 200
    assert descarga.headers["content-type"].startswith(TIPO_XLSX)
    assert "attachment" in descarga.headers["content-disposition"]
    assert descarga.content.startswith(b"PK")


async def test_el_comite_impedido_no_descarga(cliente):
    db = BaseFinalizacion()
    assert (await _finalizar(cliente, db)).status_code == 200
    db.impedido = "solicitud"
    url = (f"/calificacion-visitas/expediente/{db.id_solicitud}/visita/{db.id_programacion}"
           f"/excel/{AUDITOR['id_usuario']}")
    async with cliente(db, COMITE) as http:
        respuesta = await http.get(url)
    assert respuesta.status_code == 404


async def test_el_auditor_no_descarga_desde_el_expediente(cliente):
    db = BaseFinalizacion()
    url = (f"/calificacion-visitas/expediente/{db.id_solicitud}/visita/{db.id_programacion}"
           f"/excel/{AUDITOR['id_usuario']}")
    async with cliente(db, AUDITOR) as http:
        respuesta = await http.get(url)
    assert respuesta.status_code == 403


async def test_visita_de_otro_expediente_es_404(cliente):
    db = BaseFinalizacion()
    url = f"/calificacion-visitas/expediente/{uuid4()}/visita/{db.id_programacion}/excel/{AUDITOR['id_usuario']}"
    async with cliente(db, COMITE) as http:
        respuesta = await http.get(url)
    assert respuesta.status_code == 404


# ---------------------------------------------------------------- pantalla del auditor

HTML = Path(__file__).resolve().parent.parent / "static" / "consultar_auditorias_programadas.html"


def test_la_ventana_de_finalizar_tiene_evaluacion_excel_y_aviso_propio():
    html = HTML.read_text(encoding="utf-8")
    modal = html[html.index('id="finalizarModal"'):html.index('id="calificarModal"')]
    assert 'id="finCalNumero"' in modal and 'type="range"' in modal
    assert 'id="finExcel"' in modal and 'accept=".xlsx,.xls' in modal
    assert 'id="finalizarObservaciones"' in modal
    assert 'id="finalizarAviso"' in modal and 'role="alert"' in modal


def test_los_errores_de_acciones_en_modales_no_van_a_la_ventana_principal():
    html = HTML.read_text(encoding="utf-8")
    for funcion in ("enviarFinalizacion", "enviarSolicitudReprogramacion", "confirmarProgramacion", "guardarCalificacion"):
        inicio = html.index("async function " + funcion)
        cuerpo = html[inicio:html.index("\n        }\n", inicio)]
        assert "mostrarMensaje(" not in cuerpo.replace("mostrarMensaje(data.mensaje", ""), funcion
        assert "avisoEnModal(" in cuerpo, funcion


def test_el_expediente_del_comite_enlaza_el_excel_con_token():
    html = (Path(__file__).resolve().parent.parent / "static" / "comite.html").read_text(encoding="utf-8")
    assert "Descargar evaluación (Excel)" in html
    assert '"/excel/"' in html and "data-excel-evaluacion" in html
    assert 'Authorization: "Bearer " + token' in html[html.index("function enlaceExcelEvaluacion"):]


async def test_calificar_una_solicitud_aprobada_por_el_coordinador_se_permite():
    """'Aprobada' sin decisión del Comité = aprobada por el Coordinador para auditar."""
    from modules.calificacion_visitas.calificacion_service import CalificacionVisitaService

    db = BaseFinalizacion(estado_solicitud="Aprobada", comite_decidio=False)
    datos = {"calificacion": 70, "comentario_visita": "Visita completa y ordenada."}
    respuesta = await CalificacionVisitaService(db).guardar(db.id_programacion, datos, AUDITOR)
    assert respuesta["calificacion"]["calificacion"] == 70
    assert db.commits == 1
