"""Regresión: reponer la foto profesional rechazada no debe crear una segunda foto.

El administrador rechaza la foto en "banco de auditores → ver solicitud" y deja la
fila en estado 'Rechazado'. Cuando el auditor sube otra desde el formulario de
registro, esa misma fila debe sustituirse; si se inserta una nueva, la postulacion
queda con dos fotos y la rechazada sigue visible para el administrador.
"""

import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_POSTULACION = uuid.UUID("22222222-2222-2222-2222-222222222222")

FOTO = "Foto Profesional"
AHORA = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def documento_documento(
    tipo_documento: str,
    estado_revision: str,
    url_archivo: str,
    fecha_subida: datetime,
) -> dict:
    return {
        "id_documento": uuid.uuid4(),
        "id_postulacion": ID_POSTULACION,
        "id_usuario": ID_USUARIO,
        "tipo_documento": tipo_documento,
        "nombre_archivo": Path(url_archivo).name,
        "url_archivo": url_archivo,
        "estado_revision": estado_revision,
        "observacion_revision": "La foto no cumple" if estado_revision == "Rechazado" else "",
        "revisado_por": uuid.uuid4() if estado_revision == "Rechazado" else None,
        "fecha_subida": fecha_subida,
        "fecha_revision": fecha_subida if estado_revision == "Rechazado" else None,
    }


class SesionDocumentos:
    """Doble de `documento_auditor` en memoria, con las consultas que usa el servicio."""

    def __init__(self, documentos: list[dict]):
        self.documentos = documentos
        self.commitido = False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        tipo_documento = params.get("tipo_documento")

        if "FROM postulacion_auditor" in sql:
            return ResultadoFalso([
                {
                    "id_postulacion": ID_POSTULACION,
                    "id_usuario": ID_USUARIO,
                    "estado": "Correcciones",
                    "fecha_postulacion": AHORA - timedelta(days=3),
                    "fecha_revision": AHORA - timedelta(days=1),
                    "observaciones_tecnicas": "",
                }
            ])

        if "FROM usuario" in sql and "estado_auditor" in sql:
            return ResultadoFalso([
                {
                    "id_usuario": ID_USUARIO,
                    "nombre": "Ana Auditora",
                    "correo": "ana@example.com",
                    "estado": "Activo",
                    "estado_auditor": "Postulante",
                    "tipo_doc": "Cédula de Ciudadanía",
                    "num_doc": "1010101010",
                }
            ])

        if sql.startswith("SELECT COUNT(*)") and "estado_revision = 'Aprobado'" in sql:
            aprobados = [
                documento
                for documento in self.documentos
                if documento["tipo_documento"] == tipo_documento
                and documento["estado_revision"] == "Aprobado"
            ]
            return ResultadoFalso(escalar=len(aprobados))

        if "FROM documento_auditor" in sql and "ORDER BY fecha_subida DESC" in sql:
            filas = [
                documento
                for documento in self.documentos
                if documento["tipo_documento"] == tipo_documento
            ]
            filas.sort(key=lambda documento: documento["fecha_subida"], reverse=True)
            return ResultadoFalso(filas)

        if sql.startswith("UPDATE documento_auditor"):
            objetivo = next(
                (
                    documento
                    for documento in self.documentos
                    if str(documento["id_documento"]) == str(params["id_documento"])
                ),
                None,
            )
            if objetivo is None:
                return ResultadoFalso([])
            objetivo.update(
                {
                    "nombre_archivo": params["nombre_archivo"],
                    "url_archivo": params["url_archivo"],
                    "estado_revision": "Pendiente",
                    "observacion_revision": "",
                    "revisado_por": None,
                    "fecha_revision": None,
                }
            )
            return ResultadoFalso([dict(objetivo)])

        if sql.startswith("DELETE FROM documento_auditor") and "id_documento = :id_documento" in sql:
            self.documentos = [
                documento
                for documento in self.documentos
                if str(documento["id_documento"]) != str(params["id_documento"])
            ]
            return ResultadoFalso([])

        if sql.startswith("DELETE FROM documento_auditor"):
            self.documentos = [
                documento
                for documento in self.documentos
                if not (
                    documento["tipo_documento"] == tipo_documento
                    and documento["estado_revision"] == "Pendiente"
                )
            ]
            return ResultadoFalso([])

        if sql.startswith("INSERT INTO documento_auditor"):
            nuevo = {
                "id_documento": uuid.uuid4(),
                "id_postulacion": ID_POSTULACION,
                "id_usuario": ID_USUARIO,
                "tipo_documento": params["tipo_documento"],
                "nombre_archivo": params["nombre_archivo"],
                "url_archivo": params["url_archivo"],
                "estado_revision": "Pendiente",
                "observacion_revision": "",
                "revisado_por": None,
                "fecha_subida": AHORA,
                "fecha_revision": None,
            }
            self.documentos.append(nuevo)
            return ResultadoFalso([dict(nuevo)])

        return ResultadoFalso([])

    async def commit(self):
        self.commitido = True

    async def rollback(self):
        raise AssertionError("El reemplazo de la foto no deberia llegar al rollback.")


def archivo_subido(nombre="foto-nueva.jpg", contenido=b"foto nueva"):
    return UploadFile(file=io.BytesIO(contenido), filename=nombre)


async def subir_foto(sesion):
    # `DIRECTORIO_DOCUMENTOS` es relativo y el fixture cambia el directorio de
    # trabajo, asi que la foto se escribe dentro de tmp_path.
    return await AuditorService(sesion).adjuntar_documento(
        id_usuario=ID_USUARIO,
        tipo_documento=FOTO,
        archivo=archivo_subido(),
    )


@pytest.fixture
def carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def fotos(documentos):
    return [documento for documento in documentos if documento["tipo_documento"] == FOTO]


async def test_la_foto_rechazada_se_sustituye_en_su_propia_fila(carpeta_temporal):
    rechazada = documento_documento(FOTO, "Rechazado", "/uploads/auditores/vieja.jpg", AHORA - timedelta(days=1))
    id_rechazada = rechazada["id_documento"]
    url_rechazada = rechazada["url_archivo"]
    (carpeta_temporal / "uploads/auditores").mkdir(parents=True)
    (carpeta_temporal / "uploads/auditores/vieja.jpg").write_bytes(b"foto rechazada")

    sesion = SesionDocumentos([rechazada])
    respuesta = await subir_foto(sesion)

    guardadas = fotos(sesion.documentos)
    assert len(guardadas) == 1
    actual = guardadas[0]

    # Es la misma fila: no nace una segunda foto.
    assert actual["id_documento"] == id_rechazada
    assert respuesta["documento"]["id_documento"] == id_rechazada

    # Vuelve a quedar pendiente de revision y sin el rastro del rechazo.
    assert actual["estado_revision"] == "Pendiente"
    assert actual["observacion_revision"] == ""
    assert actual["revisado_por"] is None
    assert actual["url_archivo"] == respuesta["documento"]["url_archivo"]
    assert actual["url_archivo"] != url_rechazada
    assert sesion.commitido is True


async def test_el_archivo_rechazado_se_retira_y_la_nueva_queda_en_disco(carpeta_temporal):
    rechazada = documento_documento(FOTO, "Rechazado", "/uploads/auditores/vieja.jpg", AHORA - timedelta(days=1))
    (carpeta_temporal / "uploads/auditores").mkdir(parents=True)
    vieja = carpeta_temporal / "uploads/auditores/vieja.jpg"
    vieja.write_bytes(b"foto rechazada")

    sesion = SesionDocumentos([rechazada])
    respuesta = await subir_foto(sesion)

    assert not vieja.exists()
    nueva = carpeta_temporal / respuesta["documento"]["url_archivo"].lstrip("/")
    assert nueva.exists()
    assert nueva.read_bytes() == b"foto nueva"


async def test_deja_una_sola_foto_cuando_ya_habia_duplicados(carpeta_temporal):
    """El propio error dejo antes una rechazada vieja y una pendiente nueva."""
    rechazada = documento_documento(FOTO, "Rechazado", "/uploads/auditores/vieja.jpg", AHORA - timedelta(days=2))
    pendiente = documento_documento(FOTO, "Pendiente", "/uploads/auditores/intermedia.jpg", AHORA - timedelta(days=1))

    sesion = SesionDocumentos([rechazada, pendiente])
    await subir_foto(sesion)

    guardadas = fotos(sesion.documentos)
    assert len(guardadas) == 1
    assert guardadas[0]["id_documento"] == pendiente["id_documento"]
    assert guardadas[0]["estado_revision"] == "Pendiente"


async def test_sin_foto_previa_se_inserta_una(carpeta_temporal):
    sesion = SesionDocumentos([])
    respuesta = await subir_foto(sesion)

    guardadas = fotos(sesion.documentos)
    assert len(guardadas) == 1
    assert guardadas[0]["id_documento"] == respuesta["documento"]["id_documento"]
    assert guardadas[0]["estado_revision"] == "Pendiente"


async def test_foto_aprobada_no_se_puede_volver_a_sustituir(carpeta_temporal):
    aprobada = documento_documento(FOTO, "Aprobado", "/uploads/auditores/buena.jpg", AHORA - timedelta(days=1))

    sesion = SesionDocumentos([aprobada])
    with pytest.raises(HTTPException) as error:
        await subir_foto(sesion)

    assert error.value.status_code == 400
    assert fotos(sesion.documentos) == [aprobada]


async def test_la_regla_no_alcance_a_los_demas_tipos(carpeta_temporal):
    """Solo la foto profesional es documento unico; los demas tipos siguen igual."""
    rechazado = documento_documento("Hoja de Vida", "Rechazado", "/uploads/auditores/hv1.pdf", AHORA - timedelta(days=1))

    sesion = SesionDocumentos([rechazado])
    await AuditorService(sesion).adjuntar_documento(
        id_usuario=ID_USUARIO,
        tipo_documento="Hoja de Vida",
        archivo=archivo_subido("hv2.pdf", b"hoja de vida"),
    )

    # Comportamiento historico: la rechazada permanece y la nueva se suma.
    assert len(sesion.documentos) == 2
    assert rechazado in sesion.documentos
