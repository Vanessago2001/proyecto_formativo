from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.archivos_firmados import firmar_url
from modules.archivos import archivos_router


def test_archivo_firmado_admite_head_y_get(monkeypatch, tmp_path):
    contenido = b"%PDF-1.4 documento de prueba"
    archivo = tmp_path / "documento.pdf"
    archivo.write_bytes(contenido)
    monkeypatch.setattr(
        archivos_router,
        "resolver_en_uploads",
        lambda relativo: archivo if relativo == "auditores/documento.pdf" else None,
    )

    app = FastAPI()
    app.include_router(archivos_router.router)
    url = firmar_url("/uploads/auditores/documento.pdf")

    with TestClient(app) as cliente:
        respuesta_head = cliente.head(url)
        respuesta_get = cliente.get(url)

    assert respuesta_head.status_code == 200
    assert respuesta_head.content == b""
    assert respuesta_get.status_code == 200
    assert respuesta_get.content == contenido
