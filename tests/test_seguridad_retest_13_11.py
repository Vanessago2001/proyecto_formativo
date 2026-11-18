"""Hallazgos de seguridad del retest del 13/11.

1. /uploads era público: ahora los archivos se entregan con enlaces firmados.
2. Un auditor recibía las 11 empresas con correo y dirección.
4. La ficha pública por NIT aceptaba un NIT parcial; y validar un código que
   existe pero no está publicado con firma decía que no existía.
5. Las páginas internas se veían sin sesión.
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core import archivos_firmados as af
from core.database import get_db
from core.security import get_current_user
from main import app
from modules.auditores.auditor_schema import DocumentoAuditorCrear, PerfilAuditorCrear
from modules.consultas_p import rate_limit


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------


class Resultado:
    def __init__(self, primera=None, todas=None):
        self._primera, self._todas = primera, todas or []

    def mappings(self):
        return self

    def first(self):
        return self._primera

    def all(self):
        return self._todas


class BaseFalsa:
    """Responde según el texto de la consulta y guarda lo ejecutado."""

    def __init__(self, respuestas):
        self.respuestas = respuestas  # lista de (fragmento_sql, Resultado)
        self.sentencias = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))
        for fragmento, resultado in self.respuestas:
            if fragmento in sql:
                return resultado
        return Resultado()


async def pedir(metodo, ruta, usuario=None, db=None, **kwargs):
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    if usuario is not None:
        app.dependency_overrides[get_current_user] = lambda: usuario
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    raiz = (tmp_path / "uploads").resolve()
    (raiz / "auditores" / "perfiles").mkdir(parents=True)
    (raiz / "auditores" / "hoja.pdf").write_bytes(b"%PDF-1.4 prueba")
    (raiz / "auditores" / "perfiles" / "foto.png").write_bytes(b"\x89PNG prueba")
    (tmp_path / "secreto.txt").write_text("fuera de uploads")
    monkeypatch.setattr(af, "RAIZ_UPLOADS", raiz)
    return raiz


# ======================================================================
# 1. ARCHIVOS DE uploads/ CON ENLACE FIRMADO
# ======================================================================


async def test_uploads_ya_no_es_publico(uploads):
    respuesta = await pedir("get", "/uploads/auditores/hoja.pdf")
    assert respuesta.status_code == 404


async def test_enlace_firmado_entrega_el_archivo_en_linea(uploads):
    url = af.firmar_url("/uploads/auditores/hoja.pdf")
    assert url.startswith("/archivos/") and url.endswith("/auditores/hoja.pdf")

    respuesta = await pedir("get", url)

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.headers["content-disposition"].startswith("inline")
    assert respuesta.content == b"%PDF-1.4 prueba"


async def test_enlace_vencido_responde_403(uploads):
    url = af.firmar_url("/uploads/auditores/hoja.pdf", ahora=time.time() - 3600)
    respuesta = await pedir("get", url)
    assert respuesta.status_code == 403


async def test_firma_alterada_o_de_otro_archivo_responde_403(uploads):
    url = af.firmar_url("/uploads/auditores/hoja.pdf")
    otra = url.replace("/auditores/hoja.pdf", "/auditores/perfiles/foto.png")
    assert (await pedir("get", otra)).status_code == 403
    exp, firma = url.split("/")[2:4]
    alterada = url.replace(firma, ("0" if firma[0] != "0" else "1") + firma[1:])
    assert (await pedir("get", alterada)).status_code == 403
    sin_firma = f"/archivos/{exp}/{'a' * 64}/auditores/hoja.pdf"
    assert (await pedir("get", sin_firma)).status_code == 403


def test_no_permite_salir_de_uploads():
    assert af.ruta_relativa("/uploads/../secreto.txt") is None
    assert af.ruta_relativa("/uploads/auditores/%2e%2e/%2e%2e/secreto.txt") is None
    assert af.ruta_relativa("/static/logo.png") is None


async def test_path_traversal_codificado_no_entrega_nada(uploads):
    exp = int(time.time()) + 600
    relativo = "auditores/../../secreto.txt"
    url = f"/archivos/{exp}/{af._firma(relativo, exp)}/auditores/..%2F..%2Fsecreto.txt"
    respuesta = await pedir("get", url)
    assert respuesta.status_code in (403, 404)
    assert b"fuera de uploads" not in respuesta.content


def test_las_respuestas_json_firman_las_rutas_guardadas():
    ahora = 1_800_000_000
    cuerpo = b'{"url_archivo":"/uploads/auditores/hoja.pdf","foto_url":"uploads/auditores/perfiles/foto.png","otro":"/static/x.png"}'
    firmado = af.firmar_en_json(cuerpo, ahora=ahora)
    assert b"/uploads/" not in firmado
    assert b'"/static/x.png"' in firmado
    assert af.firmar_url("/uploads/auditores/hoja.pdf", ahora=ahora).encode() in firmado


async def test_el_middleware_firma_al_vuelo_sin_tocar_la_base():
    id_usuario = uuid.uuid4()
    filas = [{
        "id_usuario": id_usuario, "nombre": "Ana", "correo": "ana@x.co", "estado": "Activo",
        "foto_url": "/uploads/auditores/perfiles/foto.png",
    }]
    db = BaseFalsa([("FROM usuario", Resultado(todas=filas, primera=filas[0]))])
    respuesta = await pedir(
        "get", "/admin/auditores-registrados", usuario={"id_usuario": "x", "role_name": "Coordinador"}, db=db,
    )
    assert respuesta.status_code == 200, respuesta.text
    assert "/uploads/" not in respuesta.text
    assert "/archivos/" in respuesta.text


def test_el_enlace_firmado_vuelve_a_la_ruta_guardada_al_reenviarse():
    url = af.firmar_url("/uploads/auditores/perfiles/foto.png")
    perfil = PerfilAuditorCrear(
        ciudad_residencia="Pereira", departamento_residencia="Risaralda",
        modalidad_preferida="Presencial", foto_url=url, resumen_profesional="x",
    )
    assert perfil.foto_url == "/uploads/auditores/perfiles/foto.png"
    doc = DocumentoAuditorCrear(nombre_archivo="a.pdf", tipo_documento="CV", url_archivo=url + "?v=1")
    assert doc.url_archivo == "/uploads/auditores/perfiles/foto.png"


async def test_firmar_sin_sesion_responde_401():
    respuesta = await pedir("get", "/archivos/firmar", params={"ruta": "/uploads/auditores/hoja.pdf"})
    assert respuesta.status_code == 401


@pytest.mark.parametrize("rol", ["Coordinador", "Auxiliar"])
async def test_coordinador_y_auxiliar_obtienen_enlace(rol):
    respuesta = await pedir(
        "get", "/archivos/firmar", usuario={"id_usuario": "1", "role_name": rol},
        db=BaseFalsa([]), params={"ruta": "/uploads/auditores/hoja.pdf"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["url"].startswith("/archivos/")


@pytest.mark.parametrize("rol", ["Empresa", "Comité", "Publico"])
async def test_otros_roles_no_obtienen_enlace(rol):
    respuesta = await pedir(
        "get", "/archivos/firmar", usuario={"id_usuario": "1", "role_name": rol},
        db=BaseFalsa([]), params={"ruta": "/uploads/auditores/hoja.pdf"},
    )
    assert respuesta.status_code == 403


async def test_el_auditor_solo_firma_sus_propios_archivos():
    dueno = BaseFalsa([("FROM documento_auditor", Resultado(primera=(1,)))])
    ajeno = BaseFalsa([("FROM documento_auditor", Resultado(primera=None))])
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}

    ok = await pedir("get", "/archivos/firmar", usuario=usuario, db=dueno,
                     params={"ruta": "/uploads/auditores/hoja.pdf"})
    no = await pedir("get", "/archivos/firmar", usuario=usuario, db=ajeno,
                     params={"ruta": "/uploads/auditores/hoja.pdf"})

    assert ok.status_code == 200
    assert no.status_code == 403
    assert dueno.sentencias[0][1] == {"url": "/uploads/auditores/hoja.pdf", "id_usuario": usuario["id_usuario"]}


# ======================================================================
# 2. EMPRESAS: EL AUDITOR SOLO VE DATOS MÍNIMOS DE SUS ASIGNADAS
# ======================================================================

ID_EMPRESA = str(uuid.uuid4())
EMPRESA_COMPLETA = {
    "id_empresa": ID_EMPRESA, "nombre": "Cafe del Eje", "nit": "900123456-7",
    "ciudad": "Manizales", "direccion": "Calle 1", "correo": "c@x.co", "estado": "Activa",
}


async def test_el_auditor_lista_solo_empresas_asignadas_sin_contacto():
    minima = {k: EMPRESA_COMPLETA[k] for k in ("id_empresa", "nombre", "nit", "ciudad", "estado")}
    db = BaseFalsa([("JOIN auditores_solicitud", Resultado(todas=[minima]))])
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}

    respuesta = await pedir("get", "/api/empresas/", usuario=usuario, db=db)

    assert respuesta.status_code == 200
    [sql_params] = db.sentencias
    assert "a.id_auditor = :id_auditor" in sql_params[0]
    assert "correo" not in sql_params[0] and "direccion" not in sql_params[0]
    assert sql_params[1]["id_auditor"] == usuario["id_usuario"]
    assert "correo" not in respuesta.json()[0]


async def test_el_auditor_no_abre_una_empresa_que_no_tiene_asignada():
    db = BaseFalsa([("FROM auditores_solicitud", Resultado(primera=None))])
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}
    for ruta in ("", "/sedes", "/documentos", "/solicitudes"):
        respuesta = await pedir("get", f"/api/empresas/{ID_EMPRESA}{ruta}", usuario=usuario, db=db)
        assert respuesta.status_code == 404, ruta


async def test_el_auditor_asignado_ve_la_empresa_sin_correo_ni_direccion():
    db = BaseFalsa([
        ("FROM auditores_solicitud", Resultado(primera=(1,))),
        ("FROM empresa", Resultado(primera=EMPRESA_COMPLETA, todas=[EMPRESA_COMPLETA])),
    ])
    usuario = {"id_usuario": str(uuid.uuid4()), "role_name": "Auditor"}

    respuesta = await pedir("get", f"/api/empresas/{ID_EMPRESA}", usuario=usuario, db=db)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["nombre"] == "Cafe del Eje"
    assert "correo" not in datos and "direccion" not in datos


async def test_el_coordinador_sigue_viendo_el_listado_completo():
    db = BaseFalsa([("FROM empresa", Resultado(todas=[EMPRESA_COMPLETA]))])
    respuesta = await pedir("get", "/api/empresas/", usuario={"id_usuario": "1", "role_name": "Coordinador"}, db=db)
    assert respuesta.status_code == 200
    assert respuesta.json()[0]["correo"] == "c@x.co"


async def test_el_catalogo_de_empresas_de_auditores_exige_sesion():
    respuesta = await pedir("get", "/auditores/catalogos/empresas")
    assert respuesta.status_code == 401


# ======================================================================
# 4. CONSULTA PÚBLICA
# ======================================================================


@pytest.fixture(autouse=False)
def limite_limpio():
    rate_limit.reiniciar()
    yield
    rate_limit.reiniciar()


@pytest.mark.parametrize("nit", ["900", "1", "Cafe", "%25"])
async def test_ficha_y_constancia_exigen_nit_completo(limite_limpio, nit):
    db = AsyncMock()
    # La ficha exige NIT completo solo con exacto=true: sin él es el buscador
    # público unificado del equipo, que admite parte del NIT o el nombre.
    for ruta in (f"/api/consultas-publicas/empresa/{nit}?exacto=true", f"/api/consultas-publicas/constancia/{nit}/pdf"):
        respuesta = await pedir("get", ruta, db=db)
        assert respuesta.status_code == 422, ruta
    db.execute.assert_not_called()


def _fila(fila):
    resultado = MagicMock()
    resultado.mappings().first.return_value = fila
    return resultado


async def test_validar_codigo_existente_sin_firma_no_niega_ni_revela(limite_limpio):
    db = AsyncMock()
    db.execute.side_effect = [_fila(None), _fila({"existe": 1})]

    respuesta = await pedir("get", "/api/consultas-publicas/validar", db=db, params={"codigo": "CERT-2026-0001"})

    datos = respuesta.json()
    assert respuesta.status_code == 200
    assert datos["autentico"] is False
    assert datos["documento"] is None
    assert "aún no está publicado con firma digital" in datos["detalle"]
    assert "Ningún certificado" not in datos["detalle"]


async def test_validar_codigo_inexistente_lo_dice(limite_limpio):
    db = AsyncMock()
    db.execute.side_effect = [_fila(None), _fila(None)]
    respuesta = await pedir("get", "/api/consultas-publicas/validar", db=db, params={"codigo": "CERT-0000"})
    assert respuesta.json()["detalle"] == "Ningún certificado registrado coincide con ese código."


# ======================================================================
# 5. PÁGINAS INTERNAS SIN SESIÓN
# ======================================================================

INTERNAS = [
    "/dashboard", "/empresas", "/comite", "/pqrs-gestion", "/permisos-auxiliar", "/reportes",
    "/solicitudes", "/auditores-registrados", "/banco-auditores",
    "/gestion-certificados", "/consultar-agenda-auditor", "/empresa", "/apelacion", "/profile",
]
PUBLICAS = [
    "/", "/login", "/register", "/reset-password", "/pqrs", "/verificar-certificado",
    "/buscar_empresa", "/consulta-norma", "/vigencia", "/validar", "/constancia", "/cuenta-inactiva",
]


@pytest.mark.parametrize("ruta", INTERNAS)
async def test_pagina_interna_lleva_la_guardia_de_sesion(ruta):
    respuesta = await pedir("get", ruta)
    assert respuesta.status_code == 200
    html = respuesta.text
    guardia = html.find('<script src="/static/requiere-sesion.js"></script>')
    assert guardia != -1
    # Va al inicio del <head>, antes de cualquier contenido de la página.
    assert guardia < html.lower().find("<body")


@pytest.mark.parametrize("ruta", PUBLICAS)
async def test_pagina_publica_no_lleva_la_guardia(ruta):
    respuesta = await pedir("get", ruta)
    assert respuesta.status_code == 200
    assert "requiere-sesion.js" not in respuesta.text


def test_la_guardia_redirige_a_login_sin_token():
    with open("static/requiere-sesion.js", encoding="utf-8") as archivo:
        js = archivo.read()
    assert 'localStorage.getItem("access_token")' in js
    assert 'window.location.replace("/login")' in js
