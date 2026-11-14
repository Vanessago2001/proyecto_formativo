"""
Regresiones del retest del 13/11 en Gestión de certificados.

1. Consulta pública: la exigencia de firma PAdES es una decisión del equipo
   (merge 334c81c y commit 8f5a553), así que aquí se fija lo que debe seguir
   funcionando: un certificado firmado, vigente y publicado se encuentra y se
   descarga aunque el estado llegue con el relleno de la columna CHAR.
2. Métricas: CER-024 no incluye al Comité (matriz original de M9). La
   pantalla no debe pedir /certificados/metricas para los roles sin CER-024 y
   resume lo que el rol ve.
3. Estado con espacios de relleno ("VIGENTE   "): se recorta en el SQL.
"""

import asyncio
import hashlib
import re
from datetime import date
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.certificados import certificados_service as cs
from modules.certificados.certificados_pdf import generar_pdf_certificado
from modules.certificados.certificados_permissions import tiene_permiso
from modules.certificados.certificados_router import router

PDF = b"%PDF-1.4 firmado por el lider"
ID_CERT = "11111111-1111-4111-8111-111111111111"


class _BD:
    """Devuelve siempre la misma fila y guarda el SQL ejecutado."""

    def __init__(self, fila):
        self.fila = fila
        self.sql = []

    async def execute(self, sentencia, params=None):
        self.sql.append(str(sentencia))
        r = MagicMock()
        r.mappings.return_value.first.return_value = self.fila
        r.mappings.return_value.one.return_value = self.fila
        r.mappings.return_value.all.return_value = [self.fila] if self.fila else []
        return r


def _fila_firmada(**cambios):
    fila = {
        "id_certificado": ID_CERT, "codigo_verificacion": "CERT-2026-0001",
        "estado_certificado": "VIGENTE", "fecha_emision": date(2026, 1, 1),
        "fecha_vencimiento": date(2099, 1, 1), "huella_pdf": hashlib.sha256(PDF).hexdigest(),
        "huella_certificado": "abc", "firmado": True, "firmante": "Líder",
        "empresa": "Café", "nit": "900123456-7", "estado_empresa": "Activa",
        "norma_codigo": "NTC", "norma": "ISO 9001", "norma_version": "2015", "alcance": "Todo",
    }
    fila.update(cambios)
    return fila


# ---------- 1. Consulta pública ----------

def test_consulta_publica_firmado_se_encuentra_con_estado_recortado():
    bd = _BD(_fila_firmada())
    certificado = asyncio.run(cs.CertificadosService(bd).publico("cert-2026-0001"))

    assert certificado["codigo_verificacion"] == "CERT-2026-0001"
    assert certificado["firmado"] is True
    assert "TRIM(c.estado_certificado) AS estado_certificado" in bd.sql[0]


def test_consulta_publica_firmado_es_descargable(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "CERTIFICADOS_STORAGE_DIR", str(tmp_path))
    (tmp_path / f"{ID_CERT}.pdf").write_bytes(PDF)

    contenido = asyncio.run(cs.CertificadosService(_BD(_fila_firmada())).pdf_publico_firmado("CERT-2026-0001"))
    assert contenido == PDF


def test_el_criterio_publico_compara_el_estado_recortado():
    for criterio in (cs.CRITERIO_PUBLICO, cs.CRITERIO_PUBLICO_C):
        assert "TRIM(UPPER(" in criterio and "'VIGENTE'" in criterio


# ---------- 2. Métricas y Comité ----------

def _cliente(usuario, fila):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: usuario

    async def override_db():
        yield _BD(fila)

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_cer024_sigue_la_matriz_coordinador_si_comite_no():
    assert tiene_permiso("CER-024", "Coordinador")
    assert tiene_permiso("CER-024", "Auxiliar")
    assert not tiene_permiso("CER-024", "Comité")


def test_metricas_internas_para_coordinador_200_y_comite_403():
    totales = {"total": 1, "vigentes": 1, "suspendidos": 0, "cancelados": 0,
               "publicados": 0, "proximos_a_vencer": 0}
    coordinador = _cliente({"id_usuario": "1", "role_name": "Coordinador"}, totales)
    respuesta = coordinador.get("/certificados/metricas")
    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 1

    comite = _cliente({"id_usuario": "2", "role_name": "Comité"}, totales)
    assert comite.get("/certificados/metricas").status_code == 403


def test_la_pantalla_no_pide_metricas_internas_sin_cer024():
    html = open("static/certificados.html", encoding="utf-8").read()
    permitidos = re.search(r'const canSeeInternalMetrics = \[([^\]]*)\]\.includes\(role\);', html)
    assert permitidos, "falta canSeeInternalMetrics"
    roles = re.findall(r'"([^"]+)"', permitidos.group(1))
    assert set(roles) == {"admin", "auxiliar"}
    # La única llamada a /certificados/metricas queda detrás de ese permiso y
    # los demás roles resumen la lista que ven.
    bloque = html[html.index("async function loadMetrics"):html.index("async function loadCertificates")]
    assert bloque.count('api("/certificados/metricas")') == 1
    assert "} else if (canSeeInternalMetrics) {" in bloque
    assert bloque.rstrip().count("metricsFromList(state.certificados || [])") == 2


# ---------- 3. Estado con relleno CHAR ----------

def test_listado_y_detalle_devuelven_el_estado_recortado():
    fila = {"id_certificado": ID_CERT, "estado_certificado": "VIGENTE",
            "publico_certificado": True, "fecha_vencimiento": date(2099, 1, 1)}
    bd = _BD(fila)
    servicio = cs.CertificadosService(bd)
    asyncio.run(servicio.listar({"role_name": "Coordinador"}))
    asyncio.run(servicio._obtener(ID_CERT))
    asyncio.run(servicio.listar({"role_name": "Público"}))
    for sql in bd.sql:
        assert "TRIM(c.estado_certificado) AS estado_certificado" in sql


def test_estado_con_relleno_se_reconoce_como_vigente_y_pendiente():
    assert cs.certificado_esta_vigente({"estado_certificado": "VIGENTE" + " " * 43,
                                        "fecha_vencimiento": date(2099, 1, 1)})
    try:
        generar_pdf_certificado({"estado_certificado": "PENDIENTE_FIRMA   "}, modo="firma")
    except ValueError:
        pass
    else:  # pragma: no cover - el PDF de firma no debe salir con un borrador
        raise AssertionError("el estado con relleno no se reconoció como PENDIENTE_FIRMA")
