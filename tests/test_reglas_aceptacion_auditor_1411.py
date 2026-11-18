"""Reglas de negocio del 14/11 sobre el flujo de aceptación de auditores.

1. Aprobar un auditor sin competencias validadas exige confirmación explícita
   y justificación (409 sin la marca; queda registrado en el historial).
3. Rechazar una postulación exige un motivo de al menos 10 caracteres y el
   auditor lo ve en Consultar estado de registro y en su notificación.
4. Auditores registrados distingue postulantes / aprobados / rechazados y
   ofrece "Revisar solicitud".
5. Un conflicto de interés activo con la empresa marca las asignaciones
   existentes, avisa al Coordinador y permite retirar al auditor aunque haya
   visita programada; las nuevas asignaciones siguen bloqueadas.
"""

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.administrar_auditores import administrar_auditores_router as banco_router
from modules.administrar_auditores.administrar_auditores_service import (
    AdministrarAuditoresService,
    competencias_vigentes_y_faltantes,
)
from modules.asignacion_auditores import asignacion_router
from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from modules.auditores_registrados.auditores_registrados_service import (
    clasificar_estado_registro,
)
from tests.fake_db import ResultadoFalso
from tests.permisos_aux import con_permisos
from tests.test_aceptacion_auditor_y_filtros import (
    ID_ACTOR,
    ID_POSTULACION,
    ID_USUARIO,
    SesionPostulacion,
    _cambiar,
    _sql,
)

RAIZ = Path(__file__).resolve().parents[1]
HOY = date.today()


def _competencia(estado="Validado", vigente=True, fecha_fin=None, nombre="ISO 9001"):
    return {"tipo_competencia": nombre, "estado_validacion": estado,
            "es_vigente": vigente, "fecha_fin": fecha_fin}


# ---------------------------------------------------------------------------
# 1. Aprobar sin competencias validadas
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aprobar_sin_ninguna_competencia_pide_confirmacion():
    sesion = SesionPostulacion(competencias=[])
    with pytest.raises(HTTPException) as error:
        await _cambiar(sesion, "Aprobado")
    assert error.value.status_code == 409
    assert "no registró ninguna" in error.value.detail
    assert "no será elegible para asignaciones" in error.value.detail
    assert error.value.headers == {"X-Requiere-Confirmacion": "sin-competencias"}
    assert not any(sql.startswith("UPDATE") for sql, _ in sesion.sentencias)


@pytest.mark.asyncio
async def test_aprobar_con_competencia_rechazada_lista_cual_falta():
    sesion = SesionPostulacion(competencias=[_competencia("Rechazado", nombre="ISO 14001")])
    with pytest.raises(HTTPException) as error:
        await _cambiar(sesion, "Aprobado")
    assert error.value.status_code == 409
    assert "ISO 14001 (rechazado)" in error.value.detail


def test_competencia_vencida_no_cuenta_como_vigente():
    vigentes, faltantes = competencias_vigentes_y_faltantes(
        [_competencia(fecha_fin=HOY - timedelta(days=1)), _competencia(vigente=False, nombre="B")], HOY
    )
    assert vigentes == []
    assert faltantes == ["ISO 9001 (vencida o no vigente)", "B (vencida o no vigente)"]


@pytest.mark.asyncio
async def test_competencias_sin_revisar_siguen_bloqueando_con_400():
    sesion = SesionPostulacion(comp_pendientes=1, competencias=[])
    with pytest.raises(HTTPException) as error:
        await _cambiar(sesion, "Aprobado")
    assert error.value.status_code == 400
    assert "competencias" in error.value.detail


@pytest.mark.asyncio
async def test_documentos_pendientes_siguen_bloqueando_aunque_se_confirme():
    sesion = SesionPostulacion(docs_pendientes=1, competencias=[])
    with pytest.raises(HTTPException) as error:
        await AdministrarAuditoresService(sesion).cambiar_estado(
            id_postulacion=ID_POSTULACION, nuevo_estado="Aprobado", observaciones="",
            id_usuario_actor=ID_ACTOR, confirmar_sin_competencias=True,
            justificacion_sin_competencias="Experiencia comprobada en campo",
        )
    assert error.value.status_code == 400
    assert "documentos adjuntos" in error.value.detail


@pytest.mark.asyncio
async def test_confirmar_sin_justificacion_es_422():
    sesion = SesionPostulacion(competencias=[])
    with pytest.raises(HTTPException) as error:
        await AdministrarAuditoresService(sesion).cambiar_estado(
            id_postulacion=ID_POSTULACION, nuevo_estado="Aprobado", observaciones="",
            id_usuario_actor=ID_ACTOR, confirmar_sin_competencias=True,
            justificacion_sin_competencias="   corta ",
        )
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_confirmar_aprueba_y_registra_quien_y_justificacion_en_historial():
    sesion = SesionPostulacion(competencias=[])
    respuesta = await AdministrarAuditoresService(sesion).cambiar_estado(
        id_postulacion=ID_POSTULACION, nuevo_estado="Aprobado", observaciones="",
        id_usuario_actor=ID_ACTOR, confirmar_sin_competencias=True,
        justificacion_sin_competencias="Experiencia comprobada en campo",
        rol_confirmacion="Coordinador",
    )
    assert respuesta["estado_nuevo"] == "Aprobado"
    historial = next(p for sql, p in sesion.sentencias if sql.startswith("INSERT INTO historial_postulacion_auditor"))
    assert historial["id_usuario_administrador"] == ID_ACTOR
    assert "confirmado por Coordinador" in historial["observaciones"]
    assert "Justificación: Experiencia comprobada en campo" in historial["observaciones"]


@pytest.fixture
def cliente_banco(monkeypatch):
    app = FastAPI()
    app.include_router(banco_router.router)
    llamadas = []

    async def _db():
        yield object()

    async def _cambiar_estado(self, **kwargs):
        llamadas.append(kwargs)
        return {"estado_nuevo": kwargs["nuevo_estado"]}

    monkeypatch.setattr(AdministrarAuditoresService, "cambiar_estado", _cambiar_estado)
    app.dependency_overrides[get_db] = _db

    def con_rol(rol, permiso=False):
        async def _usuario():
            usuario = {"id_usuario": str(ID_ACTOR), "role_name": rol}
            # Permiso delegado simulado (regla_auxiliar): todo el catálogo.
            return con_permisos(usuario) if permiso else usuario

        async def _permiso(db, usuario, codigo, detalle=None):
            return permiso

        import modules.permisos_auxiliar.permisos_auxiliar_service as permisos
        monkeypatch.setattr(permisos, "usar_permiso_delegado", _permiso)
        app.dependency_overrides[get_current_user] = _usuario
        return TestClient(app)

    return con_rol, llamadas


def test_router_pasa_la_marca_y_el_rol_que_confirma(cliente_banco):
    con_rol, llamadas = cliente_banco
    cuerpo = {"confirmar_sin_competencias": True, "justificacion_sin_competencias": "Experiencia comprobada"}
    assert con_rol("Coordinador").patch(
        f"/administradores/auditores/solicitudes/{ID_POSTULACION}/aprobar", json=cuerpo).status_code == 200
    assert con_rol("Auxiliar", permiso=True).patch(
        f"/administradores/auditores/solicitudes/{ID_POSTULACION}/aprobar", json=cuerpo).status_code == 200
    assert llamadas[0]["confirmar_sin_competencias"] is True
    assert llamadas[0]["rol_confirmacion"] == "Coordinador"
    assert "AUD-013" in llamadas[1]["rol_confirmacion"]


def test_auxiliar_sin_aud013_no_puede_confirmar(cliente_banco):
    con_rol, llamadas = cliente_banco
    r = con_rol("Auxiliar").patch(
        f"/administradores/auditores/solicitudes/{ID_POSTULACION}/aprobar",
        json={"confirmar_sin_competencias": True, "justificacion_sin_competencias": "Experiencia comprobada"},
    )
    assert r.status_code == 403
    assert llamadas == []


def test_marca_de_confirmacion_debe_ser_booleano_verdadero(cliente_banco):
    con_rol, llamadas = cliente_banco
    con_rol("Coordinador").patch(
        f"/administradores/auditores/solicitudes/{ID_POSTULACION}/aprobar",
        json={"confirmar_sin_competencias": "si"},
    )
    assert llamadas[0]["confirmar_sin_competencias"] is False


def test_pantalla_banco_muestra_modal_de_confirmacion():
    pagina = (RAIZ / "static/banco_auditores.html").read_text(encoding="utf-8")
    assert 'id="sinCompetenciasModal"' in pagina
    assert "Sí, aprobar de todas formas" in pagina
    assert 'X-Requiere-Confirmacion' in pagina
    assert "confirmar_sin_competencias: true" in pagina


# ---------------------------------------------------------------------------
# 3. Motivo de rechazo obligatorio
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("motivo", ["", "          ", "corto", "  123456789  "])
async def test_rechazar_sin_motivo_suficiente_es_422(motivo):
    sesion = SesionPostulacion()
    with pytest.raises(HTTPException) as error:
        await _cambiar(sesion, "Rechazado", motivo)
    assert error.value.status_code == 422
    assert not any(sql.startswith("UPDATE") for sql, _ in sesion.sentencias)


@pytest.mark.asyncio
async def test_rechazar_guarda_motivo_y_lo_notifica_al_auditor():
    sesion = SesionPostulacion()
    await _cambiar(sesion, "Rechazado", "  Falta experiencia en auditoría  ")
    update = next(p for sql, p in sesion.sentencias if sql.startswith("UPDATE postulacion_auditor"))
    assert update["observaciones"] == "Falta experiencia en auditoría"
    notificacion = next(p for sql, p in sesion.sentencias if sql.startswith("INSERT INTO notificacion"))
    assert "Motivo del rechazo: Falta experiencia en auditoría" in notificacion["mensaje"]


@pytest.mark.asyncio
async def test_notificacion_con_motivo_largo_no_supera_255():
    sesion = SesionPostulacion()
    await _cambiar(sesion, "Rechazado", "x" * 600)
    notificacion = next(p for sql, p in sesion.sentencias if sql.startswith("INSERT INTO notificacion"))
    assert len(notificacion["mensaje"]) <= 255


def test_estado_de_registro_lee_el_motivo_de_la_postulacion():
    fuente = (RAIZ / "modules/auditores/auditor_service.py").read_text(encoding="utf-8")
    assert "p.motivo_rechazo" in fuente
    pagina = (RAIZ / "static/consultar_estado_registro.html").read_text(encoding="utf-8")
    assert "Motivo del rechazo" in pagina
    banco = (RAIZ / "static/banco_auditores.html").read_text(encoding="utf-8")
    assert 'id="modalObservacionesError"' in banco
    assert 'accion === "rechazar" && observaciones.length < 10' in banco


# ---------------------------------------------------------------------------
# 4. Auditores registrados: estado del auditor y "Revisar solicitud"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("estado_auditor, postulacion, esperado", [
    ("Activo", "Aprobado", "Aprobado"),
    ("Postulante", "Enviado", "Postulante"),
    ("Postulante", "Correcciones", "Postulante"),
    ("Postulante", "Borrador", "Postulante"),
    ("Postulante", "Rechazado", "Rechazado"),
    ("Postulante", "Cancelado", "Cancelado"),
    ("Postulante", None, "Sin postulación"),
])
def test_clasificar_estado_registro(estado_auditor, postulacion, esperado):
    assert clasificar_estado_registro(estado_auditor, postulacion)["estado_registro"] == esperado


def test_pantalla_auditores_registrados_tiene_filtro_y_revisar_solicitud():
    pagina = (RAIZ / "static/auditores_registrados.html").read_text(encoding="utf-8")
    assert 'id="filtroRegistro"' in pagina
    assert '<label for="filtroEstado">Cuenta</label>' in pagina
    assert "/banco-auditores/solicitud/${encodeURIComponent(auditor.id_postulacion)}" in pagina
    assert "Revisar solicitud" in pagina and "disabled" in pagina


# ---------------------------------------------------------------------------
# 5. Conflicto de interés sobre asignaciones existentes
# ---------------------------------------------------------------------------
ID_EMPRESA = uuid.uuid4()
ID_ASIGNACION = uuid.uuid4()
ID_SOLICITUD = uuid.uuid4()
ID_PROGRAMACION = uuid.uuid4()


class SesionConflicto:
    """Doble mínimo para declarar un conflicto con asignaciones activas."""

    def __init__(self, afectadas):
        self.afectadas = afectadas
        self.sentencias = []

    async def execute(self, statement, params=None):
        sql = _sql(statement)
        self.sentencias.append((sql, params or {}))
        if sql.startswith("INSERT INTO conflicto_interes"):
            return ResultadoFalso([{"id_conflicto": uuid.uuid4()}])
        if "FROM auditores_solicitud a" in sql and "s.id_empresa = :id_empresa" in sql:
            return ResultadoFalso(self.afectadas)
        if "FROM usuario" in sql and "rol" not in sql:
            return ResultadoFalso([{"id_usuario": ID_USUARIO, "estado": "Activo", "estado_auditor": "Activo"}],
                                  escalar=ID_USUARIO)
        return ResultadoFalso()

    async def commit(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["declarar_conflicto", "crear_conflicto_administrador"])
async def test_declarar_conflicto_avisa_al_coordinador_de_asignaciones_activas(monkeypatch, metodo):
    async def _postulacion(self, id_usuario):
        return ID_POSTULACION

    monkeypatch.setattr(AuditorService, "_obtener_postulacion_del_conflicto", _postulacion)
    sesion = SesionConflicto([{
        "id": ID_ASIGNACION, "id_solicitud": ID_SOLICITUD, "numero_radicado": "SOL-2026-0001",
        "especialidad": "Auditor líder", "auditor_nombre": "Leonel", "empresa_nombre": "Cafe del Eje",
    }])
    datos = ConflictoInteresCrear(id_empresa=ID_EMPRESA, tipo_conflicto="Exempleado", descripcion="x")
    respuesta = await getattr(AuditorService(sesion), metodo)(ID_USUARIO, datos)
    assert respuesta["asignaciones_afectadas"][0]["numero_radicado"] == "SOL-2026-0001"
    assert "SOL-2026-0001" in respuesta["mensaje"]
    sql_aviso, params = next(
        (sql, p) for sql, p in sesion.sentencias if sql.startswith("INSERT INTO notificacion")
    )
    assert "LOWER(TRIM(r.nombre)) = 'coordinador'" in sql_aviso
    assert "SOL-2026-0001" in params["mensaje"] and "Cafe del Eje" in params["mensaje"]
    assert len(params["mensaje"]) <= 255


@pytest.mark.asyncio
async def test_declarar_conflicto_sin_asignaciones_no_notifica(monkeypatch):
    async def _postulacion(self, id_usuario):
        return ID_POSTULACION

    monkeypatch.setattr(AuditorService, "_obtener_postulacion_del_conflicto", _postulacion)
    sesion = SesionConflicto([])
    datos = ConflictoInteresCrear(id_empresa=ID_EMPRESA, tipo_conflicto="Exempleado", descripcion="x")
    respuesta = await AuditorService(sesion).declarar_conflicto(ID_USUARIO, datos)
    assert respuesta["asignaciones_afectadas"] == []
    assert not any(sql.startswith("INSERT INTO notificacion") for sql, _ in sesion.sentencias)


def test_listado_de_asignaciones_marca_el_conflicto():
    fuente = (RAIZ / "modules/asignacion_auditores/asignacion_service.py").read_text(encoding="utf-8")
    assert "{SQL_CONFLICTO_ASIGNACION} AS conflicto_interes" in fuente
    # La antigua Asignación de auditores es ahora la etapa "Con auditores"
    # de /solicitudes: el HTML en solicitudes.html y su JS aparte.
    pagina = (RAIZ / "static/solicitudes.html").read_text(encoding="utf-8") + (
        RAIZ / "static/solicitudes-asignacion.js").read_text(encoding="utf-8")
    assert "Conflicto de interés: debe reasignarse" in pagina
    assert "/retirar-por-conflicto" in pagina
    assert 'id="retiroConflictoModal" class="modal-overlay" role="dialog" aria-modal="true"' in pagina


class SesionRetiro:
    """Doble para retirar_por_conflicto: una asignación con visita programada."""

    def __init__(self, conflicto=True, activa=True, visitas=1, restantes=1):
        self.conflicto = conflicto
        self.activa = activa
        self.visitas = visitas
        self.restantes = restantes
        self.sentencias = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = _sql(statement)
        self.sentencias.append((sql, params or {}))
        if "FROM auditores_solicitud a" in sql and "FOR UPDATE OF a" in sql:
            return ResultadoFalso([{
                "id": ID_ASIGNACION, "id_solicitud": ID_SOLICITUD, "id_auditor": ID_USUARIO,
                "estado_asignacion": "Agendada", "numero_radicado": "SOL-2026-0003",
                "empresa_nombre": "Cafe del Eje", "conflicto_interes": self.conflicto,
                "activa": self.activa,
            }])
        if "FROM detalle_programacion_auditor d" in sql:
            return ResultadoFalso([
                {"id_detalle": uuid.uuid4(), "id_programacion": ID_PROGRAMACION, "estado": "Confirmada"}
            ][: self.visitas])
        if sql.startswith("UPDATE disponibilidad_auditor"):
            return ResultadoFalso([{
                "id_disponibilidad": uuid.uuid4(), "id_usuario": ID_USUARIO,
                "fecha_inicio": None, "fecha_fin": None, "motivo": "Visita",
            }])
        if sql.startswith("SELECT COUNT(*) FROM detalle_programacion_auditor"):
            return ResultadoFalso(escalar=self.restantes)
        return ResultadoFalso()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def agenda_simulada(monkeypatch):
    from modules.agenda_auditor.agenda_service import AgendaAuditorService

    eventos = []

    async def _historial(self, fila, accion):
        eventos.append(("historial", accion))

    async def _notificar(self, id_programacion, id_usuario, titulo, mensaje):
        eventos.append(("notificacion", titulo))

    async def _estado(self, id_programacion):
        return "Confirmada"

    monkeypatch.setattr(AgendaAuditorService, "_registrar_historial_disponibilidad", _historial)
    monkeypatch.setattr(AgendaAuditorService, "_crear_notificacion", _notificar)
    monkeypatch.setattr(AgendaAuditorService, "_estado_final_programacion", _estado)
    return eventos


@pytest.mark.asyncio
async def test_retirar_por_conflicto_quita_al_auditor_de_la_visita(agenda_simulada):
    sesion = SesionRetiro()
    respuesta = await AsignacionAuditorService(sesion).retirar_por_conflicto(
        ID_ASIGNACION, {"id_usuario": str(ID_ACTOR)}, "Declarado el 11/11"
    )
    sqls = [sql for sql, _ in sesion.sentencias]
    assert any(sql.startswith("DELETE FROM detalle_programacion_auditor") for sql in sqls)
    assert any(sql.startswith("UPDATE disponibilidad_auditor SET estado = 'Cancelado'") for sql in sqls)
    assert any(sql.startswith("UPDATE programacion_visita") for sql in sqls)
    update = next(p for sql, p in sesion.sentencias if sql.startswith("UPDATE auditores_solicitud"))
    assert update["motivo"] == "Conflicto de interés con Cafe del Eje. Declarado el 11/11"
    assert update["usuario_cancela"] == str(ID_ACTOR)
    historial = [p for sql, p in sesion.sentencias if sql.startswith("INSERT INTO historial_asignacion_auditor")]
    assert historial[0]["accion"] == "RETIRO_POR_CONFLICTO_INTERES"
    assert historial[0]["id_programacion"] == str(ID_PROGRAMACION)
    assert ("historial", "LIBERADA_POR_RETIRO_CONFLICTO") in agenda_simulada
    assert ("notificacion", "Retirado de la auditoría") in agenda_simulada
    assert respuesta["visitas_afectadas"] == 1 and respuesta["bloqueos_liberados"] == 1
    assert sesion.commits == 1


@pytest.mark.asyncio
async def test_retiro_deja_la_visita_sin_auditores_para_reasignar(agenda_simulada):
    sesion = SesionRetiro(restantes=0)
    respuesta = await AsignacionAuditorService(sesion).retirar_por_conflicto(
        ID_ASIGNACION, {"id_usuario": str(ID_ACTOR)}
    )
    assert respuesta["visitas_sin_auditores"] == [str(ID_PROGRAMACION)]
    assert not any(sql.startswith("UPDATE programacion_visita") for sql, _ in sesion.sentencias)
    assert "agregue otro auditor desde Agenda" in respuesta["mensaje"]


@pytest.mark.asyncio
async def test_retiro_sin_visita_registra_historial_y_cancela(agenda_simulada):
    sesion = SesionRetiro(visitas=0)
    await AsignacionAuditorService(sesion).retirar_por_conflicto(ID_ASIGNACION, {"id_usuario": str(ID_ACTOR)})
    historial = [p for sql, p in sesion.sentencias if sql.startswith("INSERT INTO historial_asignacion_auditor")]
    assert len(historial) == 1 and historial[0]["id_programacion"] is None
    assert any(sql.startswith("UPDATE auditores_solicitud") for sql, _ in sesion.sentencias)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"conflicto": False}, {"activa": False}])
async def test_retiro_solo_aplica_a_asignaciones_activas_con_conflicto(agenda_simulada, kwargs):
    sesion = SesionRetiro(**kwargs)
    with pytest.raises(HTTPException) as error:
        await AsignacionAuditorService(sesion).retirar_por_conflicto(ID_ASIGNACION, {"id_usuario": str(ID_ACTOR)})
    assert error.value.status_code == 409
    assert not any(sql.startswith(("UPDATE", "DELETE")) for sql, _ in sesion.sentencias)
    assert sesion.rollbacks == 1


@pytest.mark.parametrize("rol, esperado", [("Coordinador", 200), ("Auxiliar", 403), ("Empresa", 403)])
def test_endpoint_retiro_solo_coordinador(monkeypatch, rol, esperado):
    app = FastAPI()
    app.include_router(asignacion_router.router)

    async def _db():
        yield object()

    async def _usuario():
        return {"id_usuario": str(ID_ACTOR), "role_name": rol}

    async def _retirar(self, id_asignacion, usuario, motivo=None):
        return {"mensaje": "ok", "motivo": motivo}

    monkeypatch.setattr(AsignacionAuditorService, "retirar_por_conflicto", _retirar)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _usuario
    r = TestClient(app).post(f"/asignacion-auditores/{ID_ASIGNACION}/retirar-por-conflicto", json={"motivo": "x"})
    assert r.status_code == esperado


@pytest.mark.asyncio
async def test_nueva_asignacion_con_conflicto_sigue_bloqueada(monkeypatch):
    """5b: el bloqueo de NUEVAS asignaciones ya existía; se confirma."""
    servicio = AsignacionAuditorService(object())

    async def _solicitud(self, id_solicitud):
        return {"id_solicitud": id_solicitud, "id_empresa": ID_EMPRESA, "id_norma": uuid.uuid4()}

    class Fila(dict):
        pass

    async def _ejecutar(statement, params=None):
        return ResultadoFalso([{
            "id_usuario": ID_USUARIO, "nombre": "Leonel", "competencia_norma": True,
            "conflicto_interes": True, "ya_asignado": False,
        }])

    monkeypatch.setattr(AsignacionAuditorService, "obtener_solicitud", _solicitud)
    servicio.db = type("S", (), {"execute": staticmethod(_ejecutar)})()

    async def _motivos(self, id_auditor, solicitud):
        return []

    monkeypatch.setattr(AsignacionAuditorService, "motivos_competencia", _motivos)
    with pytest.raises(HTTPException) as error:
        await servicio.validar_auditor(id_solicitud=uuid.uuid4(), id_auditor=ID_USUARIO, forzar=True)
    assert error.value.status_code == 409
    assert "conflicto de interés" in str(error.value.detail).lower()
