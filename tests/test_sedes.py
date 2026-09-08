from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app


@pytest.fixture
def mock_db_session():
    return AsyncMock()


@pytest.fixture
def mock_admin_user():
    return {"id_usuario": "1", "role_name": "Administrador"}


@pytest.mark.asyncio
async def test_get_sedes_empresa_success(mock_db_session, mock_admin_user):
    mock_result = MagicMock()
    mock_result.mappings().all.return_value = [
        {
            "id_sede": 1,
            "id_empresa": 5,
            "nombre_sede": "Sede principal",
            "direccion": "Calle 10 # 20-30",
            "ciudad": "Bogotá",
            "departamento": "Cundinamarca",
            "pais": "Colombia",
            "es_principal": True,
            "estado": "Activo",
            "fecha_registro": "2024-01-01T00:00:00",
        }
    ]
    mock_db_session.execute.return_value = mock_result

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_admin_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/empresas/5/sedes")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["nombre_sede"] == "Sede principal"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_sede_empresa_success(mock_db_session, mock_admin_user):
    mock_result = MagicMock()
    mock_result.mappings().first.return_value = {
        "id_sede": 2,
        "id_empresa": 5,
        "nombre_sede": "Sede Medellín",
        "direccion": "Carrera 50 # 20-30",
        "ciudad": "Medellín",
        "departamento": "Antioquia",
        "pais": "Colombia",
        "es_principal": False,
        "estado": "Activo",
        "fecha_registro": "2024-01-02T00:00:00",
    }
    mock_db_session.execute.return_value = mock_result

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_admin_user

    payload = {
        "nombre_sede": "Sede Medellín",
        "direccion": "Carrera 50 # 20-30",
        "ciudad": "Medellín",
        "departamento": "Antioquia",
        "pais": "Colombia",
        "es_principal": False,
        "estado": "Activo",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/empresas/5/sedes", json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["nombre_sede"] == "Sede Medellín"

    app.dependency_overrides.clear()
