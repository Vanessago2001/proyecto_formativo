"""
Tests del portal público de consultas (M11).

Estos endpoints responden sin token a propósito, así que lo que se protege aquí
es otra cosa:

1. Que sigan existiendo — ya se perdieron una vez al integrar los módulos de
   empresa y apelaciones, y hubo que restaurarlos desde el commit 353ea89.
2. Que no filtren datos de contacto (`correo`, `direccion`) al público.
3. Que tengan límite de peticiones, porque son la única superficie de la app
   que se puede consumir sin autenticar.
4. Que el menú "Consulta pública" del nav esté completo en las cuatro páginas
   públicas y no enlace a rutas inexistentes.
"""

import re
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from main import app
from modules.consultas_p import rate_limit

BASE = "/api/consultas-publicas"

EMPRESA = {
    "id_empresa": "11111111-1111-1111-1111-111111111111",
    "nombre": "Café del Eje",
    "nit": "900123456-7",
    "ciudad": "Manizales",
}

ULTIMA_SOLICITUD = {
    "numero_radicado": "RAD-2026-001",
    "estado": "Radicada",
    "fecha": "2026-09-01",
    "fecha_radicacion": "2026-09-02",
    "alcance_certificacion": "ISO 9001",
    "numero_empleados": 12,
    "numero_sedes": 1,
    "persona_contacto": "Ana Ramírez",
    "norma": "ISO 9001",
}


def _filas(filas):
    resultado = MagicMock()
    resultado.mappings().all.return_value = filas
    return resultado


def _una_fila(fila):
    resultado = MagicMock()
    resultado.mappings().first.return_value = fila
    return resultado


def _conteo(total):
    resultado = MagicMock()
    resultado.mappings().first.return_value = {"total": total}
    return resultado


def _cargar_busqueda_por_nit(db, empresas):
    """
    `buscar_por_nit` ejecuta 8 consultas: la de empresas y, por cada una,
    siete de detalle (certificados, historial, tres conteos y solicitudes).
    """
    detalle = []
    for _ in empresas:
        detalle += [
            _filas([]),        # certificados vigentes
            _filas([]),        # historial de certificados
            _conteo(2),        # total de solicitudes
            _conteo(1),        # total de sedes
            _conteo(3),        # total de documentos
            _una_fila(ULTIMA_SOLICITUD),
            _filas([]),        # últimas 10 solicitudes
        ]
    db.execute.side_effect = [_filas(empresas)] + detalle
    return db


def _sql_ejecutados(db):
    """Texto de cada sentencia que pasó por la sesión."""
    return [str(llamada.args[0]) for llamada in db.execute.call_args_list]


@pytest.fixture(autouse=True)
def _registro_de_rate_limit_limpio():
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
# 1. LOS ENDPOINTS EXISTEN Y NO PIDEN TOKEN
# ============================================================

async def test_buscar_empresa_por_nit_responde_sin_token(db, cliente):
    _cargar_busqueda_por_nit(db, [dict(EMPRESA)])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/empresa/900123456-7")

    assert respuesta.status_code == status.HTTP_200_OK
    datos = respuesta.json()
    assert len(datos) == 1
    assert datos[0]["nombre"] == "Café del Eje"
    assert datos[0]["ultima_solicitud"]["numero_radicado"] == "RAD-2026-001"


async def test_consulta_de_documentos_responde_sin_token(db, cliente):
    # Sin resultados la consulta ejecuta dos sentencias (principal y respaldo).
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"nit": "900123456-7"})

    assert respuesta.status_code == status.HTTP_200_OK


async def test_las_rutas_viejas_de_empresas_ya_no_responden(cliente):
    """El portal se movió de prefijo: las rutas anteriores deben dar 404."""
    async with cliente as ac:
        antiguas = await ac.get("/api/empresas/buscar/900123456-7")

    assert antiguas.status_code == status.HTTP_404_NOT_FOUND


# ============================================================
# 2. NO SE FILTRAN DATOS DE CONTACTO
# ============================================================

async def test_la_busqueda_por_nit_no_consulta_correo_ni_direccion(db, cliente):
    """
    Se revisa el SQL y no la respuesta: el mock devolvería lo que se le ponga,
    así que la única forma de detectar que alguien volvió a SELECTear las
    columnas de contacto es mirar las sentencias.
    """
    _cargar_busqueda_por_nit(db, [dict(EMPRESA)])

    async with cliente as ac:
        await ac.get(f"{BASE}/empresa/900123456-7")

    for sql in _sql_ejecutados(db):
        assert "correo" not in sql.lower(), f"Consulta pública expone 'correo': {sql}"
        assert "direccion" not in sql.lower(), f"Consulta pública expone 'direccion': {sql}"


async def test_la_consulta_de_documentos_no_expone_datos_de_contacto(db, cliente):
    db.execute.side_effect = [_filas([]), _filas([dict(EMPRESA)])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"nit": "900123456-7"})

    assert respuesta.status_code == status.HTTP_200_OK
    for sql in _sql_ejecutados(db):
        assert "correo" not in sql.lower()
        assert "direccion" not in sql.lower()


# ============================================================
# 3. COMPORTAMIENTO DE LA CONSULTA DE DOCUMENTOS
# ============================================================

async def test_consulta_sin_parametros_devuelve_lista_vacia(db, cliente):
    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos")

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json() == []
    db.execute.assert_not_called()


async def test_un_certificado_vigente_se_reporta_como_certificada(db, cliente):
    db.execute.side_effect = [_filas([{
        "id_solicitud": "s-1",
        "numero_radicado": "RAD-2026-001",
        "estado_tramite": "Aprobada",
        "fecha_tramite": "2026-09-01",
        "alcance_certificacion": "ISO 9001",
        "id_empresa": EMPRESA["id_empresa"],
        "empresa": EMPRESA["nombre"],
        "nit": EMPRESA["nit"],
        "ciudad": EMPRESA["ciudad"],
        "norma_codigo": "NTC",
        "norma_nombre": "ISO 9001",
        "norma_version": "2015",
        "codigo_verificacion": "CV-123",
        "cert_estado": "Vigente",
        "cert_emision": date(2026, 1, 1),
        "cert_vence": date(2099, 1, 1),
        "url_certificado": None,
    }])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"codigo": "RAD-2026-001"})

    fila = respuesta.json()[0]
    assert fila["vigente"] is True
    assert fila["estado_general"] == "CERTIFICADA"
    assert fila["norma_completa"] == "NTC ISO 9001 2015"
    assert "CV-123" in fila["mensaje"]


async def test_un_tramite_sin_certificado_se_reporta_en_tramite(db, cliente):
    db.execute.side_effect = [_filas([{
        "id_solicitud": "s-2",
        "numero_radicado": "RAD-2026-002",
        "estado_tramite": "Radicada",
        "fecha_tramite": "2026-09-05",
        "alcance_certificacion": None,
        "id_empresa": EMPRESA["id_empresa"],
        "empresa": EMPRESA["nombre"],
        "nit": EMPRESA["nit"],
        "ciudad": EMPRESA["ciudad"],
        "norma_codigo": None,
        "norma_nombre": None,
        "norma_version": None,
        "codigo_verificacion": None,
        "cert_estado": None,
        "cert_emision": None,
        "cert_vence": None,
        "url_certificado": None,
    }])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"codigo": "RAD-2026-002"})

    fila = respuesta.json()[0]
    assert fila["vigente"] is False
    assert fila["estado_general"] == "EN TRAMITE - Radicada"
    assert fila["norma_completa"] == "--"


# ============================================================
# 4. CONSTANCIA EN PDF (PUB-009)
# ============================================================

async def test_la_constancia_se_descarga_como_pdf(db, cliente):
    _cargar_busqueda_por_nit(db, [dict(EMPRESA)])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/900123456-7/pdf")

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.content.startswith(b"%PDF")
    assert 'filename="constancia-900123456-7.pdf"' in respuesta.headers["content-disposition"]


async def test_la_constancia_de_un_nit_inexistente_da_404(db, cliente):
    _cargar_busqueda_por_nit(db, [])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/constancia/000000000-0/pdf")

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND


# ============================================================
# 5. LÍMITE DE PETICIONES POR IP
# ============================================================

async def test_el_portal_bloquea_quien_consulta_demasiado(db, cliente, monkeypatch):
    monkeypatch.setattr(rate_limit, "PETICIONES_PERMITIDAS", 5)
    # Siempre vacío: con `nit` y sin resultados la consulta ejecuta dos
    # sentencias (la principal y el respaldo de empresas registradas).
    db.execute.return_value = _filas([])

    async with cliente as ac:
        codigos = [
            (await ac.get(f"{BASE}/documentos", params={"nit": "9001"})).status_code
            for _ in range(7)
        ]

    assert codigos[:5] == [status.HTTP_200_OK] * 5
    assert codigos[5:] == [status.HTTP_429_TOO_MANY_REQUESTS] * 2


async def test_un_nit_con_comodines_no_se_vuelve_consulta_universal(db, cliente):
    """
    `%` y `_` deben buscarse como texto literal. Sin escaparlos, un `%` hace
    que el ILIKE coincida con toda la tabla empresa.
    """
    _cargar_busqueda_por_nit(db, [])

    async with cliente as ac:
        await ac.get(f"{BASE}/empresa/%25")

    parametros = db.execute.call_args_list[0].args[1]
    assert "\\%" in parametros["nit_parcial"]


# ============================================================
# 6. LA PÁGINA Y EL MÓDULO VAN DE LA MANO
# ============================================================

async def test_la_pagina_de_busqueda_la_sirve_el_modulo(cliente):
    """`/buscar_empresa` la sirve paginas_router.py, no main.py."""
    async with cliente as ac:
        respuesta = await ac.get("/buscar_empresa")

    assert respuesta.status_code == status.HTTP_200_OK
    assert "text/html" in respuesta.headers["content-type"]
    assert "Buscar empresa por NIT" in respuesta.text


async def test_la_pagina_apunta_al_api_del_modulo(cliente):
    """
    Si alguien cambia el prefijo de la API o restaura la ruta vieja en
    empresas_router, la página quedaría apuntando a un endpoint que ya no
    existe. Este test ata las dos puntas.
    """
    async with cliente as ac:
        html = (await ac.get("/buscar_empresa")).text

    assert f"{BASE}/empresa/" in html, "buscar_e.html no llama al endpoint del módulo"
    assert f"{BASE}/constancia/" in html, "buscar_e.html no llama a la constancia del módulo"
    assert "/api/empresas/" not in html, "buscar_e.html sigue apuntando al módulo de empresas"


# ============================================================
# 7. MENÚ "CONSULTA PÚBLICA" DEL NAV
# ============================================================

# Las páginas que se ven sin iniciar sesión. Todas llevan el menú.
PAGINAS_PUBLICAS = [
    "/",
    "/login",
    "/register",
    "/buscar_empresa",
    "/consulta-norma",
    "/vigencia",
    "/validar",
    "/constancia",
]

ENLACES_DEL_MENU = [
    "/buscar_empresa",
    "/",
    "/consulta-norma",
    "/vigencia",
    "/validar",
    "/constancia",
]

PANEL = re.compile(
    r'<div class="nav-dropdown-panel">(.*?)</div>',
    re.DOTALL,
)
GRUPO_MOVIL = re.compile(
    r'<div class="mobile-menu-group">(.*?)</div>',
    re.DOTALL,
)
ENLACES = re.compile(r'href="([^"]+)"')


def _enlaces_del_menu(html: str) -> list[str]:
    panel = PANEL.search(html)
    assert panel, "la página no tiene el menú desplegable de consulta pública"
    return ENLACES.findall(panel.group(1))


async def test_la_pagina_de_norma_la_sirve_el_modulo(cliente):
    async with cliente as ac:
        respuesta = await ac.get("/consulta-norma")

    assert respuesta.status_code == status.HTTP_200_OK
    assert "text/html" in respuesta.headers["content-type"]
    assert "Consultar norma evaluada" in respuesta.text


async def test_la_pagina_de_norma_apunta_al_api_del_modulo(cliente):
    """Reutiliza `/documentos`: no debe inventar un endpoint propio."""
    async with cliente as ac:
        html = (await ac.get("/consulta-norma")).text

    assert f"{BASE}/documentos" in html


@pytest.mark.parametrize("pagina", PAGINAS_PUBLICAS)
async def test_el_menu_aparece_en_todas_las_paginas_publicas(cliente, pagina):
    async with cliente as ac:
        html = (await ac.get(pagina)).text

    assert "Consulta pública" in html
    assert _enlaces_del_menu(html) == ENLACES_DEL_MENU

    grupo = GRUPO_MOVIL.search(html)
    assert grupo, f"{pagina} no repite el menú en la versión móvil"
    assert ENLACES.findall(grupo.group(1)) == ENLACES_DEL_MENU


async def test_los_enlaces_del_menu_no_estan_muertos(cliente):
    """
    El menú se edita a mano en cuatro archivos HTML; es fácil dejar un enlace
    apuntando a una ruta que no existe. Se leen los href del HTML y se comparan
    contra las rutas reales de la app.
    """
    rutas = set(app.openapi()["paths"])

    async with cliente as ac:
        html = (await ac.get("/login")).text

    assert rutas, "no se pudieron leer las rutas de la aplicación"
    for enlace in _enlaces_del_menu(html):
        assert enlace in rutas, f"el menú enlaza a {enlace}, que no existe"


# ============================================================
# 8. VIGENCIA, PLAZOS Y AUTENTICIDAD
# ============================================================

def _fila_documento(**cambios):
    fila = {
        "id_solicitud": "s-9",
        "numero_radicado": "RAD-2026-009",
        "estado_tramite": "Aprobada",
        "fecha_tramite": date(2026, 1, 1),
        "fecha_radicacion": date(2026, 1, 1),
        "alcance_certificacion": "ISO 9001",
        "id_empresa": EMPRESA["id_empresa"],
        "empresa": EMPRESA["nombre"],
        "nit": EMPRESA["nit"],
        "ciudad": EMPRESA["ciudad"],
        "norma_codigo": "NTC",
        "norma_nombre": "ISO 9001",
        "norma_version": "2015",
        "codigo_verificacion": "CV-123",
        "cert_estado": "Vigente",
        "cert_emision": date(2026, 1, 1),
        "cert_vence": date(2099, 1, 1),
        "url_certificado": None,
    }
    fila.update(cambios)
    return fila


@pytest.mark.parametrize("vence, estado", [
    (date.today() + timedelta(days=91), "VIGENTE"),
    (date.today() + timedelta(days=90), "POR VENCER"),
    (date.today(), "POR VENCER"),
    (date.today() - timedelta(days=1), "VENCIDO"),
])
async def test_el_estado_de_vigencia_respeta_el_umbral_de_90_dias(db, cliente, vence, estado):
    db.execute.side_effect = [_filas([_fila_documento(cert_vence=vence)])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"nit": EMPRESA["nit"]})

    fila = respuesta.json()[0]
    assert fila["estado_vigencia"] == estado
    assert fila["dias_restantes"] == (vence - date.today()).days


async def test_sin_certificado_no_hay_plazo_que_contar(db, cliente):
    db.execute.side_effect = [_filas([
        _fila_documento(codigo_verificacion=None, cert_vence=None),
    ])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"nit": EMPRESA["nit"]})

    fila = respuesta.json()[0]
    assert fila["estado_vigencia"] == "SIN CERTIFICADO"
    assert fila["dias_restantes"] is None


async def test_las_fechas_como_datetime_no_rompen_la_consulta(db, cliente):
    """
    En la base real `fecha_radicacion` es timestamp, así que asyncpg la entrega
    como `datetime`. Restarla con `date.today()` lanzaba TypeError y el
    endpoint respondía 500; el service debe normalizarla a `date`.
    """
    db.execute.side_effect = [_filas([_fila_documento(
        fecha_radicacion=datetime(2026, 9, 1, 10, 30),
        cert_vence=datetime(2099, 1, 1, 0, 0),
    )])]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/documentos", params={"nit": EMPRESA["nit"]})

    assert respuesta.status_code == status.HTTP_200_OK
    fila = respuesta.json()[0]
    assert fila["estado_vigencia"] == "VIGENTE"
    assert fila["dias_desde_radicacion"] == (date.today() - date(2026, 9, 1)).days


async def test_un_codigo_existente_valida_como_autentico(db, cliente):
    db.execute.side_effect = [_una_fila({
        "codigo_verificacion": "CV-123",
        "cert_estado": "Vigente",
        "cert_emision": date(2026, 1, 1),
        "cert_vence": date(2099, 1, 1),
        "numero_radicado": "RAD-2026-009",
        "estado_tramite": "Aprobada",
        "fecha_radicacion": date(2026, 1, 1),
        "alcance_certificacion": "ISO 9001",
        "empresa": EMPRESA["nombre"],
        "nit": EMPRESA["nit"],
        "ciudad": EMPRESA["ciudad"],
        "norma_codigo": "NTC",
        "norma_nombre": "ISO 9001",
        "norma_version": "2015",
    })]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/validar", params={"codigo": "CV-123"})

    datos = respuesta.json()
    assert datos["autentico"] is True
    assert datos["documento"]["empresa"] == EMPRESA["nombre"]
    assert datos["documento"]["estado_vigencia"] == "VIGENTE"
    assert datos["documento"]["norma_completa"] == "NTC ISO 9001 2015"


async def test_un_codigo_inexistente_no_valida(db, cliente):
    db.execute.side_effect = [_una_fila(None)]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/validar", params={"codigo": "CV-999"})

    datos = respuesta.json()
    assert respuesta.status_code == status.HTTP_200_OK
    assert datos["autentico"] is False
    assert datos["documento"] is None


async def test_la_validacion_compara_exacto_y_no_por_prefijo(db, cliente):
    """
    Un ILIKE aquí dejaría que cualquiera enumere códigos válidos probando
    prefijos ("CV-1", "CV-12"...). La comparación debe ser de igualdad.
    """
    db.execute.side_effect = [_una_fila(None)]

    async with cliente as ac:
        await ac.get(f"{BASE}/validar", params={"codigo": "CV-1"})

    sql = _sql_ejecutados(db)[0]
    assert "ILIKE" not in sql.upper()
    assert "UPPER(TRIM(c.codigo_verificacion)) = UPPER(TRIM(:codigo))" in sql


async def test_validar_sin_codigo_no_toca_la_base_de_datos(db, cliente):
    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/validar")

    assert respuesta.json()["autentico"] is False
    db.execute.assert_not_called()


@pytest.mark.parametrize("pagina, titulo", [
    ("/vigencia", "Consultar vigencia y plazos"),
    ("/validar", "Validar autenticidad"),
    ("/constancia", "Descargar constancia pública"),
])
async def test_las_paginas_nuevas_las_sirve_el_modulo(cliente, pagina, titulo):
    async with cliente as ac:
        respuesta = await ac.get(pagina)

    assert respuesta.status_code == status.HTTP_200_OK
    assert "text/html" in respuesta.headers["content-type"]
    assert titulo in respuesta.text


async def test_las_paginas_nuevas_apuntan_al_api_del_modulo(cliente):
    async with cliente as ac:
        vigencia = (await ac.get("/vigencia")).text
        validar = (await ac.get("/validar")).text
        constancia = (await ac.get("/constancia")).text

    assert f"{BASE}/documentos" in vigencia
    assert f"{BASE}/validar" in validar
    assert f"{BASE}/empresa/" in constancia
    assert f"{BASE}/constancia/" in constancia


