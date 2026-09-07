from fastapi.testclient import TestClient

from main import app
from core.security import get_current_user


client = TestClient(app)


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
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 200

    app.dependency_overrides[get_current_user] = override_user("Auxiliar")
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 200

    app.dependency_overrides.clear()


def test_comite_expedientes_pendientes_rechaza_otros_roles():
    app.dependency_overrides[get_current_user] = override_user("Auditor")
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 403

    app.dependency_overrides[get_current_user] = override_user("Empresa")
    response = client.get("/comite/expedientes-pendientes")
    assert response.status_code == 403

    app.dependency_overrides.clear()
