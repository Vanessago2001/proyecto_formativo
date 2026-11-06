from fastapi.testclient import TestClient
from core.database import get_db

from main import app
from core.security import get_current_user


client = TestClient(app)


class ResultadoComiteFalso:
    def __init__(self, filas=None):
        self.filas = filas or []

    def mappings(self):
        return self

    def all(self):
        return self.filas

    def first(self):
        return self.filas[0] if self.filas else None


class SesionComiteFalsa:
    def __init__(self, filas=None):
        self.filas = filas or []

    async def execute(self, *_args, **_kwargs):
        return ResultadoComiteFalso(self.filas)


async def override_db():
    yield SesionComiteFalsa()


def override_user(role_name: str):
    async def _override():
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "nombre": "tester",
            "correo": "tester@example.com",
            "estado": "Activo",
            "rol_id": 1,
            "role_name": role_name,
        }
    return _override


def test_comite_expedientes_pendientes_permite_admin_y_auxiliar():
    app.dependency_overrides[get_current_user] = override_user("Administrador")
    app.dependency_overrides[get_db] = override_db
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 200

    app.dependency_overrides[get_current_user] = override_user("Auxiliar")
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 200

    app.dependency_overrides.clear()


def test_comite_expedientes_pendientes_rechaza_otros_roles():
    app.dependency_overrides[get_current_user] = override_user("Auditor")
    app.dependency_overrides[get_db] = override_db
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 403

    app.dependency_overrides[get_current_user] = override_user("Empresa")
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 403

    app.dependency_overrides.clear()


def test_comite_consultas_relacionadas_devuelven_datos_de_sus_fuentes():
    filas = [{
        "id_informe": "informe-1",
        "id_auditoria": "auditoria-1",
        "version": 1,
        "tipo": "Definitivo",
        "contenido": {"hallazgos": {"no_conformidades_mayores": 1, "no_conformidades_menores": 2}},
        "estado": "Enviado",
        "fecha_generacion": "2025-01-01",
        "fecha_finalizacion": "2025-01-02",
        "fecha_envio_comite": "2025-01-03",
        "hash_documento": "abc",
        "firma_digital": "firma",
        "estado_auditoria": "Cerrada",
        "id_evidencia": "evidencia-1",
        "id_hallazgo": "hallazgo-1",
        "nombre_archivo": "foto.jpg",
        "tipo_archivo": "jpg",
        "version_evidencia": 1,
        "fecha_subida": "2025-01-01",
        "hash_archivo": "def",
        "subida_por": "Técnico",
        "id": "hallazgo-1",
        "codigo": "NC-01",
        "clasificacion": "Mayor",
        "descripcion": "Hallazgo de prueba",
        "requisito_relacionado": "7.1",
        "estado_hallazgo": "Pendiente",
        "fecha_registro": "2025-01-01",
        "fecha_cierre": None,
        "numeral": "7.1",
        "requisito_descripcion": "Requisito de prueba",
        "id_observacion": "observacion-1",
        "tipo_observacion": "Tecnica",
        "fecha": "2025-01-01",
        "tecnico": "Técnico",
    }]
    db = SesionComiteFalsa(filas)

    async def override_db_consultas():
        yield db

    app.dependency_overrides[get_current_user] = override_user("Auxiliar")
    app.dependency_overrides[get_db] = override_db_consultas
    try:
        informe = client.get("/comite/informe-auditor/11111111-1111-1111-1111-111111111111")
        evidencias = client.get("/comite/evidencias-fisicas/11111111-1111-1111-1111-111111111111")
        no_conformidades = client.get("/comite/no-conformidades/11111111-1111-1111-1111-111111111111")
        observaciones = client.get("/comite/observaciones-tecnicos/11111111-1111-1111-1111-111111111111")
    finally:
        app.dependency_overrides.clear()

    assert informe.status_code == 200
    assert informe.json()["informe"]["resultado"] == "1 no conformidad mayor, 2 menores"
    assert evidencias.status_code == 200
    assert evidencias.json()["evidencias"][0]["nombre_archivo"] == "foto.jpg"
    assert no_conformidades.status_code == 200
    assert no_conformidades.json()["no_conformidades"][0]["codigo"] == "NC-01"
    assert observaciones.status_code == 200
    assert observaciones.json()["observaciones"][0]["tecnico"] == "Técnico"
