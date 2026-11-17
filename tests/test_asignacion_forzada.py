"""
"Asignar de todas formas" a un auditor no elegible.

Antes el botón solo marcaba al auditor en la pantalla: el POST no llevaba
ninguna marca y el servidor volvía a validar y respondía 409 siempre. Ahora:
  · forzar=true + justificación + Coordinador (o Auxiliar con SOL-048) → se
    asigna y queda en historial_asignacion_auditor (ASIGNACION_FORZADA);
  · sin justificación → 422; rol sin permiso → 403;
  · el conflicto de interés con la empresa nunca se puede forzar (409).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.asignacion_auditores import asignacion_router
from tests.fake_db import ResultadoFalso

ID_SOLICITUD = uuid.uuid4()
ID_AUDITOR = uuid.uuid4()
ID_COORDINADOR = uuid.uuid4()


def _plano(sql) -> str:
    return " ".join(str(sql).split())


class SesionAsignacion:
    """Simula las consultas de `asignar` según el texto del SQL."""

    def __init__(self, competencia=False, conflicto=False):
        self.competencia = competencia
        self.conflicto = conflicto
        self.sentencias: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, sentencia, params=None):
        sql = _plano(sentencia)
        self.sentencias.append((sql, params or {}))
        if sql.startswith("SELECT 1 FROM programacion_visita"):
            return ResultadoFalso([])
        if "AS total FROM auditores_solicitud" in sql:
            return ResultadoFalso([])  # sin auditores activos: la solicitud no está completa
        if "FROM solicitud s LEFT JOIN empresa e" in sql:
            return ResultadoFalso([{
                "id_solicitud": ID_SOLICITUD, "numero_radicado": "SOL-1", "estado": "Aprobada",
                "id_empresa": uuid.uuid4(), "empresa_nombre": "Empresa", "id_norma": uuid.uuid4(),
                "norma_codigo": "ISO-14001", "norma_nombre": "Ambiental", "norma_version": "2015", "fecha": None,
            }])
        if "SELECT * FROM candidatos WHERE id_usuario" in sql:
            return ResultadoFalso([{
                "id_usuario": ID_AUDITOR, "nombre": "Leonel", "competencia_norma": self.competencia,
                "conflicto_interes": self.conflicto, "ya_asignado": False,
            }])
        if "FROM competencia_auditor ca WHERE ca.id_usuario" in sql:
            return ResultadoFalso([])  # sin competencias en la norma
        if sql.startswith("INSERT INTO auditores_solicitud"):
            return ResultadoFalso([{
                "id": uuid.uuid4(), "id_solicitud": ID_SOLICITUD, "id_auditor": ID_AUDITOR,
                "especialidad": params["especialidad"], "declaracion": True,
                "fecha_inicio_planificada": None, "fecha_fin_planificada": None, "estado_asignacion": "Agendada",
            }])
        if sql.startswith("INSERT INTO historial_asignacion_auditor"):
            return ResultadoFalso([])
        if sql.startswith("SELECT nombre, correo FROM usuario"):
            return ResultadoFalso([{"nombre": "Leonel", "correo": "l@x.co"}])
        raise AssertionError("Consulta inesperada: " + sql[:160])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    def historial(self):
        return [p for sql, p in self.sentencias if sql.startswith("INSERT INTO historial_asignacion_auditor")]


async def _post(db, usuario, cuerpo):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: usuario
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await cliente.post("/asignacion-auditores/", json=cuerpo)
    finally:
        app.dependency_overrides.clear()


def _cuerpo(**extra):
    return {"id_solicitud": str(ID_SOLICITUD), "id_auditor": str(ID_AUDITOR), "rol_auditor": "Observador", **extra}


COORDINADOR = {"id_usuario": str(ID_COORDINADOR), "role_name": "Coordinador"}


async def test_sin_forzar_sigue_el_error_de_elegibilidad_con_razones():
    db = SesionAsignacion(competencia=False)
    r = await _post(db, COORDINADOR, _cuerpo())
    assert r.status_code == 409
    assert "No tiene ninguna competencia registrada en la norma ISO-14001" in r.json()["detail"]
    assert db.commits == 0


async def test_coordinador_fuerza_con_justificacion_y_queda_registrado():
    db = SesionAsignacion(competencia=False)
    r = await _post(db, COORDINADOR, _cuerpo(forzar=True, justificacion="Único auditor disponible en la región"))
    assert r.status_code == 200, r.text
    assert r.json()["forzado"] is True
    assert db.commits == 1
    (registro,) = db.historial()
    assert registro["id_usuario"] == str(ID_COORDINADOR)
    assert registro["origen"] == "Coordinador"
    assert "No tiene ninguna competencia registrada en la norma ISO-14001" in registro["motivo"]
    assert "Único auditor disponible en la región" in registro["motivo"]


@pytest.mark.parametrize("justificacion", [None, "", "corta"])
async def test_forzar_sin_justificacion_responde_422(justificacion):
    db = SesionAsignacion(competencia=False)
    r = await _post(db, COORDINADOR, _cuerpo(forzar=True, justificacion=justificacion))
    assert r.status_code == 422
    assert db.sentencias == []


async def test_auxiliar_sin_permiso_delegado_no_puede_forzar(monkeypatch):
    async def sin_permiso(session, id_usuario, codigo):
        assert codigo == "SOL-048"
        return False

    monkeypatch.setattr(asignacion_router, "auxiliar_tiene_permiso", sin_permiso)
    db = SesionAsignacion(competencia=False)
    r = await _post(db, {"id_usuario": str(uuid.uuid4()), "role_name": "Auxiliar"},
                    _cuerpo(forzar=True, justificacion="Justificación suficientemente larga"))
    assert r.status_code == 403
    assert db.sentencias == []


async def test_auxiliar_con_permiso_delegado_puede_forzar(monkeypatch):
    usos = []

    async def con_permiso(session, id_usuario, codigo):
        return True

    async def anotar(session, id_usuario, codigo, detalle=None, id_aprobacion=None):
        usos.append(codigo)

    monkeypatch.setattr(asignacion_router, "auxiliar_tiene_permiso", con_permiso)
    monkeypatch.setattr(asignacion_router, "registrar_uso", anotar)
    db = SesionAsignacion(competencia=False)
    r = await _post(db, {"id_usuario": str(uuid.uuid4()), "role_name": "Auxiliar"},
                    _cuerpo(forzar=True, justificacion="Justificación suficientemente larga"))
    assert r.status_code == 200, r.text
    assert db.historial()[0]["origen"].startswith("Auxiliar")
    assert usos == ["SOL-048"]


async def test_conflicto_de_interes_no_se_puede_forzar():
    db = SesionAsignacion(competencia=True, conflicto=True)
    r = await _post(db, COORDINADOR, _cuerpo(forzar=True, justificacion="Justificación suficientemente larga"))
    assert r.status_code == 409
    assert "conflicto de interés" in r.json()["detail"]
    assert db.commits == 0 and db.historial() == []


async def test_elegibilidad_informa_razones_y_si_es_forzable():
    from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService

    sin_competencia = await AsignacionAuditorService(SesionAsignacion(competencia=False)).elegibilidad(ID_SOLICITUD, ID_AUDITOR)
    assert sin_competencia["forzable"] is True and sin_competencia["motivos"]
    con_conflicto = await AsignacionAuditorService(SesionAsignacion(competencia=True, conflicto=True)).elegibilidad(ID_SOLICITUD, ID_AUDITOR)
    assert con_conflicto["forzable"] is False and "imparcialidad" in con_conflicto["bloqueante"]
