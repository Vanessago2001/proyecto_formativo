"""
Flujo de la solicitud (18/11/2026):

  · la empresa no puede RADICAR sin sus documentos legales obligatorios
    (subidos y no rechazados) ni sin al menos una sede incluida;
  · el Coordinador no puede APROBAR sin esos documentos aprobados y con al
    menos una sede; al aprobar la solicitud queda lista para asignar auditor;
  · la visita solo se programa en una sede incluida en la solicitud.

Todo con bases simuladas (tests/fake_db.py); nada toca la base real.
"""

import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.empresas import requisitos_empresa as req
from modules.solicitudes import estado_solicitud as estados
from modules.solicitudes.solicitud_router import router as solicitud_router
from modules.solicitudes.trazabilidad_service import TrazabilidadService
from tests.fake_db import ResultadoFalso, SesionFalsa

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_EMPRESA = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def sesion() -> SesionFalsa:
    s = SesionFalsa()
    s.vincular(ID_USUARIO, ID_EMPRESA)
    return s


@pytest.fixture
def cliente(sesion) -> TestClient:
    app = FastAPI()
    app.include_router(solicitud_router)

    async def _db():
        yield sesion

    async def _empresa():
        return {"id_usuario": ID_USUARIO, "role_name": "Empresa", "estado": "Activo", "rol_id": 4}

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _empresa
    return TestClient(app)


def _borrador(sesion):
    return sesion.sembrar(id_empresa=ID_EMPRESA, id_norma=uuid.uuid4())


# ------------------------------------------------------------------
# Radicar (enviar) la solicitud
# ------------------------------------------------------------------

def test_radicar_sin_documentos_legales_responde_422_con_la_lista(cliente, sesion):
    solicitud = _borrador(sesion)
    sede = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    sesion.incluir_sede(solicitud["id_solicitud"], sede["id_sede"])

    respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    for tipo in req.DOCUMENTOS_LEGALES_OBLIGATORIOS:
        assert tipo in detalle
    assert "sin subir" in detalle
    assert sesion.solicitudes[str(solicitud["id_solicitud"])]["estado"] == "Borrador"


def test_radicar_con_documento_rechazado_o_vencido_no_cuenta(cliente, sesion):
    solicitud = _borrador(sesion)
    sede = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    sesion.incluir_sede(solicitud["id_solicitud"], sede["id_sede"])
    sesion.sembrar_documento_empresa(ID_EMPRESA, "RUT", "Rechazado")
    sesion.sembrar_documento_empresa(ID_EMPRESA, "Cámara de Comercio", "Pendiente",
                                     fecha_vencimiento=date.today() - timedelta(days=1))
    sesion.sembrar_documento_empresa(ID_EMPRESA, "Representación Legal", "Pendiente")

    respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert "RUT (rechazado" in detalle
    assert "Cámara de Comercio (vencido" in detalle
    assert "Representación Legal" not in detalle


def test_radicar_sin_sede_incluida_responde_422(cliente, sesion):
    solicitud = _borrador(sesion)
    for tipo in req.DOCUMENTOS_LEGALES_OBLIGATORIOS:
        sesion.sembrar_documento_empresa(ID_EMPRESA, tipo)
    # La empresa tiene una sede, pero no está en la solicitud.
    sesion.sembrar_sede(id_empresa=ID_EMPRESA)

    respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")

    assert respuesta.status_code == 422
    assert "al menos una sede" in respuesta.json()["detail"]
    assert "documentos legales" not in respuesta.json()["detail"]


def test_radicar_con_todo_completo_radica(cliente, sesion):
    solicitud = _borrador(sesion)
    sesion.cumplir_requisitos(solicitud)

    respuesta = cliente.post(f"/solicitudes/{solicitud['id_solicitud']}/radicar")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["estado"] == "Radicada"


def test_informacion_general_senala_los_requisitos_pendientes(cliente, sesion):
    solicitud = _borrador(sesion)
    from modules.solicitudes.informacion_service import InformacionService  # noqa: F401
    import asyncio

    pendientes = req.faltantes_para_radicar(
        asyncio.run(req.requisitos_empresa(sesion, ID_EMPRESA)),
        asyncio.run(req.sedes_incluidas(sesion, solicitud["id_solicitud"])),
    )
    assert len(pendientes) == 2
    assert pendientes[0].startswith("documentos legales obligatorios")
    assert "sede" in pendientes[1]


# ------------------------------------------------------------------
# Lista de verificación de la empresa
# ------------------------------------------------------------------

async def test_requisitos_empresa_cuenta_documentos_y_sedes(sesion):
    sesion.sembrar_documento_empresa(ID_EMPRESA, "RUT", "Aprobado")
    sesion.sembrar_documento_empresa(ID_EMPRESA, "Cámara de Comercio", "Correccion")
    sesion.sembrar_documento_empresa(ID_EMPRESA, "Otro", "Pendiente")  # opcional: no cuenta
    sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    sesion.sembrar_sede(id_empresa=ID_EMPRESA, estado="Inactiva")

    r = await req.requisitos_empresa(sesion, ID_EMPRESA)

    assert r["documentos_total"] == 3
    assert r["documentos_al_dia"] == 1
    assert r["documentos_aprobados"] == 1
    assert r["sedes_activas"] == 1
    assert r["completo"] is False
    assert any("Cámara de Comercio (con corrección" in f for f in r["documentos_faltantes"])
    assert any("Representación Legal (sin subir" in f for f in r["documentos_faltantes"])


async def test_si_hay_varias_versiones_cuenta_la_mejor(sesion):
    sesion.sembrar_documento_empresa(ID_EMPRESA, "RUT", "Rechazado")
    sesion.sembrar_documento_empresa(ID_EMPRESA, "RUT", "Aprobado")

    r = await req.requisitos_empresa(sesion, ID_EMPRESA)

    rut = next(d for d in r["documentos"] if d["tipo_documento"] == "RUT")
    assert rut["estado"] == "Aprobado"


# ------------------------------------------------------------------
# Aprobar la solicitud (Coordinador, SOL-054)
# ------------------------------------------------------------------

class _TrazabilidadFalsa(TrazabilidadService):
    """Solo cambia de dónde sale la solicitud; el resto es el servicio real."""

    def __init__(self, sesion, solicitud):
        super().__init__(sesion)
        self._fila = solicitud
        self.actualizada = False

    async def _solicitud(self, id_solicitud, usuario):
        return self._fila


async def test_aprobar_sin_documentos_legales_aprobados_responde_409(sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estados.EN_REVISION)
    sesion.cumplir_requisitos(solicitud, estado_documentos="Pendiente")

    with pytest.raises(HTTPException) as error:
        await _TrazabilidadFalsa(sesion, solicitud).cambiar_estado(
            solicitud["id_solicitud"], estados.APROBADA, None, {"id_usuario": ID_USUARIO}
        )

    assert error.value.status_code == 409
    assert "aprobar los documentos legales obligatorios" in error.value.detail
    assert solicitud["estado"] == estados.EN_REVISION


async def test_aprobar_sin_sede_responde_409(sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estados.EN_REVISION)
    for tipo in req.DOCUMENTOS_LEGALES_OBLIGATORIOS:
        sesion.sembrar_documento_empresa(ID_EMPRESA, tipo, "Aprobado")

    with pytest.raises(HTTPException) as error:
        await _TrazabilidadFalsa(sesion, solicitud).exigir_aprobable(solicitud, "Aprobada")

    assert error.value.status_code == 409
    assert "ninguna sede" in error.value.detail


async def test_aprobar_con_todo_deja_la_solicitud_lista_para_asignar(sesion, monkeypatch):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estados.EN_REVISION)
    sesion.cumplir_requisitos(solicitud, estado_documentos="Aprobado")

    from modules.solicitudes import bitacora

    async def _sin_bitacora(*a, **k):
        return None

    monkeypatch.setattr(bitacora, "registrar", _sin_bitacora)
    servicio = _TrazabilidadFalsa(sesion, solicitud)

    async def _historial(*a, **k):
        return None

    servicio._historial = _historial
    resultado = await servicio.cambiar_estado(
        solicitud["id_solicitud"], estados.APROBADA, "Todo en orden", {"id_usuario": ID_USUARIO}
    )

    # "Por asignar auditor" = solicitudes Aprobada sin auditor.
    assert resultado["estado"] == estados.APROBADA
    assert sesion.solicitudes[str(solicitud["id_solicitud"])]["estado"] == estados.APROBADA


async def test_otros_cambios_de_estado_no_exigen_los_requisitos(sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estados.RADICADA)
    # Sin documentos ni sedes: pasar a revisión o rechazar sigue permitido.
    await _TrazabilidadFalsa(sesion, solicitud).exigir_aprobable(solicitud, estados.EN_REVISION)
    await _TrazabilidadFalsa(sesion, solicitud).exigir_aprobable(solicitud, estados.RECHAZADA)


# ------------------------------------------------------------------
# Programar la visita (M6)
# ------------------------------------------------------------------

async def test_sede_de_la_visita_es_obligatoria_y_de_la_solicitud(sesion):
    solicitud = sesion.sembrar(id_empresa=ID_EMPRESA, estado=estados.APROBADA)
    incluida = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    otra = sesion.sembrar_sede(id_empresa=ID_EMPRESA)
    sesion.incluir_sede(solicitud["id_solicitud"], incluida["id_sede"])

    with pytest.raises(HTTPException) as sin_sede:
        await req.exigir_sede_de_la_solicitud(sesion, solicitud["id_solicitud"], None)
    assert sin_sede.value.status_code == 422

    with pytest.raises(HTTPException) as ajena:
        await req.exigir_sede_de_la_solicitud(sesion, solicitud["id_solicitud"], otra["id_sede"])
    assert ajena.value.status_code == 422
    assert "no está incluida" in ajena.value.detail

    await req.exigir_sede_de_la_solicitud(sesion, solicitud["id_solicitud"], incluida["id_sede"])


class _SesionAgenda:
    """Solo conoce las consultas previas a la regla de la sede."""

    def __init__(self, id_solicitud):
        self.id_solicitud = id_solicitud
        self.rollbacks = 0

    async def execute(self, sentencia, params=None):
        sql = " ".join(str(sentencia).split())
        if "FROM solicitud s WHERE s.id_solicitud" in sql:
            return ResultadoFalso([{"id_solicitud": self.id_solicitud, "estado": "Aprobada", "id_empresa": ID_EMPRESA}])
        if "FROM solicitud_sede ss" in sql:
            return ResultadoFalso([])  # la solicitud no tiene sedes
        raise AssertionError("No debe llegar más lejos: " + sql[:120])

    async def commit(self):
        raise AssertionError("No debe confirmar nada.")

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.sede_real
async def test_programar_sin_sede_de_la_solicitud_responde_422():
    from modules.agenda_auditor.agenda_schema import ProgramacionAuditoriaCrear
    from modules.agenda_auditor.agenda_service import AgendaAuditorService

    id_solicitud = uuid.uuid4()
    datos = ProgramacionAuditoriaCrear(
        id_solicitud=id_solicitud,
        auditores=[{"id_usuario": str(uuid.uuid4()), "rol_auditor": "Auditor líder"}],
        direccion_servicio="Calle 1 # 2-3",
        ciudad_servicio="Pereira",
        fecha_inicio=datetime(2099, 1, 7, 9, 0),
        fecha_fin=datetime(2099, 1, 7, 11, 0),
    )
    with pytest.raises(HTTPException) as error:
        await AgendaAuditorService(_SesionAgenda(id_solicitud)).crear_programacion(datos)

    assert error.value.status_code == 422
    assert "sede" in error.value.detail
