from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app


@pytest.fixture
def app_fixture():
    return app


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.fixture
def mock_admin_user():
    return {"sub": "1", "role_name": "SUPERADM"}


@pytest.fixture
def mock_aux_user():
    return {"sub": "2", "role_name": "AUX"}


@pytest.fixture
def mock_unauthorized_user():
    return {"sub": "3", "role_name": "PUB"}


@pytest.mark.asyncio
async def test_get_all_empresas_success(app_fixture, mock_db_session, mock_admin_user):
    # Simular resultado de base de datos
    mock_result = MagicMock()
    mock_result.mappings().all.return_value = [
        {
            "id_empresa": 1,
            "nombre": "Empresa Test",
            "nit": "900123456-1",
            "ciudad": "Bogotá",
            "direccion": "Calle 100",
            "correo": "test@empresa.com",
            "estado": "ACTIVO"
        }
    ]
    mock_db_session.execute.return_value = mock_result

    app_fixture.dependency_overrides[get_db] = lambda: mock_db_session
    app_fixture.dependency_overrides[get_current_user] = lambda: mock_admin_user

    async with AsyncClient(transport=ASGITransport(app=app_fixture), base_url="http://test") as ac:
        response = await ac.get("/api/empresas/")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["nombre"] == "Empresa Test"

    app_fixture.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_registrar_empresa_forbidden(app_fixture, mock_db_session, mock_unauthorized_user):
    app_fixture.dependency_overrides[get_db] = lambda: mock_db_session
    app_fixture.dependency_overrides[get_current_user] = lambda: mock_unauthorized_user

    payload = {
        "nombre": "Nueva Empresa",
        "nit": "900999888-2",
        "ciudad": "Medellín",
        "direccion": "Carrera 50",
        "correo": "contacto@nueva.com",
        "estado": "ACTIVO"
    }

    async with AsyncClient(transport=ASGITransport(app=app_fixture), base_url="http://test") as ac:
        response = await ac.post("/api/empresas/", json=payload)

    assert response.status_code == status.HTTP_403_FORBIDDEN

    app_fixture.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_registrar_empresa_success(app_fixture, mock_db_session, mock_aux_user):
    mock_result = MagicMock()
    mock_result.mappings().first.return_value = {
        "id_empresa": 2,
        "nombre": "Sena Empresa",
        "nit": "899999000-1",
        "ciudad": "Cali",
        "direccion": "Avenida 3",
        "correo": "sena@sena.edu.co",
        "estado": "ACTIVO"
    }
    mock_db_session.execute.return_value = mock_result

    app_fixture.dependency_overrides[get_db] = lambda: mock_db_session
    app_fixture.dependency_overrides[get_current_user] = lambda: mock_aux_user

    payload = {
        "nombre": "Sena Empresa",
        "nit": "899999000-1",
        "ciudad": "Cali",
        "direccion": "Avenida 3",
        "correo": "sena@sena.edu.co",
        "estado": "ACTIVO"
    }

    async with AsyncClient(transport=ASGITransport(app=app_fixture), base_url="http://test") as ac:
        response = await ac.post("/api/empresas/", json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["id_empresa"] == 2
    assert data["nombre"] == "Sena Empresa"

    app_fixture.dependency_overrides.clear()