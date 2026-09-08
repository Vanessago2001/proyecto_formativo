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
def mock_user():
    # Quien presenta una apelacion es la empresa o el auditor que no fue
    # aceptado; el publico general presenta PQRS, no apelaciones. Un
    # Administrador no puede registrarla, por eso el rol de prueba es Empresa.
    return {"id_usuario": "1", "role_name": "Empresa"}


@pytest.mark.asyncio
async def test_registrar_apelacion_y_adjuntar_evidencia(mock_db_session, mock_user):
    create_result = MagicMock()
    create_result.mappings().first.return_value = {
        "id": 10,
        "id_solicitud": 21,
        "estado": "RADICADA",
        "fecha": "2026-09-08T10:00:00",
        "motivo": "La decisión fue incorrecta",
        "fallo": "No aplica",
    }

    evidence_result = MagicMock()
    evidence_result.mappings().first.return_value = {
        "id_evidencia": 1,
        "id_apelacion": 10,
        "id_usuario": 1,
        "nombre_archivo": "recurso.pdf",
        "tipo_evidencia": "pdf",
        "url_archivo": "https://example.com/recurso.pdf",
        "descripcion": "Evidencia de soporte",
        "fecha_subida": "2026-09-08T10:05:00",
    }

    mock_db_session.execute.side_effect = [create_result, evidence_result]

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    payload = {
        "id_solicitud": 21,
        "motivo": "La decisión fue incorrecta",
        "fallo": "No aplica",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/apelaciones/", json=payload)
        evidence_response = await ac.post(
            "/api/apelaciones/10/evidencias",
            json={
                "id_usuario": 1,
                "nombre_archivo": "recurso.pdf",
                "tipo_evidencia": "pdf",
                "url_archivo": "https://example.com/recurso.pdf",
                "descripcion": "Evidencia de soporte",
            },
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["motivo"] == "La decisión fue incorrecta"
    assert evidence_response.status_code == status.HTTP_201_CREATED
    assert evidence_response.json()["nombre_archivo"] == "recurso.pdf"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_consultar_historial_apelacion(mock_db_session, mock_user):
    apelacion_result = MagicMock()
    apelacion_result.mappings().first.return_value = {
        "id": 10,
        "id_solicitud": 21,
        "estado": "RADICADA",
        "fecha": "2026-09-08T10:00:00",
        "motivo": "La decisión fue incorrecta",
        "fallo": "No aplica",
    }

    evidencia_result = MagicMock()
    evidencia_result.mappings().all.return_value = [
        {
            "id_evidencia": 1,
            "id_apelacion": 10,
            "id_usuario": 1,
            "nombre_archivo": "recurso.pdf",
            "tipo_evidencia": "pdf",
            "url_archivo": "https://example.com/recurso.pdf",
            "descripcion": "Evidencia de soporte",
            "fecha_subida": "2026-09-08T10:05:00",
        }
    ]

    mock_db_session.execute.side_effect = [apelacion_result, evidencia_result]

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/apelaciones/10/historial")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["estado"] == "RADICADA"

    app.dependency_overrides.clear()
