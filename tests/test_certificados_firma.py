import asyncio
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException

from core.security import hash_password
from modules.certificados.firma_service import FirmaService, codigo_firma, generar_qr_svg
from modules.certificados.certificados_service import CertificadosService


class FakeResult:
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else [rows]

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeDatabase:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.commits = 0
        self.rollbacks = 0
        self.executions = []

    async def execute(self, *args, **kwargs):
        self.executions.append((args, kwargs))
        return FakeResult(self.responses.pop(0) if self.responses else [])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


USUARIO = {"id_usuario": "11111111-1111-4111-8111-111111111111"}


def _fila_firma(password="Firma#2026x", bloqueada=False):
    return {"hash_firma": hash_password(password), "intentos_fallidos": 0, "bloqueada": bloqueada}


def test_verificar_acepta_la_contrasena_de_firma_correcta():
    db = FakeDatabase(_fila_firma(), [])
    firma = asyncio.run(FirmaService(db).verificar(USUARIO, "Firma#2026x"))
    assert firma["id_usuario"] == USUARIO["id_usuario"]
    assert db.commits == 1


def test_verificar_rechaza_contrasena_incorrecta_y_cuenta_el_intento():
    db = FakeDatabase(_fila_firma(), [])
    with pytest.raises(HTTPException) as error:
        asyncio.run(FirmaService(db).verificar(USUARIO, "otra-cosa"))
    assert error.value.status_code == 401
    assert db.commits == 1
    assert "intentos_fallidos + 1" in str(db.executions[1][0][0])


def test_verificar_exige_firma_configurada():
    with pytest.raises(HTTPException) as error:
        asyncio.run(FirmaService(FakeDatabase([])).verificar(USUARIO, "x"))
    assert error.value.status_code == 409


def test_verificar_rechaza_firma_bloqueada():
    with pytest.raises(HTTPException) as error:
        asyncio.run(FirmaService(FakeDatabase(_fila_firma(bloqueada=True))).verificar(USUARIO, "Firma#2026x"))
    assert error.value.status_code == 423


def test_configurar_exige_contrasena_de_inicio_correcta():
    db = FakeDatabase({"contrasena": hash_password("Login#2026x")})
    with pytest.raises(HTTPException) as error:
        asyncio.run(FirmaService(db).configurar(USUARIO, "incorrecta", "Firma#2026x"))
    assert error.value.status_code == 401


def test_configurar_guarda_hash_y_devuelve_qr():
    db = FakeDatabase({"contrasena": hash_password("Login#2026x")}, [])
    resultado = asyncio.run(FirmaService(db).configurar(USUARIO, "Login#2026x", "Firma#2026x"))
    parametros = db.executions[1][0][1]
    assert parametros["hash_firma"].startswith("$2")
    assert parametros["hash_firma"] != "Firma#2026x"
    assert resultado["configurada"] is True
    assert "<svg" in resultado["qr_svg"]
    assert db.commits == 1


def test_configurar_rechaza_contrasena_de_firma_debil():
    db = FakeDatabase({"contrasena": hash_password("Login#2026x")})
    with pytest.raises(HTTPException) as error:
        asyncio.run(FirmaService(db).configurar(USUARIO, "Login#2026x", "debil"))
    assert error.value.status_code == 422


def test_registrar_firma_guarda_numero_y_codigo_cifrado():
    db = FakeDatabase([])
    firma = {"id_usuario": USUARIO["id_usuario"], "hash_firma": hash_password("Firma#2026x")}
    certificado = {"codigo_verificacion": "CS-2026-000001", "empresa": "ACME", "nit": "900"}
    asyncio.run(FirmaService(db).registrar_firma("22222222-2222-4222-8222-222222222222", certificado, firma))
    parametros = db.executions[0][0][1]
    assert parametros["numero"] == "CS-2026-000001"
    assert parametros["codigo"] == codigo_firma(
        firma["hash_firma"], "CS-2026-000001", USUARIO["id_usuario"], parametros["datos"]
    )
    assert len(parametros["codigo"]) == 64


def test_qr_es_svg():
    assert "<svg" in generar_qr_svg("CERTISENA-FIRMA:abc")


def test_publicar_certificado_firmado_ya_no_devuelve_409():
    fila = {
        "estado_certificado": "VIGENTE",
        "fecha_vencimiento": date.today() + timedelta(days=10),
        "url_certificado": "/certificados/x/pdf",
        "id_firmante": "66666666-6666-4666-8666-666666666666",
        "huella_firmante": "b" * 64,
        "codigo_hash": "a" * 64,
        "huella_pdf": "c" * 64,
    }
    publicado = {**fila, "publico_certificado": True, "id_certificado": "x", "id_empresa": "e"}
    db = FakeDatabase(fila, [], [], publicado)
    resultado = asyncio.run(CertificadosService(db).cambiar_publicacion(
        UUID("11111111-1111-4111-8111-111111111111"), True, USUARIO
    ))
    assert resultado["publico_certificado"] is True
    sql = str(db.executions[0][0][0])
    for campo in ("id_firmante", "huella_firmante", "codigo_hash", "huella_pdf"):
        assert campo in sql
