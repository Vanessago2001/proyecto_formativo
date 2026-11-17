"""Historial de dictámenes (filtro, paginación y estado de firma) y borrador
automático del certificado al aprobar el Comité."""
import asyncio
from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.certificados.certificados_service import CertificadosService
from tests.test_comite_certificacion import SesionComiteFalsa, override_user

client = TestClient(app)


def fila(codigo, accion, estado_acta=None, estado_certificado=None, firmado=False, empresa="Empresa"):
    return {
        "id_solicitud": codigo, "codigo_expediente": codigo, "empresa": empresa, "nit": "900",
        "accion": accion, "estado_expediente": "Aprobada" if accion == "aprobar" else "Rechazada",
        "estado_acta": estado_acta, "estado_certificado": estado_certificado,
        "certificado_firmado": firmado,
    }


FILAS = [
    fila("EXP-1", "aprobar", "FIRMADA", "VIGENTE", True, "Cafe del Eje"),
    fila("EXP-2", "aprobar", "FIRMADA", "PENDIENTE_FIRMA", False),
    fila("EXP-3", "rechazar", "GENERADA"),
    fila("EXP-4", "rechazar", "FIRMADA"),
]


def consultar(params, rol="Comité"):
    app.dependency_overrides[get_current_user] = override_user(rol)

    async def db():
        yield SesionComiteFalsa(FILAS)

    app.dependency_overrides[get_db] = db
    try:
        return client.get("/comite/historial-dictamenes", params=params)
    finally:
        app.dependency_overrides.clear()


def test_historial_marca_que_falta_firmar():
    datos = consultar({}).json()
    por_codigo = {d["codigo_expediente"]: d for d in datos["dictamenes"]}
    assert datos["total"] == 4
    assert por_codigo["EXP-1"]["firma_certificado"] == "Firmado" and not por_codigo["EXP-1"]["pendiente_firma"]
    assert por_codigo["EXP-2"]["firma_certificado"] == "Pendiente de firma" and por_codigo["EXP-2"]["pendiente_firma"]
    assert por_codigo["EXP-3"]["firma_dictamen"] == "Pendiente de firma"
    assert por_codigo["EXP-4"]["firma_certificado"] == "No aplica" and not por_codigo["EXP-4"]["pendiente_firma"]


def test_historial_filtra_y_pagina():
    assert [d["codigo_expediente"] for d in consultar({"firma": "pendiente"}).json()["dictamenes"]] == ["EXP-2", "EXP-3"]
    assert [d["codigo_expediente"] for d in consultar({"decision": "rechazada"}).json()["dictamenes"]] == ["EXP-3", "EXP-4"]
    assert [d["codigo_expediente"] for d in consultar({"q": "cafe"}).json()["dictamenes"]] == ["EXP-1"]
    pagina = consultar({"page": 2, "page_size": 3}).json()
    assert pagina["paginas"] == 2 and [d["codigo_expediente"] for d in pagina["dictamenes"]] == ["EXP-4"]


def test_historial_no_es_para_otros_roles():
    assert consultar({}, rol="Empresa").status_code == 403


# ---------------- borrador automático ----------------

class Escalar:
    def __init__(self, valor):
        self.valor = valor

    def scalar_one_or_none(self):
        return self.valor


class SesionBorrador:
    def __init__(self, *valores):
        self.valores = list(valores)
        self.rollbacks = 0

    async def execute(self, *_a, **_k):
        return Escalar(self.valores.pop(0))

    async def rollback(self):
        self.rollbacks += 1


ID = UUID("95198e60-b838-4d75-a694-08804cc1acc3")


def test_borrador_no_se_duplica():
    servicio = CertificadosService(SesionBorrador("CERT-2026-0001"))
    resultado = asyncio.run(servicio.crear_borrador_automatico(ID, {}))
    assert resultado["creado"] is False and "CERT-2026-0001" in resultado["motivo"]


def test_borrador_ya_no_exige_alcance(monkeypatch):
    # Solo se consulta si ya hay certificado; no se busca ninguna línea de alcance.
    sesion = SesionBorrador(None)
    servicio = CertificadosService(sesion)

    async def crear(datos, usuario, detalle_inicial=None):
        return {"codigo_verificacion": "CERT-2026-0010"}

    monkeypatch.setattr(servicio, "crear", crear)
    resultado = asyncio.run(servicio.crear_borrador_automatico(ID, {}))
    assert resultado == {"creado": True, "codigo_verificacion": "CERT-2026-0010"}
    assert sesion.valores == []


def test_borrador_se_crea_pendiente_de_firma(monkeypatch):
    sesion = SesionBorrador(None)
    servicio = CertificadosService(sesion)
    llamadas = []

    async def crear(datos, usuario, detalle_inicial=None):
        llamadas.append((datos, detalle_inicial))
        return {"codigo_verificacion": "CERT-2026-0009"}

    monkeypatch.setattr(servicio, "crear", crear)
    resultado = asyncio.run(servicio.crear_borrador_automatico(ID, {}))
    assert resultado == {"creado": True, "codigo_verificacion": "CERT-2026-0009"}
    assert not hasattr(llamadas[0][0], "id_alcance") and "firma del líder" in llamadas[0][1]


def test_borrador_sin_lider_no_rompe_la_aprobacion(monkeypatch):
    sesion = SesionBorrador(None)
    servicio = CertificadosService(sesion)

    async def crear(*_a, **_k):
        raise HTTPException(status_code=409, detail="No hay líder del Comité asignado.")

    monkeypatch.setattr(servicio, "crear", crear)
    resultado = asyncio.run(servicio.crear_borrador_automatico(ID, {}))
    assert resultado == {"creado": False, "motivo": "No hay líder del Comité asignado."}
    assert sesion.rollbacks == 1
