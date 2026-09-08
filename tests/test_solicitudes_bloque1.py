"""
M5 — GESTIÓN DE SOLICITUDES · Tests del Bloque 1 (SOL-001 a SOL-010).

Cubre tres frentes:
  1. Que la matriz codificada coincida con la hoja del Excel (fuente de verdad).
  2. Que cada endpoint conceda o niegue el acceso según esa matriz.
  3. Que el ciclo de vida de la solicitud respete las reglas de negocio.
"""

import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.solicitudes.solicitud_permissions import (
    COLUMNAS_MATRIZ,
    PERMISOS_M5,
    ROL_ADM,
    ROLES_DEL_SISTEMA,
    NivelPermiso,
    normalizar_rol,
    nivel_permiso,
    tiene_permiso,
)
from modules.solicitudes.solicitud_router import router as solicitud_router
from tests.fake_db import SesionFalsa

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "documentacion" / "permisos.xlsx"
HOJA_M5 = "M5 — GESTIÓN DE SOLICITUDES"

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_OTRO_USUARIO = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_EMPRESA = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ID_OTRA_EMPRESA = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


# ============================================================
# INFRAESTRUCTURA DE PRUEBA
# ============================================================

@pytest.fixture
def sesion() -> SesionFalsa:
    """Sesión simulada con los vínculos usuario-empresa ya establecidos."""
    s = SesionFalsa()
    s.vincular(ID_USUARIO, ID_EMPRESA)
    s.vincular(ID_OTRO_USUARIO, ID_OTRA_EMPRESA)
    return s


@pytest.fixture
def app(sesion) -> FastAPI:
    """App mínima con solo el router de M5 y la base de datos simulada."""
    aplicacion = FastAPI()
    aplicacion.include_router(solicitud_router)

    async def _db():
        yield sesion

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def autenticar(app: FastAPI, rol: str, id_usuario: uuid.UUID = ID_USUARIO) -> None:
    """Sustituye al usuario autenticado por uno con el rol indicado."""

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


CUERPO_VALIDO = {
    "alcance_certificacion": "Diseño y producción de café tostado",
    "numero_empleados": 45,
    "numero_sedes": 2,
    "persona_contacto": "Ana Ramírez",
}


# ============================================================
# 1. LA MATRIZ DEL CÓDIGO COINCIDE CON EL EXCEL
# ============================================================

def _leer_hoja_excel(ruta: Path, nombre_hoja: str) -> list[list[str]]:
    """Lee una hoja del .xlsx con la librería estándar (sin openpyxl)."""
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }

    with zipfile.ZipFile(ruta) as z:
        cadenas: list[str] = []
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in raiz.findall("m:si", ns):
            cadenas.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))

        relaciones = {
            rel.get("Id"): rel.get("Target").lstrip("/")
            for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        }

        libro = ET.fromstring(z.read("xl/workbook.xml"))
        destino = None
        for hoja in libro.find("m:sheets", ns):
            if hoja.get("name") == nombre_hoja:
                destino = relaciones[hoja.get(f"{{{ns['r']}}}id")]
                break

        assert destino, f"No se encontró la hoja '{nombre_hoja}' en {ruta.name}"
        if not destino.startswith("xl/"):
            destino = f"xl/{destino}"

        def indice_columna(referencia: str) -> int:
            letras = re.match(r"([A-Z]+)", referencia).group(1)
            numero = 0
            for letra in letras:
                numero = numero * 26 + ord(letra) - 64
            return numero

        filas: list[list[str]] = []
        hoja_xml = ET.fromstring(z.read(destino))
        for fila in hoja_xml.iter(f"{{{ns['m']}}}row"):
            celdas: dict[int, str] = {}
            for celda in fila.findall("m:c", ns):
                valor = celda.find("m:v", ns)
                if valor is None:
                    continue
                texto = (
                    cadenas[int(valor.text)]
                    if celda.get("t") == "s"
                    else valor.text
                )
                celdas[indice_columna(celda.get("r"))] = (texto or "").strip()

            if celdas:
                filas.append([celdas.get(i, "") for i in range(1, max(celdas) + 1)])

        return filas


@pytest.mark.skipif(not RUTA_EXCEL.exists(), reason="permisos.xlsx no disponible")
def test_la_matriz_del_codigo_coincide_con_el_excel():
    """
    La hoja de cálculo es la fuente de verdad: si el equipo cambia un permiso
    allí y no lo refleja en el código, este test debe fallar.
    """
    filas = _leer_hoja_excel(RUTA_EXCEL, HOJA_M5)

    # Columna 2 = código, columna 3 = permiso, columnas 4..11 = los ocho roles.
    esperado = {
        fila[1]: (fila[2], tuple(fila[3:11]))
        for fila in filas
        if len(fila) >= 11 and fila[1] in PERMISOS_M5
    }

    assert set(esperado) == set(PERMISOS_M5), (
        "Los códigos del Bloque 1 en el código no coinciden con los del Excel."
    )

    for codigo, (descripcion_excel, valores_excel) in esperado.items():
        descripcion_codigo, valores_codigo = PERMISOS_M5[codigo]

        assert descripcion_codigo == descripcion_excel, (
            f"{codigo}: la descripción difiere del Excel."
        )
        assert tuple(v.value for v in valores_codigo) == valores_excel, (
            f"{codigo}: la fila de permisos difiere del Excel.\n"
            f"  Excel:  {valores_excel}\n"
            f"  Código: {tuple(v.value for v in valores_codigo)}"
        )


def test_la_matriz_cubre_los_bloques_implementados():
    """Bloque 1 (SOL-001..010) y Bloque 4 (SOL-031..040)."""
    esperados = [f"SOL-{n:03d}" for n in range(1, 11)]
    esperados += [f"SOL-{n:03d}" for n in range(31, 41)]
    assert sorted(PERMISOS_M5) == sorted(esperados)


def test_cada_fila_tiene_un_valor_por_rol():
    for codigo, (_, valores) in PERMISOS_M5.items():
        assert len(valores) == len(COLUMNAS_MATRIZ), (
            f"{codigo} no tiene un valor por cada uno de los ocho roles."
        )


def test_el_rol_publico_no_accede_a_ningun_permiso_del_bloque():
    for codigo in PERMISOS_M5:
        assert not tiene_permiso(codigo, "Publico"), (
            f"{codigo}: el rol Publico no debería tener acceso."
        )


def test_un_rol_desconocido_siempre_queda_denegado():
    for codigo in PERMISOS_M5:
        assert nivel_permiso(codigo, "RolInventado") is NivelPermiso.DENEGADO
        assert nivel_permiso(codigo, None) is NivelPermiso.DENEGADO


def test_los_alias_de_rol_se_normalizan():
    # El equipo escribe el rol de varias formas; todas deben resolver igual.
    for alias in ("Administrador", "administrador", "ADMIN", "  admin  "):
        assert tiene_permiso("SOL-006", alias), f"El alias '{alias}' falló."

    for alias in ("Comite", "comité", "COMITÉ"):
        assert tiene_permiso("SOL-006", alias), f"El alias '{alias}' falló."

    # El aprobador no es un rol aparte: resuelve al administrador.
    for alias in ("Aprobador", "aprobador", "APR"):
        assert normalizar_rol(alias) == ROL_ADM, (
            f"'{alias}' debería resolver al rol Administrador."
        )


# ============================================================
# 2. LOS ENDPOINTS RESPETAN LA MATRIZ
# ============================================================

# (código, método, ruta, cuerpo) de cada endpoint del bloque.
ENDPOINTS = [
    ("SOL-001", "post", "/solicitudes/", CUERPO_VALIDO),
    ("SOL-002", "post", "/solicitudes/borradores", CUERPO_VALIDO),
    ("SOL-003", "patch", "/solicitudes/{id}", {"alcance_certificacion": "Nuevo"}),
    ("SOL-004", "delete", "/solicitudes/{id}", None),
    ("SOL-005", "post", "/solicitudes/{id}/radicar", None),
    ("SOL-006", "get", "/solicitudes/{id}", None),
    ("SOL-007", "get", "/solicitudes/{id}/pdf", None),
    ("SOL-008", "post", "/solicitudes/{id}/duplicar", None),
    ("SOL-009", "post", "/solicitudes/{id}/cancelar", {"motivo": "Ya no aplica"}),
    ("SOL-010", "get", "/solicitudes/{id}/estado", None),
]

TODOS_LOS_ROLES = list(ROLES_DEL_SISTEMA)


@pytest.mark.parametrize("codigo,metodo,plantilla,cuerpo", ENDPOINTS)
@pytest.mark.parametrize("rol", TODOS_LOS_ROLES)
def test_el_endpoint_aplica_la_matriz_de_permisos(
    app, cliente, sesion, codigo, metodo, plantilla, cuerpo, rol
):
    """
    Para cada combinación endpoint × rol: si la matriz dice F, la respuesta
    debe ser 403; si dice V, nunca puede ser 403.
    """
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    autenticar(app, rol, id_usuario=ID_USUARIO)

    ruta = plantilla.format(id=solicitud["id_solicitud"])
    respuesta = getattr(cliente, metodo)(
        ruta,
        **({"json": cuerpo} if cuerpo is not None else {}),
    )

    permitido = tiene_permiso(codigo, rol)

    if permitido:
        assert respuesta.status_code != 403, (
            f"{codigo} ({metodo.upper()} {ruta}): el rol {rol} tiene el permiso "
            f"en la matriz pero recibió 403 — {respuesta.text[:200]}"
        )
    else:
        assert respuesta.status_code == 403, (
            f"{codigo} ({metodo.upper()} {ruta}): el rol {rol} NO tiene el "
            f"permiso pero recibió {respuesta.status_code}."
        )
        assert codigo in respuesta.json()["detail"]


def test_sin_token_la_api_responde_401(sesion):
    """Sin sobrescribir get_current_user, la dependencia real exige el token."""
    aplicacion = FastAPI()
    aplicacion.include_router(solicitud_router)

    async def _db():
        yield sesion

    aplicacion.dependency_overrides[get_db] = _db

    respuesta = TestClient(aplicacion).get("/solicitudes/")
    assert respuesta.status_code == 401


# ============================================================
# 3. REGLAS DEL CICLO DE VIDA
# ============================================================

def test_la_solicitud_nace_en_borrador_y_sin_radicado(app, cliente):
    autenticar(app, "Empresa")

    respuesta = cliente.post("/solicitudes/", json=CUERPO_VALIDO)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "Borrador"
    assert cuerpo["numero_radicado"] is None


def test_radicar_asigna_consecutivo_y_congela_la_edicion(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    id_solicitud = solicitud["id_solicitud"]

    radicada = cliente.post(f"/solicitudes/{id_solicitud}/radicar")
    assert radicada.status_code == 200
    assert radicada.json()["estado"] == "Radicada"
    assert re.fullmatch(r"SOL-\d{4}-\d{6}", radicada.json()["numero_radicado"])

    # Ya radicada, SOL-003 debe rechazar la edición.
    edicion = cliente.patch(
        f"/solicitudes/{id_solicitud}",
        json={"alcance_certificacion": "Intento de cambio"},
    )
    assert edicion.status_code == 409


def test_el_radicado_es_consecutivo(app, cliente, sesion):
    autenticar(app, "Empresa")

    radicados = []
    for _ in range(3):
        solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
        respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")
        radicados.append(respuesta.json()["numero_radicado"])

    consecutivos = [int(r.split("-")[-1]) for r in radicados]
    assert consecutivos == sorted(consecutivos)
    assert len(set(radicados)) == 3, "Los radicados deben ser únicos."


def test_no_se_radica_sin_los_campos_obligatorios(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, alcance_certificacion=None, numero_sedes=None)

    respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")

    assert respuesta.status_code == 422
    assert "alcance_certificacion" in respuesta.json()["detail"]
    assert "numero_sedes" in respuesta.json()["detail"]


def test_eliminar_borrador_es_logico_y_no_fisico(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)
    id_solicitud = str(solicitud["id_solicitud"])

    assert cliente.delete(f"/solicitudes/{id_solicitud}").status_code == 200

    # La fila sigue en la tabla, marcada como eliminada.
    assert sesion.solicitudes[id_solicitud]["deleted_at"] is not None
    # Pero deja de ser visible para la API.
    assert cliente.get(f"/solicitudes/{id_solicitud}").status_code == 404


def test_no_se_elimina_una_solicitud_ya_radicada(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")

    respuesta = cliente.delete(f"/solicitudes/{solicitud['id_solicitud']}")

    assert respuesta.status_code == 409
    assert "SOL-009" in respuesta.json()["detail"]


def test_cancelar_exige_motivo(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA)

    respuesta = cliente.post(
        f"/solicitudes/{solicitud['id_solicitud']}/cancelar",
        json={"motivo": "no"},
    )

    assert respuesta.status_code == 422  # el motivo exige mínimo 5 caracteres


def test_no_se_cancela_una_solicitud_en_revision(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado="En revision")

    respuesta = cliente.post(
        f"/solicitudes/{solicitud['id_solicitud']}/cancelar",
        json={"motivo": "Cambio de planes de la empresa"},
    )

    assert respuesta.status_code == 409


def test_duplicar_crea_un_borrador_nuevo_sin_radicado(app, cliente, sesion):
    autenticar(app, "Empresa")
    original = sesion.sembrar(
        id_empresa=ID_EMPRESA,
        estado="Radicada",
        numero_radicado="SOL-2026-000009",
    )

    respuesta = cliente.post(f"/solicitudes/{original['id_solicitud']}/duplicar")

    assert respuesta.status_code == 201
    copia = respuesta.json()
    assert copia["estado"] == "Borrador"
    assert copia["numero_radicado"] is None
    assert copia["id_solicitud"] != str(original["id_solicitud"])
    assert copia["alcance_certificacion"] == original["alcance_certificacion"]


def test_la_empresa_no_ve_solicitudes_de_otra_empresa(app, cliente, sesion):
    ajena = sesion.sembrar(id_empresa=ID_OTRA_EMPRESA, estado="Radicada")
    autenticar(app, "Empresa", id_usuario=ID_USUARIO)

    # Se responde 404 (no 403) para no revelar que la solicitud existe.
    assert cliente.get(f"/solicitudes/{ajena['id_solicitud']}").status_code == 404
    assert cliente.get("/solicitudes/").json() == []


def test_la_administracion_si_ve_las_solicitudes_de_todas_las_empresas(
    app, cliente, sesion
):
    sesion.sembrar(id_empresa=ID_OTRA_EMPRESA, estado="Radicada")
    sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")

    for rol in ("Administrador", "Auxiliar", "Auditor", "Comite", "Aprobador"):
        autenticar(app, rol, id_usuario=uuid.uuid4())
        listado = cliente.get("/solicitudes/")
        assert listado.status_code == 200
        assert len(listado.json()) == 2, f"El rol {rol} debería ver ambas."


def test_la_empresa_no_puede_modificar_una_solicitud_ajena(app, cliente, sesion):
    ajena = sesion.sembrar(id_empresa=ID_OTRA_EMPRESA)
    autenticar(app, "Empresa", id_usuario=ID_USUARIO)

    respuesta = cliente.patch(
        f"/solicitudes/{ajena['id_solicitud']}",
        json={"alcance_certificacion": "Intento de intrusión"},
    )

    assert respuesta.status_code == 404


def test_cada_accion_queda_en_el_historial_de_estados(app, cliente, sesion):
    """Cada operación del ciclo de vida deja una fila en historial_estado."""
    autenticar(app, "Empresa")

    creada = cliente.post(
        "/solicitudes/",
        json={**CUERPO_VALIDO, "id_norma": str(uuid.uuid4())},
    ).json()
    id_solicitud = creada["id_solicitud"]
    cliente.patch(f"/solicitudes/{id_solicitud}", json={"numero_sedes": 3})
    cliente.post(f"/solicitudes/{id_solicitud}/radicar")

    assert [h["estado"] for h in sesion.historial] == [
        "Borrador",
        "Borrador",
        "Radicada",
    ]

    # La observación conserva el código de permiso que originó cada cambio.
    observaciones = [h["observacion"] for h in sesion.historial]
    assert observaciones[0].startswith("[SOL-001]")
    assert observaciones[1].startswith("[SOL-003]")
    assert observaciones[2].startswith("[SOL-005]")


def test_el_pdf_generado_es_un_archivo_valido(app, cliente, sesion):
    autenticar(app, "Empresa")
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, numero_radicado="SOL-2026-000001")

    respuesta = cliente.get(f"/solicitudes/{solicitud['id_solicitud']}/pdf")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/pdf"
    assert "SOL-2026-000001.pdf" in respuesta.headers["content-disposition"]
    assert respuesta.content.startswith(b"%PDF-1.4")
    assert respuesta.content.rstrip().endswith(b"%%EOF")


def test_el_listado_filtra_por_estado(app, cliente, sesion):
    sesion.sembrar(id_empresa=ID_EMPRESA, estado="Borrador")
    sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")
    sesion.sembrar(id_empresa=ID_EMPRESA, estado="Radicada")
    autenticar(app, "Empresa")

    radicadas = cliente.get("/solicitudes/", params={"estado": "Radicada"})

    assert radicadas.status_code == 200
    assert len(radicadas.json()) == 2
    assert all(s["estado"] == "Radicada" for s in radicadas.json())


# ============================================================
# 4. EL PDF ES LEGIBLE (SOL-007)
# ============================================================

def _texto_del_pdf(pdf: bytes) -> str:
    """Extrae las cadenas visibles del flujo de contenido del PDF."""
    flujo = re.search(rb"stream\n(.*?)\nendstream", pdf, re.S).group(1)
    literales = re.findall(r"\((.*?)\) Tj", flujo.decode("latin-1"))
    return "\n".join(l.replace("\\(", "(").replace("\\)", ")") for l in literales)


def test_el_pdf_muestra_nombres_y_no_identificadores_internos():
    """
    El PDF sale de la aplicación y puede acabar en manos de terceros, así que
    debe mostrar el nombre y el NIT de la empresa y el código de la norma,
    nunca los UUID de la base de datos.
    """
    from modules.solicitudes.solicitud_pdf import generar_pdf_solicitud

    id_solicitud = uuid.uuid4()
    id_empresa = uuid.uuid4()
    id_norma = uuid.uuid4()

    texto = _texto_del_pdf(generar_pdf_solicitud({
        "id_solicitud": id_solicitud,
        "id_empresa": id_empresa,
        "id_norma": id_norma,
        "numero_radicado": "SOL-2026-000007",
        "estado": "Radicada",
        "empresa_nombre": "Cafe del Eje S.A.S.",
        "empresa_nit": "900123456-7",
        "norma_codigo": "ISO-9001",
        "norma_nombre": "Sistemas de gestion de la calidad",
        "norma_version": "2015",
        "alcance_certificacion": "Tostion y comercializacion de cafe",
        "numero_empleados": 45,
        "numero_sedes": 2,
        "persona_contacto": "Ana Ramirez",
        "observaciones": None,
        "fecha_creacion": None,
        "fecha_radicacion": None,
        "fecha_cancelacion": None,
        "motivo_cancelacion": None,
    }))

    assert "Cafe del Eje S.A.S." in texto
    assert "900123456-7" in texto
    assert "ISO-9001" in texto
    assert "Sistemas de gestion de la calidad" in texto
    assert "SOL-2026-000007" in texto

    for identificador in (id_solicitud, id_empresa, id_norma):
        assert str(identificador) not in texto, (
            f"El PDF expone el identificador interno {identificador}."
        )


def test_el_pdf_traduce_la_puntuacion_que_latin1_no_cubre():
    """Un guion largo copiado desde Word no puede acabar como '?'."""
    from modules.solicitudes.solicitud_pdf import generar_pdf_solicitud

    texto = _texto_del_pdf(generar_pdf_solicitud({
        "id_solicitud": uuid.uuid4(),
        "numero_radicado": "SOL-2026-000008",
        "estado": "Radicada",
        "empresa_nombre": "Empresa de prueba",
        "empresa_nit": "111",
        "norma_codigo": "ISO-9001",
        "norma_nombre": "Calidad — Requisitos",   # raya
        "norma_version": "2015",
        "alcance_certificacion": "Comillas “tipograficas” y puntos…",
        "numero_empleados": 1,
        "numero_sedes": 1,
        "persona_contacto": None,
        "observaciones": None,
        "fecha_creacion": None,
        "fecha_radicacion": None,
        "fecha_cancelacion": None,
        "motivo_cancelacion": None,
    }))

    assert "Calidad - Requisitos" in texto
    assert '"tipograficas"' in texto
    assert "puntos..." in texto
    assert "?" not in texto


def test_el_pdf_no_falla_si_faltan_empresa_o_norma():
    """Un borrador recien creado puede no tener norma todavia."""
    from modules.solicitudes.solicitud_pdf import generar_pdf_solicitud

    pdf = generar_pdf_solicitud({
        "id_solicitud": uuid.uuid4(),
        "numero_radicado": None,
        "estado": "Borrador",
        "alcance_certificacion": None,
        "numero_empleados": None,
        "numero_sedes": None,
        "persona_contacto": None,
        "observaciones": None,
        "fecha_creacion": None,
        "fecha_radicacion": None,
        "fecha_cancelacion": None,
        "motivo_cancelacion": None,
    })

    assert pdf.startswith(b"%PDF-1.4")
    texto = _texto_del_pdf(pdf)
    assert "No registrada" in texto
    assert "Sin radicar (borrador)" in texto
