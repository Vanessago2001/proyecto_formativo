from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.apelaciones.apelaciones_service import ApelacionesService
from modules.solicitudes.solicitud_service import SolicitudService

ID_SOLICITUD = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ID_APELACION = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ID_USUARIO = UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_crear_apelacion_generar_radicado_y_estado_inicial(mock_db_session, mock_user, monkeypatch):
    creada = {
        "id": str(ID_APELACION),
        "id_solicitud": str(ID_SOLICITUD),
        "estado": "ENVIADA",
        "radicado": "APE-2026-000001",
        "motivo": "La decisión fue incorrecta",
        "razones_rechazo": "No se adjuntaron documentos",
    }
    monkeypatch.setattr(ApelacionesService, "create_apelacion", AsyncMock(return_value=creada))

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    payload = {
        "id_solicitud": str(ID_SOLICITUD),
        "motivo": "La decisión fue incorrecta",
        "razones_rechazo": "No se adjuntaron documentos",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/apelaciones/", json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["estado"] == "ENVIADA"
    assert response.json()["radicado"].startswith("APE-")

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_comite_no_puede_incluir_auditor_en_apelacion(mock_db_session):
    auditor = uuid4()
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": str(uuid4()), "role_name": "Comité"
    }
    app.dependency_overrides[get_db] = lambda: mock_db_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            f"/api/apelaciones/{ID_APELACION}/asignar-comite",
            json={"miembros_comite": [str(auditor)], "id_auditor_evaluador": str(auditor)},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "auditor" in response.json()["detail"].lower()

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_crear_apelacion_requiere_uuid_para_id_solicitud(mock_db_session, mock_user):
    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/apelaciones/",
            json={"id_solicitud": 21, "motivo": "La decisión fue incorrecta"},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_servicio_persiste_solicitud_uuid_y_razon_original(mock_db_session, monkeypatch):
    id_empresa = uuid4()
    solicitud = {
        "id_solicitud": ID_SOLICITUD,
        "id_empresa": id_empresa,
        "estado": "Rechazada",
        "observaciones": "Falta evidencia requerida.",
    }
    monkeypatch.setattr(SolicitudService, "consultar", AsyncMock(return_value=solicitud))
    monkeypatch.setattr(SolicitudService, "_exigir_propiedad", AsyncMock())

    duplicate_result = MagicMock()
    duplicate_result.scalar.return_value = None
    sequence_result = MagicMock()
    sequence_result.scalar.return_value = 8
    insert_result = MagicMock()
    insert_result.mappings().first.return_value = {
        "id": ID_APELACION,
        "id_solicitud": ID_SOLICITUD,
        "id_empresa": id_empresa,
        "estado": "ENVIADA",
        "radicado": "APE-2026-000008",
        "motivo": "La decisión fue incorrecta",
        "razones_rechazo": "Falta evidencia requerida.",
    }
    # El servicio consulta el motivo que escribio el Comite (comite_accion).
    # Aqui no hay ninguno, asi que debe caer en las observaciones de la solicitud.
    comite_result = MagicMock()
    comite_result.scalar.return_value = None
    mock_db_session.execute.side_effect = [duplicate_result, sequence_result, comite_result, insert_result]

    result = await ApelacionesService(mock_db_session).create_apelacion(
        {"id_solicitud": ID_SOLICITUD, "motivo": "La decisión fue incorrecta"},
        {"id_usuario": ID_USUARIO, "role_name": "Empresa"},
    )

    insert_sql = str(mock_db_session.execute.call_args_list[3].args[0])
    assert "id_solicitud_uuid" not in insert_sql
    assert "id_solicitud" in insert_sql
    assert result["id_solicitud"] == ID_SOLICITUD
    assert result["razones_rechazo"] == "Falta evidencia requerida."


@pytest.mark.asyncio
async def test_servicio_no_crea_apelacion_si_solicitud_no_esta_rechazada(mock_db_session, monkeypatch):
    monkeypatch.setattr(SolicitudService, "consultar", AsyncMock(return_value={"estado": "Radicada"}))
    monkeypatch.setattr(SolicitudService, "_exigir_propiedad", AsyncMock())

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(mock_db_session).create_apelacion(
            {"id_solicitud": ID_SOLICITUD, "motivo": "La decisión fue incorrecta"},
            {"id_usuario": ID_USUARIO, "role_name": "Empresa"},
        )

    assert error.value.status_code == status.HTTP_409_CONFLICT
    assert "Solo se puede apelar" in error.value.detail
    mock_db_session.execute.assert_not_awaited()


@pytest.fixture
def mock_db_session():
    return AsyncMock()


@pytest.fixture
def mock_user():
    # Solo la empresa titular puede presentar la apelación.
    return {"id_usuario": str(ID_USUARIO), "role_name": "Empresa"}


@pytest.mark.asyncio
async def test_registrar_apelacion_y_adjuntar_evidencia(mock_db_session, mock_user, monkeypatch):
    creada = {
        "id": str(ID_APELACION),
        "id_solicitud": str(ID_SOLICITUD),
        "estado": "ENVIADA",
        "fecha": "2026-09-08T10:00:00",
        "motivo": "La decisión fue incorrecta",
    }
    evidencia = {
        "id_evidencia": str(uuid4()),
        "id_apelacion": str(ID_APELACION),
        "id_usuario": str(ID_USUARIO),
        "nombre_archivo": "recurso.pdf",
        "tipo_evidencia": "pdf",
        "url_archivo": "storage/apelaciones/evidencia.pdf",
        "descripcion": "Evidencia de soporte",
    }
    monkeypatch.setattr(ApelacionesService, "create_apelacion", AsyncMock(return_value=creada))
    # El endpoint admite varios documentos, asi que responde con la lista.
    monkeypatch.setattr(
        ApelacionesService,
        "add_evidences",
        AsyncMock(return_value={"agregadas": 1, "evidencias": [evidencia],
                                "requerimientos_atendidos": 0}),
    )

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    payload = {
        "id_solicitud": str(ID_SOLICITUD),
        "motivo": "La decisión fue incorrecta",
        "fallo": False,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/apelaciones/", json=payload)
        evidence_response = await ac.post(
            f"/api/apelaciones/{ID_APELACION}/evidencias",
            files={"archivo": ("recurso.pdf", b"contenido pdf", "application/pdf")},
            data={"descripcion": "Evidencia de soporte"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["motivo"] == "La decisión fue incorrecta"
    assert evidence_response.status_code == status.HTTP_201_CREATED
    assert evidence_response.json()["agregadas"] == 1
    assert evidence_response.json()["evidencias"][0]["nombre_archivo"] == "recurso.pdf"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_consultar_historial_apelacion(mock_db_session, mock_user, monkeypatch):
    historial = [{"id": str(ID_APELACION), "estado": "ENVIADA"}]
    monkeypatch.setattr(ApelacionesService, "get_historial", AsyncMock(return_value=historial))

    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/api/apelaciones/{ID_APELACION}/historial")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["estado"] == "ENVIADA"

    app.dependency_overrides.clear()
