"""Exportación a Excel/PDF (CER-025, CER-026, COM-020) y filtros de la cola del Comité."""

from datetime import date, datetime
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.certificados.certificados_service import CertificadosService
from modules.comite.comite_service import construir_filtro_expedientes
from modules.reportes.exportacion_tabular import (
    TIPO_XLSX,
    Columna,
    generar_pdf_tabla,
    generar_xlsx,
    normalizar_formato,
)

client = TestClient(app)

FILA_CERTIFICADO = {
    "codigo_verificacion": "CERT-2026-0001",
    "numero_radicado": "SOL-2026-0001",
    "empresa": "=HYPERLINK(\"https://malicioso.test\")",
    "nit": "900123456-7",
    "norma_codigo": "ISO-9001",
    "alcance": "Diseño y producción",
    "fecha_emision": date(2026, 10, 2),
    "fecha_vencimiento": date(2027, 10, 2),
    "estado_certificado": "VIGENTE                     ",
    "publico_certificado": True,
}


def _usuario(rol):
    async def _override():
        return {"id": "11111111-1111-1111-1111-111111111111", "nombre": "tester", "role_name": rol}
    return _override


class _Resultado:
    def __init__(self, filas):
        self._filas = filas

    def mappings(self):
        return self

    def all(self):
        return self._filas


class _SesionDecisiones:
    async def execute(self, *_a, **_k):
        return _Resultado([{
            "id_accion": 1, "expediente_id": "x", "codigo_expediente": "SOL-2026-0003",
            "empresa": "Cafe del Eje S.A.S.", "accion": "aprobar", "comentario": "Cumple",
            "datos": "{}", "id_usuario": "u", "usuario": "Comité", "estado_expediente": "Aprobada",
            "fecha": datetime(2026, 9, 10, 15, 55),
        }])


async def _db_decisiones():
    yield _SesionDecisiones()


@pytest.fixture(autouse=True)
def _limpiar_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper común
# ---------------------------------------------------------------------------

def test_xlsx_tiene_encabezados_en_espanol_fechas_reales_y_no_evalua_formulas():
    columnas = [
        Columna("empresa", "Empresa titular", 30),
        Columna("fecha_emision", "Fecha de emisión", 15),
        Columna("publico_certificado", "Publicado", 11),
    ]
    contenido = generar_xlsx("Base de certificados", columnas, [FILA_CERTIFICADO])
    hoja = load_workbook(BytesIO(contenido)).active

    encabezados = [c.value for c in hoja[4]]
    assert encabezados == ["Empresa titular", "Fecha de emisión", "Publicado"]
    empresa, fecha, publicado = hoja[5]
    assert empresa.data_type == "s" and empresa.value.startswith("=HYPERLINK")
    assert fecha.value.date() == date(2026, 10, 2) and fecha.number_format == "DD/MM/YYYY"
    assert publicado.value == "Sí"
    assert hoja.column_dimensions["A"].width == 30
    assert hoja.freeze_panes == "A5"


def test_xlsx_y_pdf_sin_filas_avisan_que_no_hay_datos():
    columnas = [Columna("a", "A")]
    hoja = load_workbook(BytesIO(generar_xlsx("Vacío", columnas, []))).active
    assert hoja["A5"].value == "No hay información para mostrar."
    assert generar_pdf_tabla("Vacío", columnas, []).startswith(b"%PDF")


def test_formato_desconocido_se_rechaza():
    assert normalizar_formato("Excel") == "xlsx"
    assert normalizar_formato("PDF") == "pdf"
    with pytest.raises(HTTPException) as error:
        normalizar_formato("docx")
    assert error.value.status_code == 422


# ---------------------------------------------------------------------------
# CER-025 / CER-026
# ---------------------------------------------------------------------------

def test_exportar_certificados_en_excel_y_pdf(monkeypatch):
    async def filas(_self):
        return [FILA_CERTIFICADO]

    monkeypatch.setattr(CertificadosService, "registros_exportacion", filas)
    app.dependency_overrides[get_current_user] = _usuario("Administrador")

    respuesta = client.get("/certificados/exportar")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == TIPO_XLSX
    assert 'filename="certificados.xlsx"' in respuesta.headers["content-disposition"]
    hoja = load_workbook(BytesIO(respuesta.content)).active
    assert hoja["A4"].value == "Código de verificación"
    assert hoja["I5"].value == "Vigente"

    pdf = client.get("/certificados/exportar?formato=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_exportar_certificados_conserva_permisos(monkeypatch):
    async def filas(_self):
        return []

    monkeypatch.setattr(CertificadosService, "registros_exportacion", filas)
    monkeypatch.setattr(CertificadosService, "empresas_oficiales", filas)
    app.dependency_overrides[get_current_user] = _usuario("Empresa")
    assert client.get("/certificados/exportar?formato=xlsx").status_code == 403
    assert client.get("/certificados/empresas-oficiales?formato=pdf").status_code == 403

    app.dependency_overrides[get_current_user] = _usuario("Auxiliar")
    respuesta = client.get("/certificados/exportar")
    assert respuesta.status_code == 200
    assert respuesta.headers.get("X-Requiere-Aprobacion") == "true"


def test_listado_oficial_de_empresas_en_excel(monkeypatch):
    async def filas(_self):
        return [{"empresa": "Cafe del Eje S.A.S.", "nit": "900123456-7", "ciudad": "Armenia",
                 "norma_codigo": "ISO-9001", "fecha_emision": date(2026, 10, 2),
                 "fecha_vencimiento": date(2027, 10, 2), "codigo_verificacion": "CERT-2026-0001"}]

    monkeypatch.setattr(CertificadosService, "empresas_oficiales", filas)
    app.dependency_overrides[get_current_user] = _usuario("Administrador")
    respuesta = client.get("/certificados/empresas-oficiales")
    assert respuesta.status_code == 200
    hoja = load_workbook(BytesIO(respuesta.content)).active
    # Con subtítulo el encabezado baja una fila.
    assert [c.value for c in hoja[5]][:3] == ["Empresa", "NIT", "Ciudad"]
    assert hoja["E6"].number_format == "DD/MM/YYYY"


# ---------------------------------------------------------------------------
# COM-020
# ---------------------------------------------------------------------------

def test_exportar_decisiones_en_excel_pdf_y_json():
    app.dependency_overrides[get_current_user] = _usuario("Administrador")
    app.dependency_overrides[get_db] = _db_decisiones

    excel = client.get("/comite/exportar-decisiones?formato=xlsx")
    assert excel.status_code == 200
    hoja = load_workbook(BytesIO(excel.content)).active
    assert [c.value for c in hoja[4]][:4] == ["Fecha", "Expediente", "Empresa", "Acción"]
    assert hoja["D5"].value == "Aprobó el otorgamiento"

    pdf = client.get("/comite/exportar-decisiones?formato=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    json = client.get("/comite/exportar-decisiones")
    assert json.status_code == 200
    assert json.json()["decisiones"][0]["codigo_expediente"] == "SOL-2026-0003"


def test_exportar_decisiones_rechaza_roles_sin_permiso():
    app.dependency_overrides[get_current_user] = _usuario("Empresa")
    app.dependency_overrides[get_db] = _db_decisiones
    assert client.get("/comite/exportar-decisiones?formato=xlsx").status_code == 403


# ---------------------------------------------------------------------------
# Cola del Comité: el estado lo decide el filtro, no el buscador
# ---------------------------------------------------------------------------

def test_filtro_por_defecto_son_los_pendientes_aunque_se_busque_por_nit():
    sin_busqueda, params = construir_filtro_expedientes()
    con_nit, params_nit = construir_filtro_expedientes(q="900123456-7")
    assert params["estado_0"] == "Radicada" and params["estado_1"] == "En revision"
    assert params_nit["estado_0"] == "Radicada" and params_nit["estado_1"] == "En revision"
    assert params_nit["q"] == "%900123456-7%"
    assert params_nit["q_compacto"] == "%9001234567%"
    assert ":q" not in sin_busqueda and ":q" in con_nit


def test_filtro_todos_no_restringe_estado_y_un_estado_se_normaliza():
    sql, params = construir_filtro_expedientes(estado="todos")
    assert sql == "" and params == {}
    _, params = construir_filtro_expedientes(estado="APROBADO")
    assert params == {"estado_0": "Aprobada"}


def test_filtro_estado_desconocido_es_422():
    with pytest.raises(HTTPException) as error:
        construir_filtro_expedientes(estado="inventado")
    assert error.value.status_code == 422


def test_filtro_norma_ignora_espacios_y_guiones():
    _, params = construir_filtro_expedientes(estado="todos", norma="ISO 9001")
    assert params == {"norma": "ISO9001"}


def test_filtro_fechas_y_rango_invalido():
    _, params = construir_filtro_expedientes(estado="todos", fecha_desde=date(2026, 9, 1), fecha_hasta=date(2026, 9, 30))
    assert params == {"fecha_desde": date(2026, 9, 1), "fecha_hasta": date(2026, 9, 30)}
    with pytest.raises(HTTPException):
        construir_filtro_expedientes(fecha_desde=date(2026, 10, 1), fecha_hasta=date(2026, 9, 1))


def test_endpoint_de_cola_acepta_filtros_y_valida_estado():
    app.dependency_overrides[get_current_user] = _usuario("Comite")

    class _Sesion:
        def __init__(self):
            self.params = []

        async def execute(self, _sql, params=None):
            self.params.append(params)
            return _Resultado([])

    sesion = _Sesion()

    async def _db():
        yield sesion

    app.dependency_overrides[get_db] = _db
    respuesta = client.get("/comite/expedientes-pendientes?estado=Rechazada&q=900&norma=ISO-14001&fecha_desde=2026-09-01")
    assert respuesta.status_code == 200
    assert respuesta.json()["filtro"]["estado"] == "Rechazada"
    assert sesion.params[0]["estado_0"] == "Rechazada"
    assert sesion.params[0]["norma"] == "ISO14001"
    assert client.get("/comite/expedientes-pendientes?estado=xyz").status_code == 422
