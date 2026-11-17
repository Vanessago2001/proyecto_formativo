"""
Apelación aprobada -> solicitud aprobada + borrador del certificado, y
certificados sin "alcance".

Antes una apelación aprobada (y luego notificada/cerrada) dejaba la solicitud
en 'Rechazada': no se podía generar el certificado ni aprobarla en el Comité.
"""

import asyncio
import inspect
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from core.security import get_current_user
from main import app
from modules.apelaciones.apelaciones_service import ApelacionesService, texto_estado_apelacion
from modules.certificados import certificados_service as modulo_cert
from modules.certificados.certificados_schema import CertificadoCrear
from modules.certificados.certificados_service import CertificadosService

ID_APELACION = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ID_SOLICITUD = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ID_EMPRESA = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
USUARIO = {"id_usuario": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "role_name": "Comité"}


class Resultado:
    def __init__(self, filas=None, escalar=None):
        self.filas = filas or []
        self.escalar = escalar

    def mappings(self):
        return self

    def first(self):
        return self.filas[0] if self.filas else None

    def all(self):
        return self.filas

    def scalar_one_or_none(self):
        return self.escalar

    def scalar_one(self):
        return self.escalar

    def scalar(self):
        return self.escalar


class BaseFalsa:
    """Responde según el texto del SQL y guarda todo lo ejecutado."""

    def __init__(self, respuestas):
        self.respuestas = respuestas  # lista de (fragmento, Resultado)
        self.sql = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, consulta, parametros=None):
        texto = " ".join(str(consulta).split())
        self.sql.append((texto, parametros or {}))
        for fragmento, resultado in self.respuestas:
            if fragmento in texto:
                return resultado(texto, parametros) if callable(resultado) else resultado
        return Resultado()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def ejecutadas(self, fragmento):
        return [p for texto, p in self.sql if fragmento in texto]


def _fila_apelacion(estado="APROBADA", fallo=False, estado_solicitud="Rechazada"):
    return {
        "id_solicitud": ID_SOLICITUD, "radicado": "APE-2026-000014", "estado": estado,
        "fallo": fallo, "estado_solicitud": estado_solicitud,
        "numero_radicado": "SOL-2026-0002", "id_empresa": ID_EMPRESA,
    }


def _base_favorable(estado_solicitud="Rechazada", **kw):
    estado_final = {"valor": estado_solicitud}

    def actualizar(_texto, parametros):
        estado_final["valor"] = parametros["estado"]
        return Resultado()

    return BaseFalsa([
        ("FROM apelacion a JOIN solicitud s", Resultado([_fila_apelacion(estado_solicitud=estado_solicitud, **kw)])),
        ("UPDATE solicitud SET estado", actualizar),
        ("SELECT estado FROM solicitud", lambda *_: Resultado(escalar=estado_final["valor"])),
        ("FROM asignacion_lider_comite a", Resultado([{"id_usuario": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", "id_asignacion": "x", "nombre": "Líder", "correo": "l@x.co"}])),
    ])


@pytest.fixture
def borrador(monkeypatch):
    llamadas = []

    async def crear_borrador(self, id_solicitud, usuario):
        llamadas.append(id_solicitud)
        return llamadas_respuesta[0]

    llamadas_respuesta = [{"creado": True, "codigo_verificacion": "CS-2026-000002"}]
    monkeypatch.setattr(CertificadosService, "crear_borrador_automatico", crear_borrador)
    return llamadas, llamadas_respuesta


def test_apelacion_aprobada_pasa_la_solicitud_a_aprobada_y_crea_el_borrador(borrador):
    llamadas, _ = borrador
    db = _base_favorable()
    resultado = asyncio.run(ApelacionesService(db).aplicar_apelacion_favorable(ID_APELACION, USUARIO))

    assert resultado["solicitud_actualizada"] is True
    assert resultado["certificado"] == {"creado": True, "codigo_verificacion": "CS-2026-000002"}
    assert db.ejecutadas("UPDATE solicitud SET estado")[0]["estado"] == "Aprobada"
    historial = db.ejecutadas("INSERT INTO historial_estado")
    assert historial and historial[0]["estado"] == "Aprobada" and "APE-2026-000014" in historial[0]["observacion"]
    assert llamadas == [ID_SOLICITUD]
    # Aviso a la empresa y al líder que debe firmar.
    avisos = db.ejecutadas("INSERT INTO notificacion")
    assert len(avisos) == 2
    assert "CS-2026-000002" in avisos[1]["mensaje"]
    assert all(len(a["mensaje"]) <= 255 for a in avisos)


def test_es_idempotente_si_ya_estaba_aprobada_y_con_certificado(borrador):
    llamadas, respuesta = borrador
    respuesta[0] = {"creado": False, "motivo": "La solicitud ya tiene el certificado CS-2026-000002."}
    db = _base_favorable(estado_solicitud="Aprobada")
    resultado = asyncio.run(ApelacionesService(db).aplicar_apelacion_favorable(ID_APELACION, USUARIO))

    assert resultado["solicitud_actualizada"] is False
    assert not db.ejecutadas("UPDATE solicitud SET estado")
    assert not db.ejecutadas("INSERT INTO historial_estado")
    assert not db.ejecutadas("INSERT INTO notificacion")
    assert llamadas == [ID_SOLICITUD]  # el borrador decide no duplicar


@pytest.mark.parametrize("estado,fallo", [("CERRADA", True), ("RECHAZADA", True), ("EN_REVISION", None)])
def test_no_toca_la_solicitud_si_la_apelacion_no_es_favorable(borrador, estado, fallo):
    llamadas, _ = borrador
    db = _base_favorable(estado=estado, fallo=fallo)
    resultado = asyncio.run(ApelacionesService(db).aplicar_apelacion_favorable(ID_APELACION, USUARIO))
    assert resultado == {"solicitud_actualizada": False, "certificado": None}
    assert not db.ejecutadas("UPDATE solicitud")
    assert llamadas == []


def test_no_certifica_una_solicitud_cerrada(borrador):
    llamadas, _ = borrador
    db = _base_favorable(estado_solicitud="Cerrada")
    resultado = asyncio.run(ApelacionesService(db).aplicar_apelacion_favorable(ID_APELACION, USUARIO))
    assert resultado["certificado"] is None and llamadas == []


@pytest.mark.parametrize(
    "nuevo,anterior,fallo,aplica",
    [("CERRADA", "NOTIFICADA", False, True), ("NOTIFICADA", "APROBADA", False, True),
     ("APROBADA", "EN_REVISION", False, True), ("CERRADA", "NOTIFICADA", True, False),
     ("RECHAZADA", "EN_REVISION", True, False)],
)
def test_cambiar_estado_dictamen_aplica_la_apelacion_favorable(monkeypatch, nuevo, anterior, fallo, aplica):
    llamadas = []

    async def obtener(self, id_apelacion, usuario=None):
        return {"id": id_apelacion, "estado": anterior, "id_solicitud": ID_SOLICITUD}

    async def aplicar(self, id_apelacion, usuario):
        llamadas.append(id_apelacion)
        return {"solicitud_actualizada": True, "certificado": {"creado": True}}

    monkeypatch.setattr(ApelacionesService, "get_apelacion_by_id", obtener)
    monkeypatch.setattr(ApelacionesService, "aplicar_apelacion_favorable", aplicar)
    db = BaseFalsa([("UPDATE apelacion", Resultado([{"id": ID_APELACION, "estado": nuevo, "fallo": fallo, "fecha_decision": None}]))])
    respuesta = asyncio.run(ApelacionesService(db).cambiar_estado_dictamen(ID_APELACION, nuevo, USUARIO))
    assert (llamadas == [ID_APELACION]) is aplica
    assert ("certificacion" in respuesta) is aplica


def test_resolver_aprobada_tambien_aplica(monkeypatch):
    llamadas = []

    async def obtener(self, id_apelacion, usuario=None):
        return {"id": id_apelacion, "estado": "EN_REVISION"}

    async def aplicar(self, id_apelacion, usuario):
        llamadas.append(id_apelacion)
        return {"solicitud_actualizada": True, "certificado": None}

    monkeypatch.setattr(ApelacionesService, "get_apelacion_by_id", obtener)
    monkeypatch.setattr(ApelacionesService, "aplicar_apelacion_favorable", aplicar)
    db = BaseFalsa([("UPDATE apelacion", Resultado([{"id": ID_APELACION, "estado": "APROBADA", "observaciones": "", "fecha_decision": None}]))])
    asyncio.run(ApelacionesService(db).registrar_decision_final(ID_APELACION, "APROBADA", "ok", USUARIO))
    assert llamadas == [ID_APELACION]


def test_texto_del_estado_para_la_empresa():
    assert texto_estado_apelacion("EN_REVISION") == "En revisión"
    assert texto_estado_apelacion("INFORMACION_SOLICITADA") == "Información solicitada"
    assert texto_estado_apelacion("CERRADA", False) == "Aprobada (cerrada)"
    assert texto_estado_apelacion("NOTIFICADA", True) == "No aprobada (notificada)"
    assert texto_estado_apelacion("RECHAZADA") == "No aprobada"


# ---------------- Portal de empresa: mis apelaciones ----------------

def test_mis_apelaciones_filtra_por_las_empresas_del_usuario():
    db = BaseFalsa([("FROM apelacion a", Resultado([{
        "id": ID_APELACION, "id_solicitud": ID_SOLICITUD, "radicado": "APE-1", "estado": "INFORMACION_SOLICITADA",
        "fallo": None, "requerimientos_pendientes": 0, "estado_solicitud": "Rechazada",
    }]))])
    filas = asyncio.run(ApelacionesService(db).mis_apelaciones({"id_usuario": "u-1"}))
    texto, parametros = db.sql[0]
    assert "user_empresa" in texto and "ue.estado = 'Activo'" in texto
    assert parametros == {"id_usuario": "u-1"}
    assert filas[0]["estado_texto"] == "Información solicitada"
    assert filas[0]["requerimientos_pendientes"] == 1


def test_mis_apelaciones_es_solo_para_la_empresa():
    async def comite():
        return {"id_usuario": "u-2", "role_name": "Comité"}

    app.dependency_overrides[get_current_user] = comite
    try:
        assert TestClient(app).get("/api/apelaciones/mias").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_empresa_no_puede_presentar_una_segunda_apelacion():
    fuente = inspect.getsource(ApelacionesService.create_apelacion)
    assert "SELECT id FROM apelacion WHERE id_solicitud" in fuente and "HTTP_409_CONFLICT" in fuente


# ---------------- Certificados sin alcance ----------------

def test_generar_certificado_no_exige_ni_guarda_alcance():
    assert "id_alcance" not in CertificadoCrear.model_fields
    db = BaseFalsa([
        ("FROM solicitud", Resultado([{"id_solicitud": ID_SOLICITUD, "estado": "Aprobada"}])),
        ("FROM certificado WHERE id_solicitud", Resultado(escalar=None)),
        ("FROM asignacion_lider_comite", Resultado([{"id_asignacion": "f0f0f0f0-f0f0-4f0f-8f0f-f0f0f0f0f0f0"}])),
        ("nextval", Resultado(escalar=7)),
        ("INSERT INTO certificado", Resultado(escalar="11111111-1111-4111-8111-111111111111")),
    ])
    servicio = CertificadosService(db)

    async def obtener(_id, usuario=None):
        return {"codigo_verificacion": "CS-2026-000007"}

    servicio._obtener = obtener
    datos = CertificadoCrear(id_solicitud=ID_SOLICITUD, fecha_vencimiento=date.today() + timedelta(days=365))
    certificado = asyncio.run(servicio.crear(datos, USUARIO))

    assert certificado["codigo_verificacion"] == "CS-2026-000007"
    assert not any("alcance" in texto.lower() for texto, _ in db.sql)


def test_firmar_publicar_y_consultar_no_dependen_del_alcance():
    fuente = inspect.getsource(modulo_cert)
    assert "alcance_solicitud" not in fuente and "id_alcance" not in fuente
    from modules.certificados import certificados_router

    assert "alcance" not in inspect.getsource(certificados_router).lower()
