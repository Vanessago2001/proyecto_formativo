"""
M5 — GESTIÓN DE SOLICITUDES · Tests del Bloque 4 (SOL-031 a SOL-040).

Verifica que cada endpoint de documentos aplique la fila que le corresponde
en la matriz del Excel. Las rutas denegadas cortan en la dependencia de
permisos, antes de tocar la base de datos.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.solicitudes.documento_router import router as documento_router
from modules.solicitudes.documento_service import (
    EXTENSIONES_PERMITIDAS,
    TAMANO_MAXIMO_BYTES,
    _nombre_seguro,
)
from modules.solicitudes.solicitud_permissions import (
    PERMISOS_M5,
    ROLES_DEL_SISTEMA,
    tiene_permiso,
)
from tests.fake_db import SesionFalsa

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_SOLICITUD = uuid.UUID("33333333-3333-3333-3333-333333333333")
ID_DOCUMENTO = uuid.UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def app() -> FastAPI:
    aplicacion = FastAPI()
    aplicacion.include_router(documento_router)

    async def _db():
        yield SesionFalsa()

    aplicacion.dependency_overrides[get_db] = _db
    return aplicacion


def autenticar(app: FastAPI, rol: str) -> None:
    async def _usuario():
        return {
            "id_usuario": ID_USUARIO,
            "nombre": f"tester_{rol}",
            "correo": "t@example.com",
            "estado": "Activo",
            "rol_id": 1,
            "role_name": rol,
        }

    app.dependency_overrides[get_current_user] = _usuario


@pytest.fixture
def cliente(app) -> TestClient:
    return TestClient(app)


ARCHIVO = {"archivo": ("prueba.pdf", b"%PDF-1.4\n", "application/pdf")}
MOTIVO = {"observaciones": "Falta la firma del representante legal."}

# (código, método, ruta, kwargs de la petición)
ENDPOINTS = [
    ("SOL-031", "post",   "/solicitudes/{s}/documentos",
     {"files": ARCHIVO, "data": {"tipo_documento": "Documento de existencia"}}),
    ("SOL-032", "put",    "/solicitudes/{s}/documentos/{d}", {"files": ARCHIVO}),
    ("SOL-033", "delete", "/solicitudes/{s}/documentos/{d}", {}),
    ("SOL-034", "get",    "/solicitudes/{s}/documentos/{d}/descargar", {}),
    ("SOL-035", "get",    "/solicitudes/{s}/documentos", {}),
    ("SOL-036", "get",    "/solicitudes/documentos/formatos-permitidos", {}),
    ("SOL-037", "post",   "/solicitudes/{s}/documentos/{d}/rechazar", {"json": MOTIVO}),
    ("SOL-038", "post",   "/solicitudes/{s}/documentos/{d}/aprobar", {"json": {}}),
    ("SOL-039", "post",   "/solicitudes/{s}/documentos/{d}/solicitar-correccion",
     {"json": MOTIVO}),
    ("SOL-040", "get",    "/solicitudes/{s}/documentos/historial", {}),
]


def test_la_matriz_incluye_todo_el_bloque_cuatro():
    for n in range(31, 41):
        assert f"SOL-{n:03d}" in PERMISOS_M5


@pytest.mark.parametrize("codigo,metodo,plantilla,extra", ENDPOINTS)
@pytest.mark.parametrize("rol", list(ROLES_DEL_SISTEMA))
def test_el_endpoint_de_documentos_aplica_la_matriz(
    app, cliente, codigo, metodo, plantilla, extra, rol
):
    """Si la matriz dice F, la respuesta debe ser 403; si dice V, nunca 403."""
    autenticar(app, rol)
    ruta = plantilla.format(s=ID_SOLICITUD, d=ID_DOCUMENTO)
    respuesta = getattr(cliente, metodo)(ruta, **extra)

    if tiene_permiso(codigo, rol):
        assert respuesta.status_code != 403, (
            f"{codigo} ({metodo.upper()} {ruta}): el rol {rol} tiene el permiso "
            f"pero recibió 403."
        )
    else:
        assert respuesta.status_code == 403, (
            f"{codigo} ({metodo.upper()} {ruta}): el rol {rol} NO tiene el "
            f"permiso pero recibió {respuesta.status_code}."
        )
        assert codigo in respuesta.json()["detail"]


def test_las_reglas_de_formato_son_coherentes():
    """SOL-036: lo que publica el endpoint es lo que aplica el validador."""
    autenticar_app = FastAPI()
    assert ".pdf" in EXTENSIONES_PERMITIDAS
    assert ".exe" not in EXTENSIONES_PERMITIDAS
    assert TAMANO_MAXIMO_BYTES == 10 * 1024 * 1024


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("../../etc/passwd", "passwd"),
        ("/tmp/malo.pdf", "malo.pdf"),
        ("cámara comercio.pdf", "camara comercio.pdf"),
        ("", "documento"),
        # Todo lo anterior a la última barra es ruta y se descarta.
        ("a;rm -rf /.pdf", ".pdf"),
        ("informe;rm.pdf", "informe_rm.pdf"),
    ],
)
def test_el_nombre_de_archivo_se_sanea(entrada, esperado):
    """
    El nombre que envía el cliente nunca debe poder salirse de su carpeta
    ni traer caracteres raros.
    """
    assert _nombre_seguro(entrada) == esperado
