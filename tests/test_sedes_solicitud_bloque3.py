"""
M5 — GESTIÓN DE SOLICITUDES · Tests del Bloque 3 (SOL-021 a SOL-030).

Cubre:
  1. Que cada endpoint conceda o niegue el acceso según la matriz del Excel.
  2. Incluir, registrar, editar, quitar e inactivar sedes sin romper
     expedientes ya radicados. Ciudad, departamento y país solo al crear.
  3. La validación de Administración y la exportación a Excel.

No confundir con `test_sedes.py`, que prueba las sedes del módulo de empresas.
"""

import io
import uuid
import zipfile
import xml.etree.ElementTree as ET

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.solicitudes.sede_excel import TIPO_XLSX, generar_excel_sedes
from modules.solicitudes.sede_router import router as sede_router
from modules.solicitudes.solicitud_permissions import (
    PERMISOS_M5,
    ROLES_DEL_SISTEMA,
    exigir_permisos,
    tiene_permiso,
)
from tests.fake_db import SesionFalsa

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_OTRO_USUARIO = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_EMPRESA = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ID_OTRA_EMPRESA = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

SEDE_NUEVA = {
    "nombre_sede": "Planta Chinchiná",
    "direccion": "Km 2 vía Manizales",
    "ciudad": "Chinchiná",
    "departamento": "Caldas",
}

NS_HOJA = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


# ============================================================
# INFRAESTRUCTURA DE PRUEBA
# ============================================================

@pytest.fixture
def sesion() -> SesionFalsa:
    s = SesionFalsa()
    s.vincular(ID_USUARIO, ID_EMPRESA)
    s.vincular(ID_OTRO_USUARIO, ID_OTRA_EMPRESA)
    return s


@pytest.fixture
def app(sesion) -> FastAPI:
    aplicacion = FastAPI()
    aplicacion.include_router(sede_router)

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


def ruta(solicitud: dict, sufijo: str = "") -> str:
    return f"/solicitudes/{solicitud['id_solicitud']}/sedes{sufijo}"


def sede_incluida(sesion: SesionFalsa, solicitud: dict, **campos) -> dict:
    sede = sesion.sembrar_sede(id_empresa=solicitud["id_empresa"], **campos)
    sesion.incluir_sede(solicitud["id_solicitud"], sede["id_sede"])
    return sede


def textos_de_la_hoja(contenido: bytes) -> list[str]:
    """Todas las cadenas escritas en la hoja del .xlsx, en orden."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
        # Cada parte debe ser XML bien formado, o Excel no abre el archivo.
        for nombre in libro.namelist():
            ET.fromstring(libro.read(nombre))
        hoja = ET.fromstring(libro.read("xl/worksheets/sheet1.xml"))
    return [t.text or "" for t in hoja.iter(f"{{{NS_HOJA['m']}}}t")]


# ============================================================
# 1. LOS ENDPOINTS RESPETAN LA MATRIZ
# ============================================================

def test_la_matriz_incluye_todo_el_bloque_tres():
    for n in range(21, 31):
        assert f"SOL-{n:03d}" in PERMISOS_M5


# (código, método, sufijo de la ruta, cuerpo). {d} es la sede incluida.
ENDPOINTS = [
    ("SOL-021", "get",    "/disponibles", None),
    ("SOL-021", "post",   "", {"id_sede": "{d}"}),
    ("SOL-022", "patch",  "/{d}", {"nombre_sede": "Planta 2"}),
    ("SOL-023", "delete", "/{d}", None),
    ("SOL-023", "post",   "/{d}/inactivar", None),
    ("SOL-024", "post",   "/nueva", SEDE_NUEVA),
    ("SOL-025", "patch",  "/{d}/direccion", {"direccion": "Calle 10 # 5-20"}),
    ("SOL-028", "get",    "", None),
    ("SOL-029", "post",   "/validar", None),
    ("SOL-030", "get",    "/excel", None),
]


@pytest.mark.parametrize("codigo,metodo,sufijo,cuerpo", ENDPOINTS)
@pytest.mark.parametrize("rol", list(ROLES_DEL_SISTEMA))
def test_el_endpoint_de_sedes_aplica_la_matriz(
    app, cliente, sesion, codigo, metodo, sufijo, cuerpo, rol
):
    """Si la matriz dice F, la respuesta debe ser 403; si dice V, nunca 403."""
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sede_incluida(sesion, solicitud)
    autenticar(app, rol)

    url = ruta(solicitud, sufijo.format(d=sede["id_sede"]))
    extra = {}
    if cuerpo is not None:
        extra["json"] = {
            clave: (valor.format(d=sede["id_sede"]) if isinstance(valor, str) else valor)
            for clave, valor in cuerpo.items()
        }
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


def test_exigir_permisos_corta_con_el_codigo_que_falta():
    with pytest.raises(HTTPException) as error:
        exigir_permisos({"role_name": "Auditor"}, "SOL-026")

    assert error.value.status_code == 403
    assert "SOL-026" in error.value.detail

    # A la empresa no le falta ninguno: no debe lanzar.
    exigir_permisos({"role_name": "Empresa"}, "SOL-021", "SOL-026", "SOL-027")


def test_registrar_una_sede_verifica_incluir_ciudad_y_departamento(
    app, cliente, sesion, monkeypatch
):
    import modules.solicitudes.sede_service as sede_service

    verificados = []
    monkeypatch.setattr(
        sede_service,
        "exigir_permisos",
        lambda usuario, *codigos: verificados.append(codigos),
    )
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    assert cliente.post(ruta(solicitud, "/nueva"), json=SEDE_NUEVA).status_code == 201
    assert verificados == [("SOL-021", "SOL-026", "SOL-027")]


# ============================================================
# 2. INCLUIR, REGISTRAR, EDITAR, QUITAR E INACTIVAR
# ============================================================

def test_registrar_una_sede_nueva_la_crea_en_la_empresa_y_la_incluye(
    app, cliente, sesion
):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    respuesta = cliente.post(ruta(solicitud, "/nueva"), json=SEDE_NUEVA)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado_en_solicitud"] == "Incluida"
    assert cuerpo["estado_sede"] == "Activa"
    assert cuerpo["pais"] == "Colombia"

    [sede] = sesion.sedes_empresa.values()
    assert sede["id_empresa"] == ID_EMPRESA
    assert sede["departamento"] == "Caldas"


@pytest.mark.parametrize("faltante", ["direccion", "ciudad", "departamento"])
def test_la_sede_nueva_exige_direccion_ciudad_y_departamento(
    app, cliente, sesion, faltante
):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    cuerpo = {k: v for k, v in SEDE_NUEVA.items() if k != faltante}

    assert cliente.post(ruta(solicitud, "/nueva"), json=cuerpo).status_code == 422
    assert sesion.sedes_empresa == {}


def test_incluir_una_sede_existente_y_no_duplicarla(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sesion.sembrar_sede(id_empresa=ID_EMPRESA)

    primera = cliente.post(ruta(solicitud), json={"id_sede": str(sede["id_sede"])})
    segunda = cliente.post(ruta(solicitud), json={"id_sede": str(sede["id_sede"])})

    assert primera.status_code == 201
    assert segunda.status_code == 409


def test_incluir_exige_el_id_de_la_sede(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    assert cliente.post(ruta(solicitud), json=SEDE_NUEVA).status_code == 422


def test_no_se_incluye_una_sede_de_otra_empresa(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    ajena = sesion.sembrar_sede(id_empresa=ID_OTRA_EMPRESA)

    respuesta = cliente.post(ruta(solicitud), json={"id_sede": str(ajena["id_sede"])})

    assert respuesta.status_code == 404
    assert sesion.solicitud_sedes == {}


def test_no_se_incluye_una_sede_inactiva(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    inactiva = sesion.sembrar_sede(id_empresa=ID_EMPRESA, estado="Inactiva")

    respuesta = cliente.post(ruta(solicitud), json={"id_sede": str(inactiva["id_sede"])})

    assert respuesta.status_code == 409


def test_las_sedes_disponibles_son_las_activas_de_la_empresa_sin_incluir(
    app, cliente, sesion
):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede_incluida(sesion, solicitud, nombre_sede="Ya incluida")
    sesion.sembrar_sede(id_empresa=ID_EMPRESA, nombre_sede="Libre")
    sesion.sembrar_sede(id_empresa=ID_EMPRESA, nombre_sede="Inactiva", estado="Inactiva")
    sesion.sembrar_sede(id_empresa=ID_OTRA_EMPRESA, nombre_sede="De otra empresa")

    respuesta = cliente.get(ruta(solicitud, "/disponibles"))

    assert respuesta.status_code == 200
    assert [s["nombre_sede"] for s in respuesta.json()] == ["Libre"]


def test_quitar_una_sede_no_la_borra_y_se_puede_volver_a_incluir(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sede_incluida(sesion, solicitud)

    assert cliente.delete(ruta(solicitud, f"/{sede['id_sede']}")).status_code == 200
    assert cliente.get(ruta(solicitud)).json() == []

    # El vínculo sigue en la tabla y la sede sigue activa en la empresa.
    [vinculo] = sesion.solicitud_sedes.values()
    assert vinculo["estado"] == "Excluida"
    assert sesion.sedes_empresa[str(sede["id_sede"])]["estado"] == "Activa"

    otra_vez = cliente.post(ruta(solicitud), json={"id_sede": str(sede["id_sede"])})
    assert otra_vez.status_code == 201
    assert len(sesion.solicitud_sedes) == 1, "Debe reactivarse el mismo vínculo."


def test_inactivar_quita_la_sede_y_ya_no_se_puede_usar(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sede_incluida(sesion, solicitud)

    respuesta = cliente.post(ruta(solicitud, f"/{sede['id_sede']}/inactivar"))

    assert respuesta.status_code == 200
    assert sesion.sedes_empresa[str(sede["id_sede"])]["estado"] == "Inactiva"
    assert cliente.get(ruta(solicitud)).json() == []
    assert cliente.post(
        ruta(solicitud), json={"id_sede": str(sede["id_sede"])}
    ).status_code == 409


def test_no_se_inactiva_una_sede_de_un_expediente_radicado(app, cliente, sesion):
    autenticar(app, "Empresa")
    borrador = sesion.sembrar(id_empresa=ID_EMPRESA)
    radicada = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")
    sede = sede_incluida(sesion, borrador)
    sesion.incluir_sede(radicada["id_solicitud"], sede["id_sede"])

    respuesta = cliente.post(ruta(borrador, f"/{sede['id_sede']}/inactivar"))

    assert respuesta.status_code == 409
    assert sesion.sedes_empresa[str(sede["id_sede"])]["estado"] == "Activa"


def test_se_editan_nombre_principal_y_direccion(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sede_incluida(sesion, solicitud)
    base = ruta(solicitud, f"/{sede['id_sede']}")

    assert cliente.patch(base, json={"nombre_sede": "Bodega", "es_principal": True}).status_code == 200
    final = cliente.patch(base + "/direccion", json={"direccion": "Carrera 23 # 64-10"})

    assert final.status_code == 200
    cuerpo = final.json()
    assert cuerpo["nombre_sede"] == "Bodega"
    assert cuerpo["es_principal"] is True
    assert cuerpo["direccion"] == "Carrera 23 # 64-10"


def test_ciudad_departamento_y_pais_no_se_editan(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    sede = sede_incluida(sesion, solicitud)
    base = ruta(solicitud, f"/{sede['id_sede']}")

    respuesta = cliente.patch(
        base, json={"ciudad": "Pereira", "departamento": "Risaralda", "pais": "Peru"}
    )

    assert respuesta.status_code == 400
    assert "inactive la sede" in respuesta.json()["detail"]
    guardada = sesion.sedes_empresa[str(sede["id_sede"])]
    assert (guardada["ciudad"], guardada["departamento"], guardada["pais"]) == (
        "Manizales", "Caldas", "Colombia",
    )

    # Tampoco existen rutas propias para cambiarlos.
    assert cliente.put(base + "/ciudad", json={"ciudad": "Pereira"}).status_code in (404, 405)
    assert cliente.put(base + "/departamento", json={"departamento": "X"}).status_code in (404, 405)


def test_no_se_edita_la_direccion_de_una_sede_de_un_expediente_radicado(
    app, cliente, sesion
):
    autenticar(app, "Empresa")
    borrador = sesion.sembrar(id_empresa=ID_EMPRESA)
    radicada = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")
    sede = sede_incluida(sesion, borrador)
    sesion.incluir_sede(radicada["id_solicitud"], sede["id_sede"])

    respuesta = cliente.patch(
        ruta(borrador, f"/{sede['id_sede']}/direccion"),
        json={"direccion": "Otra direccion 123"},
    )

    assert respuesta.status_code == 409
    assert sesion.sedes_empresa[str(sede["id_sede"])]["direccion"] == "Calle 1 # 2-3"


def test_si_la_otra_solicitud_fue_cancelada_la_sede_si_se_edita(app, cliente, sesion):
    autenticar(app, "Empresa")
    borrador = sesion.sembrar(id_empresa=ID_EMPRESA)
    cancelada = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Cancelada")
    sede = sede_incluida(sesion, borrador)
    sesion.incluir_sede(cancelada["id_solicitud"], sede["id_sede"])

    respuesta = cliente.patch(
        ruta(borrador, f"/{sede['id_sede']}/direccion"),
        json={"direccion": "Avenida Santander 50"},
    )

    assert respuesta.status_code == 200


def test_no_se_agregan_sedes_a_una_solicitud_radicada(app, cliente, sesion):
    autenticar(app, "Empresa")
    radicada = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")

    assert cliente.post(ruta(radicada, "/nueva"), json=SEDE_NUEVA).status_code == 409


def test_la_empresa_no_ve_ni_toca_sedes_de_solicitudes_ajenas(app, cliente, sesion):
    ajena = sesion.sembrar(id_empresa=ID_OTRA_EMPRESA)
    autenticar(app, "Empresa", id_usuario=ID_USUARIO)

    assert cliente.get(ruta(ajena)).status_code == 404
    assert cliente.get(ruta(ajena, "/disponibles")).status_code == 404
    assert cliente.post(ruta(ajena, "/nueva"), json=SEDE_NUEVA).status_code == 404
    assert cliente.get(ruta(ajena, "/excel")).status_code == 404


# ============================================================
# 3. VALIDACIÓN Y EXPORTACIÓN
# ============================================================

def test_solo_se_validan_sedes_de_solicitudes_radicadas(app, cliente, sesion):
    autenticar(app, "Administrador", id_usuario=uuid.uuid4())

    for estado in ("Borrador", "Cancelada"):
        solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estado)
        assert cliente.post(ruta(solicitud, "/validar")).status_code == 409


def test_validar_marca_cada_sede_y_detecta_datos_incompletos(app, cliente, sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada", numero_sedes=2)
    sede_incluida(sesion, solicitud, nombre_sede="Principal", es_principal=True)
    # Sede antigua registrada fuera de M5, sin departamento.
    sede_incluida(sesion, solicitud, nombre_sede="Bodega", departamento=None)
    autenticar(app, "Administrador", id_usuario=uuid.uuid4())

    respuesta = cliente.post(ruta(solicitud, "/validar"))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["valida"] is False
    assert cuerpo["sedes_incluidas"] == 2
    assert cuerpo["inconsistencias"] == ["La sede 'Bodega' no tiene: departamento."]

    estados = {s["nombre_sede"]: s["estado_en_solicitud"] for s in cuerpo["sedes"]}
    assert estados == {"Principal": "Validada", "Bodega": "Con observaciones"}


def test_validar_detecta_una_sede_inactiva(app, cliente, sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada", numero_sedes=1)
    sede_incluida(sesion, solicitud, nombre_sede="Cerrada", es_principal=True, estado="Inactiva")
    autenticar(app, "Administrador", id_usuario=uuid.uuid4())

    cuerpo = cliente.post(ruta(solicitud, "/validar")).json()

    assert cuerpo["inconsistencias"] == ["La sede 'Cerrada' está inactiva en la empresa."]
    assert cuerpo["sedes"][0]["estado_en_solicitud"] == "Con observaciones"


def test_validar_sin_observaciones(app, cliente, sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada", numero_sedes=1)
    sede_incluida(sesion, solicitud, es_principal=True)
    autenticar(app, "Auxiliar", id_usuario=uuid.uuid4())

    cuerpo = cliente.post(ruta(solicitud, "/validar")).json()

    assert cuerpo["valida"] is True
    assert cuerpo["inconsistencias"] == []
    assert sesion.historial[-1]["observacion"].startswith("[SOL-029]")


def test_validar_detecta_numero_declarado_distinto_y_falta_de_principal(
    app, cliente, sesion
):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada", numero_sedes=3)
    sede_incluida(sesion, solicitud, es_principal=False)
    autenticar(app, "Administrador", id_usuario=uuid.uuid4())

    inconsistencias = cliente.post(ruta(solicitud, "/validar")).json()["inconsistencias"]

    assert "Se declararon 3 sedes y se incluyeron 1." in inconsistencias
    assert "Debe haber exactamente una sede principal y hay 0." in inconsistencias


def test_validar_una_solicitud_sin_sedes(app, cliente, sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")
    autenticar(app, "Administrador", id_usuario=uuid.uuid4())

    cuerpo = cliente.post(ruta(solicitud, "/validar")).json()

    assert cuerpo["valida"] is False
    assert cuerpo["inconsistencias"] == ["La solicitud no tiene sedes incluidas."]


def test_exportar_sedes_genera_un_excel_valido(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, numero_radicado="SOL-2026-000012")
    cliente.post(ruta(solicitud, "/nueva"), json={**SEDE_NUEVA, "es_principal": True})

    respuesta = cliente.get(ruta(solicitud, "/excel"))

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == TIPO_XLSX
    assert "sedes-SOL-2026-000012.xlsx" in respuesta.headers["content-disposition"]

    textos = textos_de_la_hoja(respuesta.content)
    assert "Sedes de la solicitud SOL-2026-000012" in textos
    assert "Dirección" in textos
    assert "Planta Chinchiná" in textos
    assert "Sí" in textos


def test_el_excel_escapa_el_contenido_y_no_expone_identificadores():
    id_solicitud = uuid.uuid4()
    id_sede = uuid.uuid4()

    contenido = generar_excel_sedes(
        {"id_solicitud": id_solicitud, "numero_radicado": None, "empresa_nombre": "Cafe & Cia <S.A.S.>"},
        [
            {
                "id_sede": id_sede,
                "nombre_sede": '=HYPERLINK("http://malo")',
                "direccion": "Calle \x07 1",
                "ciudad": "Manizales",
                "departamento": None,
                "pais": "Colombia",
                "es_principal": False,
                "estado_en_solicitud": "Incluida",
                "fecha_inclusion": None,
            }
        ],
    )

    textos = textos_de_la_hoja(contenido)
    assert "Empresa: Cafe & Cia <S.A.S.>" in textos
    assert "Sedes de la solicitud sin radicar (borrador)" in textos
    # La "fórmula" se guarda como texto, y el carácter de control se descarta.
    assert '=HYPERLINK("http://malo")' in textos
    assert "Calle  1" in textos

    with zipfile.ZipFile(io.BytesIO(contenido)) as libro:
        hoja = libro.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<f>" not in hoja
    assert str(id_solicitud) not in hoja
    assert str(id_sede) not in hoja
