"""
M3 — EMPRESAS · documentos de soporte (EMP-011 a EMP-020) y dirección de la
sede (EMP-025 / EMP-026).

Los roles salen de la hoja "M3 — EMPRESAS":

    EMP-011/012  subir y reemplazar   -> SUPERADM, ADM, AUX, EMP
    EMP-014/015  descargar y ver      -> todos menos PUB
    EMP-016/017/018/019  revisión     -> SUPERADM, ADM, AUX (la empresa no)
    EMP-020  historial documental     -> SUPERADM, ADM, AUX, EMP
    EMP-025/026  dirección de sede    -> SUPERADM, ADM, AUX, EMP

Ningún archivo de prueba toca `storage/`: la carpeta de archivos se redirige
a un directorio temporal.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.empresas import documento_empresa_service
from modules.empresas.documento_empresa_service import DocumentoEmpresaService

ID_EMPRESA = str(uuid.uuid4())
ID_DOCUMENTO = str(uuid.uuid4())
ID_SEDE = str(uuid.uuid4())

BASE = f"/api/empresas/{ID_EMPRESA}"
DOCS = f"{BASE}/documentos"

PDF = ("soporte.pdf", b"%PDF-1.4 contenido de prueba", "application/pdf")


@pytest.fixture(autouse=True)
def archivos_en_temporal(tmp_path, monkeypatch):
    """Las pruebas escriben en una carpeta temporal, nunca en storage/."""
    monkeypatch.setattr(documento_empresa_service, "CARPETA_ARCHIVOS", tmp_path / "empresas")


def documento(estado: str = "Pendiente", version: int = 1) -> dict:
    return {
        "id_documento": ID_DOCUMENTO,
        "id_empresa": ID_EMPRESA,
        "tipo_documento": "Cámara de Comercio",
        "numero_documento": "CC-1",
        "nombre_archivo": "soporte.pdf",
        "url_archivo": f"storage/empresas/{ID_EMPRESA}/x.pdf",
        "version": version,
        "estado_validacion": estado,
        "observaciones": None,
        "usuario_subida": str(uuid.uuid4()),
        "usuario_revision": None,
        "fecha_expedicion": None,
        "fecha_vencimiento": None,
        "fecha_subida": None,
        "fecha_revision": None,
    }


def sesion(registro: dict | None = None, filas: list[dict] | None = None) -> AsyncMock:
    resultado = MagicMock()
    resultado.mappings().all.return_value = filas if filas is not None else ([registro] if registro else [])
    resultado.mappings().first.return_value = registro
    resultado.scalar.return_value = 1
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


# ============================================================
# EMP-011 · SUBIR DOCUMENTO
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [
        ("Super Administrador", 201),
        ("Administrador", 201),
        ("Auxiliar", 201),
        ("Empresa", 201),
        ("Auditor", 403),
        ("Comité", 403),
        ("Publico", 403),
    ],
)
async def test_subir_documento_segun_la_hoja(rol, esperado):
    db = sesion(documento())

    respuesta = await pedir(
        db, rol, "post", DOCS,
        files={"archivo": PDF},
        data={"tipo_documento": "Cámara de Comercio"},
    )

    assert respuesta.status_code == esperado


async def test_el_documento_nace_pendiente_y_en_la_version_uno():
    db = sesion(documento())

    await pedir(db, "Empresa", "post", DOCS, files={"archivo": PDF}, data={"tipo_documento": "RUT"})

    sql, parametros = next((s, p) for s, p in sentencias(db) if s.startswith("INSERT INTO documento_empresa"))
    assert parametros["estado"] == "Pendiente"
    assert "version, estado_validacion" in sql
    assert parametros["nombre_archivo"] == "soporte.pdf"


async def test_no_se_admite_un_tipo_de_documento_fuera_del_catalogo():
    """La tabla tiene una restricción; se avisa antes de llegar a ella."""
    db = sesion(documento())

    respuesta = await pedir(
        db, "Empresa", "post", DOCS,
        files={"archivo": PDF},
        data={"tipo_documento": "Lo que sea"},
    )

    assert respuesta.status_code == 400
    assert not any(s.startswith("INSERT INTO documento_empresa") for s, _ in sentencias(db))


# ============================================================
# EMP-016 · VALIDACIÓN AUTOMÁTICA DE FORMATO
# ============================================================

@pytest.mark.parametrize("nombre", ["programa.exe", "hoja.xlsx", "archivo"])
async def test_se_rechazan_los_formatos_no_permitidos(nombre):
    db = sesion(documento())

    respuesta = await pedir(
        db, "Empresa", "post", DOCS,
        files={"archivo": (nombre, b"contenido", "application/octet-stream")},
        data={"tipo_documento": "Otro"},
    )

    assert respuesta.status_code == 415


async def test_no_se_admite_un_archivo_vacio():
    db = sesion(documento())

    respuesta = await pedir(
        db, "Empresa", "post", DOCS,
        files={"archivo": ("vacio.pdf", b"", "application/pdf")},
        data={"tipo_documento": "Otro"},
    )

    assert respuesta.status_code == 400


async def test_la_validacion_manual_la_hace_la_administracion():
    db = sesion(documento())

    assert (await pedir(db, "Auxiliar", "get", f"{DOCS}/{ID_DOCUMENTO}/validar")).status_code == 200
    assert (await pedir(db, "Empresa", "get", f"{DOCS}/{ID_DOCUMENTO}/validar")).status_code == 403


async def test_la_validacion_manual_avisa_si_el_archivo_no_esta():
    db = sesion(documento())

    respuesta = await pedir(db, "Administrador", "get", f"{DOCS}/{ID_DOCUMENTO}/validar")

    cuerpo = respuesta.json()
    assert cuerpo["formato_valido"] is False
    assert "no está disponible" in cuerpo["motivos"][0]


# ============================================================
# EMP-012 · REEMPLAZAR
# ============================================================

async def test_reemplazar_guarda_la_version_anterior():
    db = sesion(documento(version=1))

    await pedir(db, "Empresa", "put", f"{DOCS}/{ID_DOCUMENTO}", files={"archivo": PDF})

    ejecutadas = [s for s, _ in sentencias(db)]
    assert any(s.startswith("INSERT INTO historial_documento_empresa") for s in ejecutadas)
    assert any("version = version + 1" in s for s in ejecutadas)


async def test_reemplazar_devuelve_el_documento_a_revision():
    db = sesion(documento(estado="Correccion"))

    await pedir(db, "Empresa", "put", f"{DOCS}/{ID_DOCUMENTO}", files={"archivo": PDF})

    _, parametros = next((s, p) for s, p in sentencias(db) if "version = version + 1" in s)
    assert parametros["estado"] == "Pendiente"


@pytest.mark.parametrize("estado", ["Aprobado", "Vencido"])
async def test_no_se_reemplaza_un_documento_ya_resuelto(estado):
    db = sesion(documento(estado=estado))

    respuesta = await pedir(db, "Empresa", "put", f"{DOCS}/{ID_DOCUMENTO}", files={"archivo": PDF})

    assert respuesta.status_code == 409


# ============================================================
# EMP-017 / EMP-018 / EMP-019 · REVISIÓN
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [
        ("Super Administrador", 200),
        ("Administrador", 200),
        ("Auxiliar", 200),
        ("Empresa", 403),
        ("Auditor", 403),
        ("Comité", 403),
    ],
)
async def test_la_empresa_no_revisa_sus_propios_documentos(rol, esperado):
    db = sesion(documento())

    respuesta = await pedir(
        db, rol, "post", f"{DOCS}/{ID_DOCUMENTO}/aprobar", json={"observaciones": None}
    )

    assert respuesta.status_code == esperado


@pytest.mark.parametrize(
    "ruta,estado",
    [("aprobar", "Aprobado"), ("rechazar", "Rechazado"), ("correccion", "Correccion")],
)
async def test_cada_decision_deja_su_estado(ruta, estado):
    db = sesion(documento())

    await pedir(
        db, "Administrador", "post", f"{DOCS}/{ID_DOCUMENTO}/{ruta}",
        json={"observaciones": "Motivo suficientemente largo."},
    )

    _, parametros = next((s, p) for s, p in sentencias(db) if s.startswith("UPDATE documento_empresa SET estado_validacion"))
    assert parametros["estado"] == estado
    assert parametros["usuario_revision"]


@pytest.mark.parametrize("ruta", ["rechazar", "correccion"])
async def test_rechazar_y_pedir_correccion_exigen_motivo(ruta):
    db = sesion(documento())

    respuesta = await pedir(db, "Administrador", "post", f"{DOCS}/{ID_DOCUMENTO}/{ruta}", json={})

    assert respuesta.status_code == 422


# ============================================================
# EMP-020 · HISTORIAL DOCUMENTAL
# ============================================================

async def test_el_historial_reune_las_versiones_y_la_vigente():
    db = sesion(documento(), filas=[
        {"id_documento": ID_DOCUMENTO, "version": 2, "situacion": "Vigente"},
        {"id_documento": ID_DOCUMENTO, "version": 1, "situacion": "Reemplazada"},
    ])

    respuesta = await pedir(db, "Empresa", "get", f"{DOCS}/historial")

    assert respuesta.status_code == 200
    assert [f["situacion"] for f in respuesta.json()] == ["Vigente", "Reemplazada"]
    sql = next(s for s, _ in sentencias(db) if "historial_documento_empresa" in s)
    assert "UNION ALL" in sql


@pytest.mark.parametrize("rol,esperado", [("Empresa", 200), ("Auditor", 403), ("Comité", 403)])
async def test_el_historial_no_es_para_auditores_ni_comite(rol, esperado):
    db = sesion(documento(), filas=[])

    assert (await pedir(db, rol, "get", f"{DOCS}/historial")).status_code == esperado


# ============================================================
# EMP-014 · DESCARGAR
# ============================================================

async def test_descargar_avisa_cuando_el_archivo_ya_no_esta():
    db = sesion(documento())

    respuesta = await pedir(db, "Auditor", "get", f"{DOCS}/{ID_DOCUMENTO}/archivo")

    assert respuesta.status_code == 404


async def test_descargar_no_es_para_el_publico():
    db = sesion(documento())

    assert (await pedir(db, "Publico", "get", f"{DOCS}/{ID_DOCUMENTO}/archivo")).status_code == 403


# ============================================================
# EMP-025 / EMP-026 · DIRECCIÓN DE LA SEDE
# ============================================================

async def test_registrar_la_direccion_cuando_la_sede_no_la_tenia():
    db = sesion({"id_sede": ID_SEDE, "id_empresa": ID_EMPRESA, "direccion": ""})

    respuesta = await pedir(
        db, "Empresa", "patch", f"{BASE}/sedes/{ID_SEDE}/direccion",
        json={"direccion": "Calle 10 # 5-20"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["permiso"] == "EMP-025"


async def test_editar_la_direccion_cuando_la_sede_ya_la_tenia():
    db = sesion({"id_sede": ID_SEDE, "id_empresa": ID_EMPRESA, "direccion": "Calle 1"})

    respuesta = await pedir(
        db, "Empresa", "patch", f"{BASE}/sedes/{ID_SEDE}/direccion",
        json={"direccion": "Calle 10 # 5-20"},
    )

    assert respuesta.json()["permiso"] == "EMP-026"


async def test_la_direccion_no_puede_quedar_en_cualquier_cosa():
    db = sesion({"id_sede": ID_SEDE, "id_empresa": ID_EMPRESA, "direccion": "Calle 1"})

    respuesta = await pedir(
        db, "Empresa", "patch", f"{BASE}/sedes/{ID_SEDE}/direccion", json={"direccion": "a"}
    )

    assert respuesta.status_code == 422


# ============================================================
# VALIDACIONES DEL SERVICIO, SIN PASAR POR HTTP
# ============================================================

@pytest.mark.parametrize("tipo", list(documento_empresa_service.TIPOS_DOCUMENTO))
def test_el_catalogo_de_tipos_coincide_con_la_restriccion_de_la_tabla(tipo):
    assert DocumentoEmpresaService.validar_tipo(tipo) == tipo
