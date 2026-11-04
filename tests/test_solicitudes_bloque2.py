"""
M5 — GESTIÓN DE SOLICITUDES · Tests del Bloque 2 (SOL-011 a SOL-020).

Cubre tres frentes:
  1. Que cada endpoint conceda o niegue el acceso según la matriz del Excel.
  2. Que registrar y editar respeten su orden (409 indicando el permiso a usar).
  3. Que solo se modifique un borrador propio y que la consulta general
     reúna toda la información.

La conformidad de las filas con permisos.xlsx la comprueba
`test_la_matriz_del_codigo_coincide_con_el_excel` en los tests del Bloque 1.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.solicitudes.informacion_router import router as informacion_router
from modules.solicitudes.solicitud_permissions import (
    PERMISOS_M5,
    ROLES_DEL_SISTEMA,
    tiene_permiso,
)
from tests.fake_db import SesionFalsa

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_OTRO_USUARIO = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_EMPRESA = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ID_OTRA_EMPRESA = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ID_NORMA = uuid.UUID("55555555-5555-5555-5555-555555555555")
ID_OTRA_NORMA = uuid.UUID("66666666-6666-6666-6666-666666666666")


# ============================================================
# INFRAESTRUCTURA DE PRUEBA
# ============================================================

@pytest.fixture
def sesion() -> SesionFalsa:
    s = SesionFalsa()
    s.vincular(ID_USUARIO, ID_EMPRESA)
    s.vincular(ID_OTRO_USUARIO, ID_OTRA_EMPRESA)
    s.sembrar_norma(id_norma=ID_NORMA, codigo="ISO-9001")
    s.sembrar_norma(id_norma=ID_OTRA_NORMA, codigo="ISO-14001")
    return s


@pytest.fixture
def app(sesion) -> FastAPI:
    aplicacion = FastAPI()
    aplicacion.include_router(informacion_router)

    async def _db():
        yield sesion

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def autenticar(app: FastAPI, rol: str, id_usuario: uuid.UUID = ID_USUARIO) -> None:
    async def _usuario():
        return {
            "id_usuario": id_usuario,
            "nombre": f"tester_{rol}",
            "correo": f"{rol.lower()}@example.com",
            "estado": "Activo",
            "rol_id": 1,
            "role_name": rol,
        }

    app.dependency_overrides[get_current_user] = _usuario


@pytest.fixture
def cliente(app) -> TestClient:
    return TestClient(app)


def ruta(solicitud: dict, sufijo: str) -> str:
    return f"/solicitudes/{solicitud['id_solicitud']}/{sufijo}"


# ============================================================
# 1. LOS ENDPOINTS RESPETAN LA MATRIZ
# ============================================================

def test_la_matriz_incluye_todo_el_bloque_dos():
    for n in range(11, 21):
        assert f"SOL-{n:03d}" in PERMISOS_M5


# (código, método, ruta, kwargs de la petición). {d} es un alcance o proceso.
ENDPOINTS = [
    ("SOL-011", "post",  "/solicitudes/{s}/norma", {"json": {"id_norma": str(ID_NORMA)}}),
    ("SOL-012", "patch", "/solicitudes/{s}/norma", {"json": {"id_norma": str(ID_OTRA_NORMA)}}),
    ("SOL-013", "post",  "/solicitudes/{s}/alcances", {"json": {"descripcion": "Tostion de cafe"}}),
    ("SOL-014", "patch", "/solicitudes/{s}/alcances/{d}", {"json": {"estado": "Inactivo"}}),
    ("SOL-015", "post",  "/solicitudes/{s}/procesos", {"json": {"nombre": "Compras"}}),
    ("SOL-016", "patch", "/solicitudes/{s}/procesos/{d}", {"json": {"nombre": "Ventas"}}),
    ("SOL-017", "post",  "/solicitudes/{s}/numero-empleados", {"json": {"numero_empleados": 30}}),
    ("SOL-018", "patch", "/solicitudes/{s}/numero-empleados", {"json": {"numero_empleados": 31}}),
    ("SOL-019", "post",  "/solicitudes/{s}/numero-sedes", {"json": {"numero_sedes": 2}}),
    ("SOL-020", "get",   "/solicitudes/{s}/informacion-general", {}),
]


@pytest.mark.parametrize("codigo,metodo,plantilla,extra", ENDPOINTS)
@pytest.mark.parametrize("rol", list(ROLES_DEL_SISTEMA))
def test_el_endpoint_de_informacion_aplica_la_matriz(
    app, cliente, sesion, codigo, metodo, plantilla, extra, rol
):
    """Si la matriz dice F, la respuesta debe ser 403; si dice V, nunca 403."""
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    autenticar(app, rol)

    url = plantilla.format(s=solicitud["id_solicitud"], d=uuid.uuid4())
    respuesta = getattr(cliente, metodo)(url, **extra)

    if tiene_permiso(codigo, rol):
        assert respuesta.status_code != 403, (
            f"{codigo} ({metodo.upper()} {url}): el rol {rol} tiene el permiso "
            f"pero recibió 403 — {respuesta.text[:200]}"
        )
    else:
        assert respuesta.status_code == 403, (
            f"{codigo} ({metodo.upper()} {url}): el rol {rol} NO tiene el "
            f"permiso pero recibió {respuesta.status_code}."
        )
        assert codigo in respuesta.json()["detail"]


# ============================================================
# 2. REGISTRAR Y EDITAR
# ============================================================

def test_la_norma_se_registra_solo_si_no_hay_una(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=None)

    registrada = cliente.post(ruta(solicitud, "norma"), json={"id_norma": str(ID_NORMA)})
    assert registrada.status_code == 200
    assert registrada.json()["id_norma"] == str(ID_NORMA)

    repetida = cliente.post(ruta(solicitud, "norma"), json={"id_norma": str(ID_OTRA_NORMA)})
    assert repetida.status_code == 409
    assert "SOL-012" in repetida.json()["detail"]


def test_editar_la_norma_exige_que_haya_una_registrada(app, cliente, sesion):
    autenticar(app, "Empresa")
    sin_norma = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=None)

    respuesta = cliente.patch(ruta(sin_norma, "norma"), json={"id_norma": str(ID_NORMA)})

    assert respuesta.status_code == 409
    assert "SOL-011" in respuesta.json()["detail"]


def test_editar_la_norma_la_cambia(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=ID_NORMA)

    respuesta = cliente.patch(ruta(solicitud, "norma"), json={"id_norma": str(ID_OTRA_NORMA)})

    assert respuesta.status_code == 200
    assert respuesta.json()["id_norma"] == str(ID_OTRA_NORMA)


def test_no_se_registra_una_norma_que_no_existe(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=None)

    respuesta = cliente.post(ruta(solicitud, "norma"), json={"id_norma": str(uuid.uuid4())})

    assert respuesta.status_code == 404
    assert sesion.solicitudes[str(solicitud["id_solicitud"])]["id_norma"] is None


def test_el_alcance_se_registra_y_se_desactiva_sin_borrarse(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    creado = cliente.post(
        ruta(solicitud, "alcances"),
        json={"descripcion": "  Tostion y empaque de cafe  "},
    )
    assert creado.status_code == 201
    assert creado.json()["estado"] == "Activo"
    assert creado.json()["descripcion"] == "Tostion y empaque de cafe"

    id_alcance = creado.json()["id_alcance"]
    desactivado = cliente.patch(
        ruta(solicitud, f"alcances/{id_alcance}"), json={"estado": "Inactivo"}
    )
    assert desactivado.status_code == 200
    assert desactivado.json()["estado"] == "Inactivo"
    assert id_alcance in sesion.alcances


def test_editar_alcance_sin_campos_o_ajeno(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    id_alcance = cliente.post(
        ruta(solicitud, "alcances"), json={"descripcion": "Alcance inicial"}
    ).json()["id_alcance"]

    vacio = cliente.patch(ruta(solicitud, f"alcances/{id_alcance}"), json={})
    assert vacio.status_code == 400

    # El mismo alcance pedido a través de otra solicitud no existe.
    otra = sesion.sembrar(id_empresa=ID_EMPRESA)
    ajeno = cliente.patch(ruta(otra, f"alcances/{id_alcance}"), json={"estado": "Inactivo"})
    assert ajeno.status_code == 404


def test_los_procesos_activos_no_repiten_nombre(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    compras = cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Compras"})
    assert compras.status_code == 201

    repetido = cliente.post(ruta(solicitud, "procesos"), json={"nombre": "compras"})
    assert repetido.status_code == 409

    ventas = cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Ventas"})
    renombrar = cliente.patch(
        ruta(solicitud, f"procesos/{ventas.json()['id_proceso']}"),
        json={"nombre": "Compras"},
    )
    assert renombrar.status_code == 409

    # Desactivado deja de contar, y el nombre vuelve a estar libre.
    cliente.patch(
        ruta(solicitud, f"procesos/{compras.json()['id_proceso']}"),
        json={"estado": "Inactivo"},
    )
    de_nuevo = cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Compras"})
    assert de_nuevo.status_code == 201


def test_un_proceso_puede_editar_su_descripcion_sin_chocar_consigo_mismo(
    app, cliente, sesion
):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    proceso = cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Produccion"}).json()

    respuesta = cliente.patch(
        ruta(solicitud, f"procesos/{proceso['id_proceso']}"),
        json={"nombre": "Produccion", "descripcion": "Tostion en planta"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["descripcion"] == "Tostion en planta"


def test_numero_de_empleados_registrar_y_editar(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, numero_empleados=None)
    url = ruta(solicitud, "numero-empleados")

    sin_registro = cliente.patch(url, json={"numero_empleados": 40})
    assert sin_registro.status_code == 409
    assert "SOL-017" in sin_registro.json()["detail"]

    assert cliente.post(url, json={"numero_empleados": 40}).status_code == 200

    otra_vez = cliente.post(url, json={"numero_empleados": 41})
    assert otra_vez.status_code == 409
    assert "SOL-018" in otra_vez.json()["detail"]

    editado = cliente.patch(url, json={"numero_empleados": 45})
    assert editado.status_code == 200
    assert editado.json()["numero_empleados"] == 45


def test_el_numero_de_empleados_debe_ser_positivo(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, numero_empleados=None)

    respuesta = cliente.post(ruta(solicitud, "numero-empleados"), json={"numero_empleados": 0})

    assert respuesta.status_code == 422


def test_numero_de_sedes_ya_registrado_remite_a_editar_el_borrador(app, cliente, sesion):
    autenticar(app, "Empresa")
    con_sedes = sesion.sembrar(id_empresa=ID_EMPRESA, numero_sedes=2)
    sin_sedes = sesion.sembrar(id_empresa=ID_EMPRESA, numero_sedes=None)

    repetido = cliente.post(ruta(con_sedes, "numero-sedes"), json={"numero_sedes": 3})
    assert repetido.status_code == 409
    assert "SOL-003" in repetido.json()["detail"]

    registrado = cliente.post(ruta(sin_sedes, "numero-sedes"), json={"numero_sedes": 3})
    assert registrado.status_code == 200
    assert registrado.json()["numero_sedes"] == 3


# ============================================================
# 3. REGLAS DE ACCESO Y CONSULTA GENERAL
# ============================================================

@pytest.mark.parametrize(
    "metodo,sufijo,cuerpo",
    [
        ("post", "norma", {"id_norma": str(ID_NORMA)}),
        ("post", "alcances", {"descripcion": "Alcance tardio"}),
        ("post", "procesos", {"nombre": "Compras"}),
        ("post", "numero-empleados", {"numero_empleados": 5}),
    ],
)
def test_no_se_modifica_una_solicitud_radicada(app, cliente, sesion, metodo, sufijo, cuerpo):
    autenticar(app, "Empresa")
    radicada = sesion.sembrar(
        id_empresa=ID_EMPRESA, estado="Radicada", id_norma=None, numero_empleados=None
    )

    respuesta = getattr(cliente, metodo)(ruta(radicada, sufijo), json=cuerpo)

    assert respuesta.status_code == 409
    assert "Borrador" in respuesta.json()["detail"]


def test_un_estado_antiguo_de_la_base_no_rompe_la_edicion(app, cliente, sesion):
    """En la base hay filas con estados como 'APROBADO': deben dar 409, no 500."""
    autenticar(app, "Empresa")
    antigua = sesion.sembrar(id_empresa=ID_EMPRESA, estado="APROBADO")

    respuesta = cliente.post(ruta(antigua, "alcances"), json={"descripcion": "Intento"})

    assert respuesta.status_code == 409


def test_la_empresa_no_modifica_ni_consulta_solicitudes_ajenas(app, cliente, sesion):
    ajena = sesion.sembrar(id_empresa=ID_OTRA_EMPRESA, id_norma=None)
    autenticar(app, "Empresa", id_usuario=ID_USUARIO)

    assert cliente.post(ruta(ajena, "norma"), json={"id_norma": str(ID_NORMA)}).status_code == 404
    assert cliente.get(ruta(ajena, "informacion-general")).status_code == 404


def test_la_informacion_general_reune_todo_y_senala_lo_pendiente(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=None, numero_empleados=None)
    cliente.post(ruta(solicitud, "alcances"), json={"descripcion": "Tostion de cafe"})
    cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Compras"})

    sede = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    retirada = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    sesion.incluir_sede(solicitud["id_solicitud"], sede["id_sede"])
    sesion.incluir_sede(solicitud["id_solicitud"], retirada["id_sede"], estado="Excluida")

    # Un auditor también la consulta (SOL-020 es V para AUD).
    autenticar(app, "Auditor", id_usuario=uuid.uuid4())
    respuesta = cliente.get(ruta(solicitud, "informacion-general"))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["alcances"]) == 1
    assert [p["nombre"] for p in cuerpo["procesos"]] == ["Compras"]
    assert cuerpo["sedes_incluidas"] == 1
    assert cuerpo["campos_pendientes"] == ["id_norma", "numero_empleados"]


def test_cada_cambio_queda_en_el_historial_con_su_permiso(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=None)

    cliente.post(ruta(solicitud, "norma"), json={"id_norma": str(ID_NORMA)})
    cliente.post(ruta(solicitud, "alcances"), json={"descripcion": "Tostion de cafe"})
    cliente.post(ruta(solicitud, "procesos"), json={"nombre": "Compras"})

    observaciones = [h["observacion"] for h in sesion.historial]
    assert observaciones[0].startswith("[SOL-011]")
    assert "ISO-9001" in observaciones[0]
    assert observaciones[1].startswith("[SOL-013]")
    assert observaciones[2].startswith("[SOL-015]")
