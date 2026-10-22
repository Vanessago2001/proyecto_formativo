"""
Tests del módulo de reportes (M12).

Lo que se protege aquí no es que los reportes existan, sino quién puede
ejecutarlos y hasta dónde llegan sus filas:

1. Matriz rol × reporte: cada rol solo ejecuta los suyos (403 para el resto).
2. Sin sesión no hay reportes (401).
3. El alcance de los datos: una cuenta de empresa consulta con su `id_empresa`
   inyectado en el SQL, y un auditor con su `id_usuario`. Si esos filtros se
   pierden, un rol vería filas que no le corresponden aunque el menú se las
   oculte.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.reportes import reportes_roles as roles_m12

BASE = "/api/reportes"

CODIGOS = list(roles_m12.CATALOGO_REPORTES)
ROLES = ["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite", "public"]

ID_USUARIO = "22222222-2222-2222-2222-222222222222"
ID_EMPRESA = "33333333-3333-3333-3333-333333333333"


def _filas(filas):
    resultado = MagicMock()
    resultado.mappings().all.return_value = filas
    resultado.mappings().first.return_value = filas[0] if filas else None
    return resultado


@pytest.fixture(autouse=True)
def _sin_overrides_previos():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    sesion = AsyncMock()
    app.dependency_overrides[get_db] = lambda: sesion
    return sesion


@pytest.fixture
def cliente():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sesion(rol: str):
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": ID_USUARIO,
        "nombre": f"Usuario {rol}",
        "role_name": rol,
    }


def _sql_y_params(db):
    return [
        (str(llamada.args[0]), llamada.args[1] if len(llamada.args) > 1 else {})
        for llamada in db.execute.call_args_list
    ]


# ============================================================
# 1. MATRIZ ROL × REPORTE
# ============================================================

@pytest.mark.parametrize("rol", ROLES)
@pytest.mark.parametrize("codigo", CODIGOS)
async def test_solo_los_roles_autorizados_ejecutan_cada_reporte(db, cliente, codigo, rol):
    _sesion(rol)
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/{codigo}")

    autorizado = rol in roles_m12.roles_del_reporte(codigo)
    esperado = status.HTTP_200_OK if autorizado else status.HTTP_403_FORBIDDEN
    assert respuesta.status_code == esperado, f"{rol} × {codigo}"


async def test_un_reporte_inexistente_da_404(db, cliente):
    _sesion("superadmin")

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/reporte-de-lo-que-no-hay")

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND


async def test_sin_sesion_no_hay_reportes(cliente):
    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/{CODIGOS[0]}")

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================
# 2. CATÁLOGO SEGÚN EL ROL
# ============================================================

@pytest.mark.parametrize("rol", ROLES)
async def test_el_catalogo_solo_ofrece_lo_que_el_rol_puede(db, cliente, rol):
    _sesion(rol)

    async with cliente as ac:
        respuesta = await ac.get(BASE)

    visibles = {item["codigo"] for item in respuesta.json()}
    esperados = {
        codigo for codigo in CODIGOS
        if rol in roles_m12.roles_del_reporte(codigo)
    }
    assert visibles == esperados


async def test_el_catalogo_de_un_rol_de_control_incluye_conflictos(db, cliente):
    _sesion("comite")

    async with cliente as ac:
        respuesta = await ac.get(BASE)

    assert "preventivo-conflictos" in {item["codigo"] for item in respuesta.json()}


# ============================================================
# 3. ALCANCE DE LOS DATOS POR ROL
# ============================================================

async def test_una_cuenta_de_empresa_consulta_con_su_id_empresa(db, cliente):
    _sesion("empresa")
    db.execute.side_effect = [
        _filas([{"id_empresa": ID_EMPRESA}]),   # user_empresa
        _filas([]),                             # el reporte
    ]

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/certificados-vigentes")

    assert respuesta.status_code == status.HTTP_200_OK
    sql, params = _sql_y_params(db)[1]
    assert "e.id_empresa = :eid" in sql
    assert params["eid"] == ID_EMPRESA


async def test_una_empresa_sin_empresa_asociada_no_ve_nada(db, cliente):
    _sesion("empresa")
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/certificados-vigentes")

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["total"] == 0
    # Solo la consulta de user_empresa: sin empresa no se consulta el reporte.
    assert db.execute.call_count == 1


async def test_un_auditor_consulta_con_su_id_usuario(db, cliente):
    _sesion("auditor")
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/operativo-auditores")

    assert respuesta.status_code == status.HTTP_200_OK
    sql, params = _sql_y_params(db)[0]
    assert "u.id_usuario = :yo" in sql
    assert params["yo"] == ID_USUARIO


async def test_un_rol_de_direccion_no_lleva_filtro_de_filas(db, cliente):
    _sesion("admin")
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/certificados-vigentes")

    assert respuesta.status_code == status.HTTP_200_OK
    sql, params = _sql_y_params(db)[0]
    assert ":eid" not in params
    assert ":yo" not in params
    assert "e.id_empresa = :eid" not in sql


async def test_un_auditor_solo_ve_sus_apelaciones(db, cliente):
    _sesion("auditor")
    db.execute.return_value = _filas([])

    async with cliente as ac:
        respuesta = await ac.get(f"{BASE}/apelaciones-fallos")

    assert respuesta.status_code == status.HTTP_200_OK
    sql, params = _sql_y_params(db)[0]
    assert "ap.id_usuario_presenta = :yo" in sql
    assert params["yo"] == ID_USUARIO


async def test_el_reporte_critico_usa_el_umbral_de_90_dias(db, cliente):
    _sesion("admin")
    db.execute.return_value = _filas([])

    async with cliente as ac:
        await ac.get(f"{BASE}/critico-vencimiento")

    _, params = _sql_y_params(db)[0]
    assert params["dias"] == roles_m12.DIAS_VENCIMIENTO_CRITICO == 90


# ============================================================
# 5. INTERFAZ DEL MÓDULO
# ============================================================

# Páginas del panel que deben ofrecer una entrada al módulo de reportes.
PAGINAS_CON_ENLACE = [
    "/dashboard",
    "/asignacion-auditores",
    "/banco-auditores",
    "/banco-auditores/solicitud/44444444-4444-4444-4444-444444444444",
    "/empresas",
    "/revision-solicitudes",
    "/empresa",
    "/comite",
    "/auditor",
]


async def test_la_pagina_de_reportes_existe(cliente):
    async with cliente as ac:
        respuesta = await ac.get("/reportes")

    assert respuesta.status_code == status.HTTP_200_OK
    assert "text/html" in respuesta.headers["content-type"]
    assert "Módulo de reportes" in respuesta.text


async def test_la_pagina_consume_las_dos_rutas_de_la_api(cliente):
    """El catálogo y las filas los decide el servidor, no el HTML."""
    async with cliente as ac:
        html = (await ac.get("/reportes")).text

    assert 'api("/api/reportes")' in html
    assert '"/api/reportes/" + encodeURIComponent(codigo)' in html


async def test_la_pagina_exige_sesion_y_lleva_al_login(cliente):
    async with cliente as ac:
        html = (await ac.get("/reportes")).text

    assert 'localStorage.getItem("access_token")' in html
    assert 'window.location.href = "/login"' in html


async def test_la_pagina_envia_el_token_en_cada_peticion(cliente):
    async with cliente as ac:
        html = (await ac.get("/reportes")).text

    assert 'Authorization: "Bearer " + token' in html


@pytest.mark.parametrize("pagina", PAGINAS_CON_ENLACE)
async def test_el_panel_enlaza_al_modulo_de_reportes(cliente, pagina):
    async with cliente as ac:
        html = (await ac.get(pagina)).text

    assert 'href="/reportes"' in html, f"{pagina} no enlaza al módulo de reportes"


async def test_la_ruta_de_la_pagina_esta_registrada(cliente):
    assert "/reportes" in set(app.openapi()["paths"])
