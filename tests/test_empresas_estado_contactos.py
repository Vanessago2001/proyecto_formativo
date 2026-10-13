"""
M3 — EMPRESAS · estado de la empresa (EMP-006 a EMP-008), contactos de sede
(EMP-027 a EMP-029) y roles alineados con la hoja "M3 — EMPRESAS".

Donde la hoja marca REQ para el Auxiliar, la respuesta es 202: la acción
queda pendiente de aprobación y no se ejecuta (ver test_empresas_seguridad_aprobaciones).
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
ID_CONTACTO = str(uuid.uuid4())


def fila(estado: str = "Activa") -> dict:
    """Una fila que sirve de empresa, de sede y de contacto para el doble."""
    return {
        "id_empresa": ID_EMPRESA,
        "nombre": "Cafe del Eje",
        "estado": estado,
        "id_sede": ID_SEDE,
        "nombre_sede": "Planta",
        "ciudad": "Manizales",
        "departamento": "Caldas",
        "pais": "Colombia",
        "id_contacto": ID_CONTACTO,
    }


def sesion(registro: dict | None = None) -> AsyncMock:
    resultado = MagicMock()
    resultado.mappings().all.return_value = [registro] if registro else []
    resultado.mappings().first.return_value = registro
    resultado.scalar.return_value = 0
    db = AsyncMock()
    db.execute.return_value = resultado
    return db


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": str(uuid.uuid4()),
        "role_name": rol,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


def sentencias(db) -> list[tuple[str, dict]]:
    return [
        (" ".join(str(llamada.args[0]).split()), llamada.args[1] if len(llamada.args) > 1 else {})
        for llamada in db.execute.call_args_list
    ]


def estados_guardados(db) -> list[str]:
    return [p["estado"] for sql, p in sentencias(db) if sql.startswith("UPDATE empresa SET estado")]


BASE = f"/api/empresas/{ID_EMPRESA}"
CONTACTOS = f"{BASE}/sedes/{ID_SEDE}/contactos"


# ============================================================
# ESTADO DE LA EMPRESA
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 200), ("Auxiliar", 202), ("Empresa", 403), ("Auditor", 403)],
)
async def test_inactivar_empresa_segun_la_hoja(rol, esperado):
    db = sesion(fila("Activa"))

    respuesta = await pedir(db, rol, "post", f"{BASE}/inactivar")

    assert respuesta.status_code == esperado
    assert estados_guardados(db) == (["Inactiva"] if esperado == 200 else [])


@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 403), ("Auxiliar", 202)],
)
async def test_solo_el_superadministrador_reactiva(rol, esperado):
    db = sesion(fila("Inactiva"))

    respuesta = await pedir(db, rol, "post", f"{BASE}/reactivar")

    assert respuesta.status_code == esperado
    assert estados_guardados(db) == (["Activa"] if esperado == 200 else [])


async def test_no_se_reactiva_una_empresa_que_no_esta_inactiva():
    db = sesion(fila("Activa"))
    assert (await pedir(db, "Super Administrador", "post", f"{BASE}/reactivar")).status_code == 409


async def test_no_se_inactiva_dos_veces():
    db = sesion(fila("Inactiva"))
    assert (await pedir(db, "Administrador", "post", f"{BASE}/inactivar")).status_code == 409


async def test_cambiar_estado_suspende_una_empresa_activa():
    db = sesion(fila("Activa"))

    respuesta = await pedir(db, "Administrador", "patch", f"{BASE}/estado", json={"estado": "Suspendida"})

    assert respuesta.status_code == 200
    assert estados_guardados(db) == ["Suspendida"]


async def test_cambiar_estado_no_saca_a_una_empresa_de_inactiva():
    db = sesion(fila("Inactiva"))

    respuesta = await pedir(db, "Administrador", "patch", f"{BASE}/estado", json={"estado": "Activa"})

    assert respuesta.status_code == 409
    assert estados_guardados(db) == []


async def test_cambiar_estado_no_acepta_inactiva():
    db = sesion(fila("Activa"))
    respuesta = await pedir(db, "Administrador", "patch", f"{BASE}/estado", json={"estado": "Inactiva"})
    assert respuesta.status_code == 422


# ============================================================
# CONTACTOS DE SEDE
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Empresa", 201), ("Auxiliar", 201), ("Administrador", 201), ("Auditor", 403), ("Comité", 403)],
)
async def test_registrar_contacto_segun_la_hoja(rol, esperado):
    db = sesion(fila())

    respuesta = await pedir(db, rol, "post", CONTACTOS, json={"nombre": "Ana Ramírez", "correo": "ana@cafe.co"})

    assert respuesta.status_code == esperado
    insertado = any(sql.startswith("INSERT INTO contacto_sede") for sql, _ in sentencias(db))
    assert insertado is (esperado == 201)


@pytest.mark.parametrize("rol,esperado", [("Empresa", 200), ("Administrador", 200), ("Auxiliar", 202)])
async def test_eliminar_contacto_segun_la_hoja(rol, esperado):
    db = sesion(fila())

    respuesta = await pedir(db, rol, "delete", f"{CONTACTOS}/{ID_CONTACTO}")

    assert respuesta.status_code == esperado
    borrado = any(sql.startswith("DELETE FROM contacto_sede") for sql, _ in sentencias(db))
    assert borrado is (esperado == 200)


@pytest.mark.parametrize("rol", ["Auditor", "Comité", "Empresa"])
async def test_consultar_contactos(rol):
    respuesta = await pedir(sesion(fila()), rol, "get", CONTACTOS)
    assert respuesta.status_code == 200


async def test_el_contacto_valida_el_correo():
    respuesta = await pedir(sesion(fila()), "Empresa", "post", CONTACTOS, json={"nombre": "Ana", "correo": "no-es-correo"})
    assert respuesta.status_code == 422


async def test_editar_contacto_sin_campos_responde_400():
    respuesta = await pedir(sesion(fila()), "Empresa", "put", f"{CONTACTOS}/{ID_CONTACTO}", json={})
    assert respuesta.status_code == 400


async def test_el_contacto_de_una_sede_inexistente_responde_404():
    respuesta = await pedir(sesion(None), "Empresa", "post", CONTACTOS, json={"nombre": "Ana Ramírez"})
    assert respuesta.status_code == 404


# ============================================================
# SEDES Y EMPRESAS
# ============================================================

async def test_la_ubicacion_de_la_sede_no_se_edita():
    db = sesion(fila())

    respuesta = await pedir(db, "Administrador", "put", f"{BASE}/sedes/{ID_SEDE}", json={"ciudad": "Pereira"})

    assert respuesta.status_code == 409
    assert not any(sql.startswith("UPDATE sede_empresa") for sql, _ in sentencias(db))


async def test_la_direccion_de_la_sede_si_se_edita():
    db = sesion(fila())

    respuesta = await pedir(
        db, "Empresa", "put", f"{BASE}/sedes/{ID_SEDE}",
        json={"direccion": "Calle 2 # 3-4", "ciudad": "Manizales"},
    )

    assert respuesta.status_code == 200


async def test_el_auxiliar_solo_solicita_eliminar_sedes():
    db = sesion(fila())
    respuesta = await pedir(db, "Auxiliar", "delete", f"{BASE}/sedes/{ID_SEDE}")
    assert respuesta.status_code == 202
    assert not any(sql.startswith("DELETE") for sql, _ in sentencias(db))


async def test_la_empresa_consulta_solo_sus_empresas():
    db = sesion(fila())

    respuesta = await pedir(db, "Empresa", "get", "/api/empresas/mias")

    assert respuesta.status_code == 200
    [(sql, parametros)] = sentencias(db)
    assert "JOIN user_empresa ue ON ue.id_empresa = e.id_empresa" in sql
    assert "id_usuario" in parametros


@pytest.mark.parametrize("rol,esperado", [("Empresa", 403), ("Comité", 200), ("Auditor", 200)])
async def test_el_listado_de_empresas_sigue_la_hoja(rol, esperado):
    respuesta = await pedir(sesion(fila()), rol, "get", "/api/empresas/")
    assert respuesta.status_code == esperado


async def test_registrar_empresa_como_empresa_la_vincula_a_la_cuenta():
    db = sesion(fila())

    respuesta = await pedir(
        db, "Empresa", "post", "/api/empresas/",
        json={"nombre": "Cafe del Eje", "nit": "900123456-7", "ciudad": "Manizales", "direccion": "Calle 1", "correo": "cafe@eje.co"},
    )

    assert respuesta.status_code == 201
    assert any(sql.startswith("INSERT INTO user_empresa") for sql, _ in sentencias(db))
