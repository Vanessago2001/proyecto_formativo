import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core.config import settings
from modules.comite.comite_acta_service import ComiteActaService


class Resultado:
    def __init__(self, rows=None, scalar=None):
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class BaseFalsa:
    def __init__(self, *resultados):
        self.resultados = list(resultados)
        self.ejecuciones = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, sentencia, parametros=None):
        self.ejecuciones.append((str(sentencia), parametros or {}))
        return self.resultados.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def test_generar_guarda_acta_pdf_y_hash_en_la_base(tmp_path, monkeypatch):
    id_solicitud = uuid4()
    id_usuario = uuid4()
    expediente = {
        "id_solicitud": id_solicitud,
        "estado": "Aprobada",
        "numero_radicado": "RAD-2026-001",
        "alcance_certificacion": "Producción",
        "observaciones": "Revisión completada",
        "empresa": "Empresa de prueba",
        "nit": "900123456",
        "norma_codigo": "ISO 9001",
        "norma_nombre": "Calidad",
        "norma_version": "2015",
    }
    db = BaseFalsa(
        Resultado([expediente]),
        Resultado([{"accion": "aprobar", "datos": {"comentario": "Cumple los requisitos"}}]),
        Resultado(scalar=0),
        Resultado(),
        Resultado(),
    )
    monkeypatch.setattr(settings, "COMITE_ACTAS_STORAGE_DIR", str(tmp_path))

    respuesta = asyncio.run(
        ComiteActaService(db).generar(
            id_solicitud, "Justificación aprobada", {"id_usuario": str(id_usuario)}
        )
    )

    archivo = tmp_path / f"{respuesta['id_acta']}.pdf"
    contenido = archivo.read_bytes()
    assert contenido.startswith(b"%PDF")
    assert hashlib.sha256(contenido).hexdigest() == respuesta["huella_pdf"]
    assert respuesta["estado"] == "GENERADA"
    assert db.commits == 1
    registro = db.ejecuciones[3][1]
    assert registro["version"] == 1
    assert json.loads(registro["datos"])["dictamen"] == "Aprobado"


def test_generar_acta_exige_un_dictamen_final():
    db = BaseFalsa(Resultado([{"id_solicitud": uuid4(), "estado": "En revision"}]))

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            ComiteActaService(db).generar(
                uuid4(), "Justificación", {"id_usuario": str(uuid4())}
            )
        )

    assert error.value.status_code == 409
    assert len(db.ejecuciones) == 1
    assert db.commits == 0


@pytest.mark.asyncio
async def test_firmar_acta_persiste_pdf_firmado_y_descarga_valida(
    tmp_path, monkeypatch
):
    from modules.certificados.firma_service import FirmaService
    import modules.comite.comite_acta_service as modulo_acta

    id_solicitud = uuid4()
    id_acta = uuid4()
    id_lider = uuid4()
    borrador = b"%PDF-1.4 draft"
    firmado = b"%PDF-1.4 signed"
    huella_borrador = hashlib.sha256(borrador).hexdigest()
    huella_firmado = hashlib.sha256(firmado).hexdigest()
    (tmp_path / f"{id_acta}.pdf").write_bytes(borrador)
    monkeypatch.setattr(settings, "COMITE_ACTAS_STORAGE_DIR", str(tmp_path))

    async def verificar(_self, _usuario, _password):
        return {"id_usuario": str(id_lider), "hash_firma": "hash"}

    monkeypatch.setattr(FirmaService, "verificar", verificar)
    monkeypatch.setattr(
        modulo_acta,
        "firmar_pdf_pades",
        lambda *_args: (firmado, huella_firmado, "f" * 64),
    )
    db = BaseFalsa(
        Resultado([{"id_usuario": id_lider}]),
        Resultado(),
        Resultado([{"id_usuario": id_lider, "correo": "lider@example.test"}]),
        Resultado([{
            "id_acta": id_acta,
            "version": 1,
            "estado": "GENERADA",
            "huella_pdf": huella_borrador,
        }]),
        Resultado(),
        Resultado(),
        Resultado([{
            "id_acta": id_acta,
            "version": 1,
            "estado": "FIRMADA",
            "huella_pdf": huella_firmado,
        }]),
    )

    respuesta = await ComiteActaService(db).firmar(
        id_solicitud, "password", {"id_usuario": str(id_lider)}
    )
    descargado, version = await ComiteActaService(db).descargar_firmada(id_solicitud)

    assert respuesta["estado"] == "FIRMADA"
    assert descargado == firmado
    assert version == 1
    assert not (tmp_path / f"{id_acta}.pdf").exists()
    assert db.commits == 1


@pytest.mark.asyncio
async def test_firma_de_acta_solo_la_puede_aplicar_el_lider_actual(
    tmp_path, monkeypatch
):
    from modules.certificados.firma_service import FirmaService

    async def verificar(_self, _usuario, _password):
        return {"id_usuario": "otro", "hash_firma": "hash"}

    monkeypatch.setattr(FirmaService, "verificar", verificar)
    monkeypatch.setattr(settings, "COMITE_ACTAS_STORAGE_DIR", str(tmp_path))
    db = BaseFalsa(
        Resultado([{"id_usuario": uuid4()}]),
    )

    with pytest.raises(HTTPException) as error:
        await ComiteActaService(db).firmar(
            uuid4(), "password", {"id_usuario": "otro"}
        )

    assert error.value.status_code == 403
    assert len(db.ejecuciones) == 1
    assert db.commits == 0
