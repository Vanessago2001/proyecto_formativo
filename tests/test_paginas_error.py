"""La página de error se muestra al navegador; el API sigue respondiendo JSON."""

from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.paginas_error import registrar_paginas_error

HTML = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    registrar_paginas_error(app)

    @app.get("/prohibido")
    async def prohibido():
        raise HTTPException(status_code=403, detail="Sin permiso.")

    @app.get("/falla")
    async def falla():
        raise RuntimeError("fallo interno de prueba")

    @app.get("/solicitud/{id_solicitud}")
    async def solicitud(id_solicitud: UUID):
        return {"id": str(id_solicitud)}

    return TestClient(app, raise_server_exceptions=False)


def test_pagina_inexistente_muestra_la_pagina_de_error(cliente):
    respuesta = cliente.get("/no-existe", headers=HTML)

    assert respuesta.status_code == 404
    assert "text/html" in respuesta.headers["content-type"]
    assert "No encontramos esta página" in respuesta.text
    assert "Error 404" in respuesta.text
    assert "login-header" in respuesta.text  # mismo encabezado del sistema
    assert "{{" not in respuesta.text  # no quedan marcas sin rellenar


def test_el_api_sigue_respondiendo_json(cliente):
    respuesta = cliente.get("/no-existe")  # fetch envía Accept: */*

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "Not Found"}


def test_error_de_permiso_ofrece_iniciar_sesion(cliente):
    pagina = cliente.get("/prohibido", headers=HTML)
    api = cliente.get("/prohibido")

    assert pagina.status_code == 403
    assert "No tiene permiso para ver esta página" in pagina.text
    assert 'id="btnLogin" href="/login" >' in pagina.text  # visible
    assert api.json() == {"detail": "Sin permiso."}


def test_error_interno_muestra_referencia_y_no_el_detalle_tecnico(cliente):
    respuesta = cliente.get("/falla", headers=HTML)

    assert respuesta.status_code == 500
    assert "Ocurrió un error en el sistema" in respuesta.text
    assert "Código de referencia" in respuesta.text
    assert "fallo interno de prueba" not in respuesta.text
    assert 'id="btnReintentar" >' in respuesta.text  # botón "Intentar de nuevo" visible


def test_error_interno_en_el_api_responde_json_con_referencia(cliente):
    respuesta = cliente.get("/falla")

    assert respuesta.status_code == 500
    cuerpo = respuesta.json()
    assert "error interno" in cuerpo["detail"]
    assert len(cuerpo["referencia"]) == 8


def test_parametro_mal_formado_en_una_pagina_es_direccion_no_valida(cliente):
    pagina = cliente.get("/solicitud/abc", headers=HTML)
    api = cliente.get("/solicitud/abc")

    assert pagina.status_code == 400
    assert "La dirección no es válida" in pagina.text
    assert api.status_code == 422


def test_la_ruta_se_escapa_en_la_pagina(cliente):
    respuesta = cliente.get("/<script>alert(1)</script>", headers=HTML)

    assert respuesta.status_code == 404
    assert "<script>alert(1)</script>" not in respuesta.text
    assert "&lt;script&gt;" in respuesta.text


def test_post_que_falla_responde_json_aunque_acepte_html(cliente):
    respuesta = cliente.post("/no-existe", headers=HTML)

    assert respuesta.status_code in (404, 405)
    assert respuesta.headers["content-type"].startswith("application/json")
