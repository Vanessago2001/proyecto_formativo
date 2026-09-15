"""
Módulo de empresas contra el esquema real de la base.

  · empresa.id_empresa y sede_empresa.id_sede son UUID: las rutas deben
    aceptarlos (antes exigían enteros y respondían 422).
  · Las sedes viven en `sede_empresa`, con estados 'Activa' / 'Inactiva'.
  · Una sede incluida en solicitudes no se borra.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app

ID_EMPRESA = str(uuid.uuid4())
ID_SEDE = str(uuid.uuid4())
ADMIN = {"id_usuario": "1", "role_name": "Administrador"}


@pytest.fixture
def sesion():
    resultado = MagicMock()
    resultado.mappings().all.return_value = []
    resultado.mappings().first.return_value = {
        "id_empresa": ID_EMPRESA,
        "id_sede": ID_SEDE,
        "nombre": "Cafe del Eje",
        "nombre_sede": "Planta",
    }
    resultado.scalar.return_value = 0

    db = AsyncMock()
    db.execute.return_value = resultado
    return db


async def pedir(sesion, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: sesion
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


def sentencias(sesion) -> list[tuple[str, dict]]:
    return [
        (" ".join(str(llamada.args[0]).split()), llamada.args[1] if len(llamada.args) > 1 else {})
        for llamada in sesion.execute.call_args_list
    ]


@pytest.mark.parametrize(
    "sufijo",
    ["", "/solicitudes", "/sedes", "/documentos", f"/sedes/{ID_SEDE}"],
)
async def test_las_rutas_de_empresa_aceptan_uuid(sesion, sufijo):
    respuesta = await pedir(sesion, "get", f"/api/empresas/{ID_EMPRESA}{sufijo}")

    assert respuesta.status_code == 200, respuesta.text


async def test_crear_empresa_genera_su_uuid(sesion):
    respuesta = await pedir(
        sesion,
        "post",
        "/api/empresas/",
        json={
            "nombre": "Cafe del Eje",
            "nit": "900123456-7",
            "ciudad": "Manizales",
            "direccion": "Calle 1",
            "correo": "cafe@eje.co",
        },
    )

    assert respuesta.status_code == 201
    [(sql, _)] = sentencias(sesion)
    assert "INSERT INTO empresa (id_empresa," in sql
    assert "gen_random_uuid()" in sql


async def test_los_documentos_se_filtran_por_la_columna_real(sesion):
    await pedir(sesion, "get", f"/api/empresas/{ID_EMPRESA}/documentos")

    [(sql, _)] = sentencias(sesion)
    assert "FROM documento_empresa WHERE id_empresa = :id_empresa" in sql


async def test_la_sede_se_guarda_en_sede_empresa_con_estado_valido(sesion):
    respuesta = await pedir(
        sesion,
        "post",
        f"/api/empresas/{ID_EMPRESA}/sedes",
        json={
            "nombre_sede": "Bodega",
            "direccion": "Carrera 23 # 64-10",
            "ciudad": "Manizales",
            "estado": "Inactivo",
        },
    )

    assert respuesta.status_code == 201
    insercion = [(sql, p) for sql, p in sentencias(sesion) if sql.startswith("INSERT")]
    [(sql, parametros)] = insercion
    assert "INSERT INTO sede_empresa" in sql
    assert parametros["estado"] == "Inactiva"
    assert parametros["pais"] == "Colombia"


async def test_no_se_borra_una_sede_incluida_en_solicitudes(sesion):
    sesion.execute.return_value.scalar.return_value = 2

    respuesta = await pedir(sesion, "delete", f"/api/empresas/{ID_EMPRESA}/sedes/{ID_SEDE}")

    assert respuesta.status_code == 409
    assert not any(sql.startswith("DELETE") for sql, _ in sentencias(sesion))


async def test_una_sede_sin_uso_si_se_borra(sesion):
    respuesta = await pedir(sesion, "delete", f"/api/empresas/{ID_EMPRESA}/sedes/{ID_SEDE}")

    assert respuesta.status_code == 200
    assert any(sql.startswith("DELETE FROM sede_empresa") for sql, _ in sentencias(sesion))
