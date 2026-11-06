"""
Correcciones del documento de pruebas del portal público y del bloqueo por
intentos fallidos:

1/6. Empresa inactiva: se muestra como tal en todos los submódulos, nunca
     como empresa activa o certificada.
2.   NIT completo: sin coincidencias por subcadena; formato normalizado.
3.   Consulta pública por código: un certificado vigente y publicado se
     encuentra aunque no tenga firma PAdES (la firma solo condiciona la
     descarga del PDF firmado).
4.   Validar autenticidad: el código del PDF se encuentra aunque llegue en
     minúsculas, con espacios o con un guion tipográfico.
5.   Constancia: no se emite sin certificados vigentes; con varios se elige
     uno o todos.
8.   Código por correo: un fallo del SMTP ya no deja al usuario en un 500, la
     verificación antigua no salta la fase 1 y existe "Reenviar código".
"""

import asyncio
import base64
import re
import zlib
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from main import app
from modules.consultas_p import rate_limit
from modules.consultas_p.consultas_service import normalizar_codigo, normalizar_nit

BASE = "/api/consultas-publicas"

EMPRESA_ACTIVA = {
    "id_empresa": "11111111-1111-1111-1111-111111111111",
    "nombre": "Café del Eje",
    "nit": "900123456-7",
    "ciudad": "Manizales",
    "estado_empresa": "Activa",
}
EMPRESA_INACTIVA = {**EMPRESA_ACTIVA, "nombre": "Empresa Cerrada", "estado_empresa": "Inactiva"}


def _cert(codigo, norma="NTC"):
    return {
        "codigo_verificacion": codigo,
        "estado": "VIGENTE",
        "fecha_emision": date(2026, 1, 1),
        "fecha_vencimiento": date(2099, 1, 1),
        "url_certificado": None,
        "norma_codigo": norma,
        "norma_nombre": "ISO 9001",
        "norma_version": "2015",
    }


def _filas(filas):
    r = MagicMock()
    r.mappings().all.return_value = filas
    return r


def _una(fila):
    r = MagicMock()
    r.mappings().first.return_value = fila
    return r


def _conteo(n):
    return _una({"total": n})


def _cargar_empresa(db, empresa, certificados):
    db.execute.side_effect = [
        _filas([dict(empresa)]),
        _filas(certificados),
        _filas(certificados),
        _conteo(1), _conteo(1), _conteo(1),
        _una({"numero_radicado": "RAD-1", "fecha": date(2026, 1, 1)}),
        _filas([]),
    ]


def _fila_documento(**cambios):
    fila = {
        "id_solicitud": "s-1", "numero_radicado": "RAD-2026-001", "estado_tramite": "Aprobada",
        "fecha_tramite": date(2026, 1, 1), "fecha_radicacion": date(2026, 1, 1),
        "alcance_certificacion": "ISO 9001", "id_empresa": EMPRESA_ACTIVA["id_empresa"],
        "empresa": EMPRESA_ACTIVA["nombre"], "nit": EMPRESA_ACTIVA["nit"], "ciudad": "Manizales",
        "estado_empresa": "Activa", "norma_codigo": "NTC", "norma_nombre": "ISO 9001",
        "norma_version": "2015", "codigo_verificacion": "CERT-2026-0001", "cert_estado": "VIGENTE",
        "cert_emision": date(2026, 1, 1), "cert_vence": date(2099, 1, 1), "url_certificado": None,
    }
    fila.update(cambios)
    return fila


def _texto_del_pdf(pdf: bytes) -> str:
    fragmentos = []
    for trozo in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        datos = trozo.group(1).rstrip(b"\r\n")
        for intento in (lambda d: base64.a85decode(d, adobe=True), lambda d: d):
            try:
                fragmentos.append(zlib.decompress(intento(datos)))
                break
            except Exception:
                continue
    return "\n".join(f.decode("latin-1") for f in fragmentos)


@pytest.fixture(autouse=True)
def _rate_limit_limpio():
    rate_limit.reiniciar()
    yield
    rate_limit.reiniciar()


@pytest.fixture
def db():
    sesion = AsyncMock()
    app.dependency_overrides[get_db] = lambda: sesion
    yield sesion
    app.dependency_overrides.clear()


@pytest.fixture
def cliente():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ============================================================
# 2. NORMALIZACIÓN DE NIT Y CÓDIGOS
# ============================================================

@pytest.mark.parametrize("entrada, completo, base", [
    ("900123456-7", "9001234567", "900123456"),
    ("900.123.456-7", "9001234567", "900123456"),
    (" 900 123 456 - 7 ", "9001234567", "900123456"),
    ("900123456–7", "9001234567", "900123456"),  # semiraya pegada desde Word/PDF
    ("900123456", "900123456", "900123456"),
    ("9001234567", "9001234567", "9001234567"),
])
def test_normalizar_nit_acepta_formatos_coherentes(entrada, completo, base):
    assert normalizar_nit(entrada) == {"nit_completo": completo, "nit_base": base}


@pytest.mark.parametrize("entrada", ["", "1", "12345", "900-123-456-7", "abc", "900123456-77", "%"])
def test_normalizar_nit_rechaza_lo_que_no_es_un_nit_completo(entrada):
    assert normalizar_nit(entrada) is None


@pytest.mark.parametrize("entrada", ["CERT-2026-0001", "cert-2026-0001", " CERT 2026 0001 ", "CERT‐2026‐0001"])
def test_normalizar_codigo_ignora_mayusculas_espacios_y_guiones(entrada):
    assert normalizar_codigo(entrada) == "CERT20260001"


# ============================================================
# 4. VALIDAR AUTENTICIDAD CON EL CÓDIGO DEL PDF
# ============================================================

async def test_validar_envia_el_codigo_normalizado(db, cliente):
    db.execute.side_effect = [_una(None)]

    async with cliente as ac:
        await ac.get(f"{BASE}/validar", params={"codigo": "cert‐2026‐0001 "})

    assert db.execute.call_args_list[0].args[1] == {"codigo": "CERT20260001"}


async def test_validar_un_certificado_de_empresa_inactiva_lo_dice(db, cliente):
    db.execute.side_effect = [_una({
        "codigo_verificacion": "CERT-2026-0001", "cert_estado": "VIGENTE",
        "cert_emision": date(2026, 1, 1), "cert_vence": date(2099, 1, 1),
        "numero_radicado": "RAD-1", "estado_tramite": "Aprobada", "fecha_radicacion": None,
        "alcance_certificacion": None, "empresa": "Empresa Cerrada", "nit": "900123456-7",
        "ciudad": None, "estado_empresa": "Inactiva", "norma_codigo": None,
        "norma_nombre": None, "norma_version": None,
    })]

    async with cliente as ac:
        datos = (await ac.get(f"{BASE}/validar", params={"codigo": "CERT-2026-0001"})).json()

    assert datos["autentico"] is True
    assert datos["documento"]["estado_vigencia"] == "EMPRESA INACTIVA"
    assert datos["documento"]["empresa_activa"] is False
    assert "inactiva" in datos["detalle"]


# ============================================================
# 1/6. EMPRESA INACTIVA EN TODOS LOS SUBMÓDULOS
# ============================================================

async def test_documentos_de_empresa_inactiva_no_se_muestran_como_tramites(db, cliente):
    db.execute.side_effect = [_filas([
        _fila_documento(estado_empresa="Inactiva"),
        _fila_documento(estado_empresa="Inactiva", numero_radicado="RAD-2026-002"),
    ])]

    async with cliente as ac:
        filas = (await ac.get(f"{BASE}/documentos", params={"nit": "900123456-7"})).json()

    assert len(filas) == 1
    fila = filas[0]
    assert fila["estado_general"] == "EMPRESA INACTIVA"
    assert fila["vigente"] is False
    assert fila["empresa_activa"] is False
    assert fila["codigo_verificacion"] is None
    assert "no cuenta con certificación vigente" in fila["mensaje"]


async def test_empresa_inactiva_sin_tramites_no_aparece_como_registrada(db, cliente):
    db.execute.side_effect = [_filas([]), _filas([{
        "id_empresa": "x", "empresa": "Empresa Cerrada", "nit": "900123456-7",
        "ciudad": None, "estado_empresa": "Inactiva",
    }])]

    async with cliente as ac:
        filas = (await ac.get(f"{BASE}/documentos", params={"nit": "900123456-7"})).json()

    assert [f["estado_general"] for f in filas] == ["EMPRESA INACTIVA"]
    assert filas[0]["estado_vigencia"] == "SIN CERTIFICACIÓN VIGENTE"


async def test_empresa_activa_sin_tramites_sigue_registrada(db, cliente):
    db.execute.side_effect = [_filas([]), _filas([{
        "id_empresa": "x", "empresa": "Café", "nit": "900123456-7", "ciudad": None, "estado_empresa": "Activa",
    }])]

    async with cliente as ac:
        filas = (await ac.get(f"{BASE}/documentos", params={"nit": "900123456-7"})).json()

    assert filas[0]["estado_general"] == "REGISTRADA"


async def test_buscar_empresa_inactiva_no_la_muestra_certificada(db, cliente):
    _cargar_empresa(db, EMPRESA_INACTIVA, [_cert("CERT-2026-0001")])

    async with cliente as ac:
        empresa = (await ac.get(f"{BASE}/empresa/900123456-7")).json()[0]

    assert empresa["empresa_activa"] is False
    assert empresa["certificada"] is False
    assert empresa["certificados"] == []
    assert empresa["certificados_vigentes"] == 0


async def test_un_certificado_suspendido_no_cuenta_como_vigente(db, cliente):
    db.execute.side_effect = [_filas([_fila_documento(cert_estado="SUSPENDIDO")])]

    async with cliente as ac:
        fila = (await ac.get(f"{BASE}/documentos", params={"codigo": "RAD-2026-001"})).json()[0]

    assert fila["vigente"] is False
    assert fila["estado_general"] == "CERTIFICADO SUSPENDIDO"


async def test_el_radicado_se_busca_exacto(db, cliente):
    db.execute.side_effect = [_filas([])]

    async with cliente as ac:
        await ac.get(f"{BASE}/documentos", params={"codigo": "rad 2026-001"})

    sql, parametros = db.execute.call_args_list[0].args
    assert "ILIKE" not in str(sql).upper()
    assert parametros == {"codigo": "RAD2026001"}


# ============================================================
# 5. CONSTANCIA: SIN VIGENTES NO HAY PDF; ELEGIR UNO O TODOS
# ============================================================

async def test_sin_certificados_vigentes_no_hay_constancia(db, cliente):
    _cargar_empresa(db, EMPRESA_ACTIVA, [])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf")

    assert respuesta.status_code == 409
    assert "no tiene certificados vigentes" in respuesta.json()["detail"]


async def test_empresa_inactiva_no_descarga_constancia(db, cliente):
    _cargar_empresa(db, EMPRESA_INACTIVA, [_cert("CERT-2026-0001")])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf")

    assert respuesta.status_code == 409
    assert "inactiva" in respuesta.json()["detail"]


async def test_constancia_de_un_solo_certificado_elegido(db, cliente):
    _cargar_empresa(db, EMPRESA_ACTIVA, [_cert("CERT-2026-0001"), _cert("CERT-2026-0002", "GTC")])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf", params={"codigo": "cert-2026-0002"})

    assert respuesta.status_code == 200
    assert 'filename="constancia-900123456-7-CERT-2026-0002.pdf"' in respuesta.headers["content-disposition"]
    texto = _texto_del_pdf(respuesta.content)
    assert "CERT-2026-0002" in texto
    assert "CERT-2026-0001" not in texto


async def test_constancia_con_todos_los_certificados(db, cliente):
    _cargar_empresa(db, EMPRESA_ACTIVA, [_cert("CERT-2026-0001"), _cert("CERT-2026-0002", "GTC")])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf")

    texto = _texto_del_pdf(respuesta.content)
    assert "CERTIFICADOS VIGENTES INCLUIDOS" in texto
    assert "CERT-2026-0001" in texto and "CERT-2026-0002" in texto


async def test_constancia_con_codigo_ajeno_da_404(db, cliente):
    _cargar_empresa(db, EMPRESA_ACTIVA, [_cert("CERT-2026-0001")])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf", params={"codigo": "OTRO-1"})

    assert respuesta.status_code == 404


def test_las_paginas_deshabilitan_la_constancia_sin_vigentes():
    for pagina in ("static/constancia.html", "static/buscar_e.html"):
        html = open(pagina, encoding="utf-8").read()
        assert "disabled>Descargar" in html, pagina
        assert "Todos los certificados vigentes" in html, pagina


# ============================================================
# 3. CONSULTA PÚBLICA DE CERTIFICADOS (modules/certificados)
# ============================================================

class _BD:
    def __init__(self, fila):
        self.fila = fila
        self.llamadas = []

    async def execute(self, sql, params=None):
        self.llamadas.append((str(sql), params))
        r = MagicMock()
        r.mappings().first.return_value = self.fila
        return r


def _fila_publica(**cambios):
    fila = {
        "id_certificado": "11111111-1111-4111-8111-111111111111",
        "codigo_verificacion": "CERT-2026-0001", "estado_certificado": "VIGENTE",
        "fecha_emision": date(2026, 1, 1), "fecha_vencimiento": date(2099, 1, 1),
        "huella_pdf": None, "huella_certificado": None, "firmado": False, "firmante": None,
        "empresa": "Café", "nit": "900123456-7", "estado_empresa": "Activa",
        "norma_codigo": "NTC", "norma": "ISO 9001", "norma_version": "2015", "alcance": "Todo",
    }
    fila.update(cambios)
    return fila


def test_consulta_publica_por_codigo_solo_publica_certificados_firmados():
    # Decisión del equipo: solo se publican certificados firmados (PAdES) por el
    # líder del comité. El código se sigue comparando sin mayúsculas ni guiones.
    from modules.certificados.certificados_service import CertificadosService

    bd = _BD(_fila_publica())
    certificado = asyncio.run(CertificadosService(bd).publico("cert 2026-0001"))

    assert certificado["codigo_verificacion"] == "CERT-2026-0001"
    assert "id_certificado" not in certificado
    sql, params = bd.llamadas[0]
    assert params == {"codigo": "CERT20260001"}
    for requisito in ("id_firmante IS NOT NULL", "huella_firmante IS NOT NULL",
                      "codigo_hash IS NOT NULL", "huella_pdf IS NOT NULL"):
        assert requisito in sql


def test_pdf_publico_sin_firma_explica_que_no_hay_pdf_firmado():
    from modules.certificados.certificados_service import CertificadosService

    with pytest.raises(HTTPException) as error:
        asyncio.run(CertificadosService(_BD(_fila_publica())).pdf_publico_firmado("CERT-2026-0001"))

    assert error.value.status_code == 404
    assert "firma digital" in error.value.detail


def test_certificado_publico_de_empresa_inactiva_no_se_muestra():
    from modules.certificados.certificados_service import CertificadosService

    with pytest.raises(HTTPException) as error:
        asyncio.run(CertificadosService(_BD(_fila_publica(estado_empresa="Inactiva"))).publico("CERT-2026-0001"))

    assert error.value.status_code == 404
    assert "inactiva" in error.value.detail


def test_metricas_y_listado_publico_usan_el_mismo_criterio_con_firma():
    from modules.certificados import certificados_service as cs

    for criterio in (cs.CRITERIO_PUBLICO, cs.CRITERIO_PUBLICO_C):
        assert "huella_pdf IS NOT NULL" in criterio and "id_firmante IS NOT NULL" in criterio
        assert "publico_certificado IS TRUE" in criterio
        assert "'activa'" in criterio


# ============================================================
# 8. CÓDIGO DE VERIFICACIÓN POR CORREO
# ============================================================

def _bd_auth(usuario):
    """Sesión simulada: la primera consulta devuelve `usuario`; el resto, nada."""
    bd = AsyncMock()
    bd.in_transaction = MagicMock(return_value=False)
    llamadas = []

    async def execute(sql, params=None):
        llamadas.append((str(sql), params))
        r = MagicMock()
        r.mappings().first.return_value = usuario if len(llamadas) == 1 else None
        return r

    bd.execute.side_effect = execute
    bd.llamadas = llamadas
    return bd


def _usuario(**cambios):
    u = {
        "id_usuario": "u-1", "nombre": "Ana", "correo": "ana@example.com",
        "password_hash": "x", "estado": "Activo", "intentos_fallidos": 2,
        "ultimo_intento": datetime.now(timezone.utc) - timedelta(seconds=20),
        "codigo_verificacion": None, "codigo_expira": None, "bloqueado_hasta": None,
        "rol_id": None, "codigo_verificado": False, "fecha_cambio_password": None,
        "mfa_activado": False, "mfa_codigo": None, "mfa_expira": None, "mfa_verificado": False,
        "ultimo_inicio_sesion": None, "rol_nombre": "Empresa",
    }
    u.update(cambios)
    return u


def _login(bd):
    from modules.auth.auth_service import AuthService

    with patch("modules.auth.auth_service.verify_password", return_value=False):
        with pytest.raises(HTTPException) as error:
            asyncio.run(AuthService(bd).login("ana@example.com", "mala"))
    return error.value


def test_tercer_intento_envia_el_codigo():
    bd = _bd_auth(_usuario())
    with patch("modules.auth.auth_service.MailService.enviar_codigo_verificacion", new=AsyncMock()) as envio:
        error = _login(bd)

    assert error.status_code == 403
    assert error.detail["accion"] == "codigo"
    assert error.detail["enviado"] is True
    envio.assert_awaited_once()
    assert envio.await_args.kwargs["destinatario"] == "ana@example.com"
    update = next(p for sql, p in bd.llamadas if p and "codigo" in p)
    assert update["ultimo_envio"] is not None


def test_si_el_smtp_falla_no_hay_500_y_se_ofrece_reenviar():
    bd = _bd_auth(_usuario())
    with patch(
        "modules.auth.auth_service.MailService.enviar_codigo_verificacion",
        new=AsyncMock(side_effect=ConnectionError("smtp caído")),
    ):
        error = _login(bd)

    assert error.status_code == 403
    assert error.detail["enviado"] is False
    assert "Reenviar código" in error.detail["mensaje"]


def test_una_verificacion_antigua_no_salta_la_fase_del_codigo():
    """
    Antes `codigo_verificado` quedaba en TRUE hasta un login correcto: días
    después, 3 fallos ya no enviaban código (se exigían 5 y luego un enlace).
    """
    bd = _bd_auth(_usuario(
        codigo_verificado=True, intentos_fallidos=0,
        ultimo_intento=datetime.now(timezone.utc) - timedelta(days=3),
    ))
    error = _login(bd)

    assert error.status_code == 401
    assert "requerir un código de verificación" in error.detail
    update = next(p for sql, p in bd.llamadas if p and "verificado" in p)
    assert update["verificado"] is False


def _reenviar(bd, envio=None):
    from modules.auth.auth_service import AuthService

    envio = envio or AsyncMock()
    with patch("modules.auth.auth_service.MailService.enviar_codigo_verificacion", new=envio):
        return asyncio.run(AuthService(bd).reenviar_codigo("ana@example.com")), envio


def _pendiente(**cambios):
    fila = {
        "id_usuario": "u-1", "correo": "ana@example.com", "codigo_verificacion": "hash",
        "ultimo_envio_codigo": None, "codigo_verificado": False, "intentos_fallidos": 3,
    }
    fila.update(cambios)
    return fila


def test_reenviar_codigo_genera_y_envia_uno_nuevo():
    bd = _bd_auth(_pendiente())
    respuesta, envio = _reenviar(bd)

    envio.assert_awaited_once()
    assert re.fullmatch(r"\d{6}", envio.await_args.kwargs["codigo"])
    assert respuesta["espera_reenvio"] == 60
    assert any("UPDATE usuario" in sql for sql, _ in bd.llamadas)


def test_reenviar_codigo_respeta_la_espera_minima():
    bd = _bd_auth(_pendiente(ultimo_envio_codigo=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)))
    envio = AsyncMock()
    with pytest.raises(HTTPException) as error:
        _reenviar(bd, envio)

    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) in range(45, 51)
    envio.assert_not_awaited()


def test_reenviar_codigo_sin_cuenta_responde_igual_y_no_envia():
    respuesta, envio = _reenviar(_bd_auth(None))

    envio.assert_not_awaited()
    assert "Si la cuenta tiene una verificación pendiente" in respuesta["mensaje"]


def test_reenviar_codigo_si_el_smtp_falla_responde_503():
    with pytest.raises(HTTPException) as error:
        _reenviar(_bd_auth(_pendiente()), AsyncMock(side_effect=OSError("smtp")))

    assert error.value.status_code == 503


async def test_endpoint_reenviar_codigo_existe(cliente):
    sesion = _bd_auth(None)
    app.dependency_overrides[get_db] = lambda: sesion
    try:
        async with cliente as ac:
            respuesta = await ac.post("/auth/reenviar-codigo", json={"correo": "nadie@example.com"})
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200


def test_login_ofrece_reenviar_codigo_y_muestra_errores_legibles():
    html = open("static/login.html", encoding="utf-8").read()
    assert 'id="btnReenviarCodigo"' in html
    assert "/auth/reenviar-codigo" in html
    assert "errores-api.js" in html


# ============================================================
# 7. ERRORES 422 LEGIBLES EN LAS PÁGINAS PÚBLICAS
# ============================================================

@pytest.mark.parametrize("pagina", [
    "register.html", "login.html", "index.html", "vigencia.html", "validar.html",
    "constancia.html", "consulta_norma.html", "buscar_e.html", "cambiar_password.html",
])
def test_las_paginas_publicas_no_pintan_detail_crudo(pagina):
    html = open(f"static/{pagina}", encoding="utf-8").read()
    assert "errores-api.js" in html
    assert "mensajeErrorApi(" in html
    assert not re.search(r"(textContent|innerHTML)\s*=\s*data\.detail\b", html)
    assert "detalle = datos.detail ||" not in html and "detalle = data.detail ||" not in html


def test_el_traductor_de_errores_cubre_las_listas_de_fastapi():
    js = open("static/errores-api.js", encoding="utf-8").read()
    assert "Array.isArray(detalle)" in js
    assert "string_too_short" in js
    assert "window.validarNit" in js
