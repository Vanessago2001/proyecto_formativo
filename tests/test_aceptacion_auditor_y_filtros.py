"""Regresión: flujo de aceptación del auditor y filtros de candidatos.

Cubre las correcciones de la verificación del 13/11:

* Banco de auditores: un borrador no se revisa, el mensaje de "faltan
  elementos" es legible, la aprobación/rechazo deja fecha y revisor, y el
  Auxiliar necesita el permiso delegado (AUD-013/014/030).
* Rechazar un documento o una competencia de una postulación ya cerrada no le
  quita el estado Activo a un auditor aprobado.
* GET /auditores/registro/{id} no crea filas y solo una cuenta Auditor puede
  tener postulación.
* Conflictos: tipo inválido -> 422; los declarados después del registro
  bloquean la asignación; el detalle del banco muestra todos con empresa.
* Agenda: la disponibilidad extraordinaria cubre todo su rango de fechas.
"""

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.database import get_db
from core.security import get_current_user
from modules.administrar_auditores import administrar_auditores_router as banco_router
from modules.administrar_auditores.administrar_auditores_service import (
    AdministrarAuditoresService,
)
from modules.asignacion_auditores.asignacion_service import CTE_AUDITORES
from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

RAIZ = Path(__file__).resolve().parents[1]
ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_POSTULACION = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_ACTOR = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _sql(statement) -> str:
    return " ".join(str(statement).split())


# ---------------------------------------------------------------------------
# cambiar_estado
# ---------------------------------------------------------------------------
class SesionPostulacion:
    def __init__(self, estado="Enviado", docs_pendientes=0, comp_pendientes=0, competencias=None):
        self.estado = estado
        self.docs_pendientes = docs_pendientes
        self.comp_pendientes = comp_pendientes
        # Por defecto, una competencia validada y vigente.
        self.competencias = competencias if competencias is not None else [
            {"tipo_competencia": "ISO 9001", "estado_validacion": "Validado",
             "es_vigente": True, "fecha_fin": None},
        ]
        self.sentencias: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = _sql(statement)
        params = params or {}
        self.sentencias.append((sql, params))
        if sql.startswith("SELECT pa.id_postulacion") or "FROM postulacion_auditor pa INNER JOIN usuario" in sql:
            return ResultadoFalso([{
                "id_postulacion": ID_POSTULACION, "id_usuario": ID_USUARIO,
                "estado": self.estado, "observaciones_tecnicas": "",
                "nombre": "Auditor", "correo": "a@x.co",
            }])
        if "FROM documento_auditor" in sql:
            return ResultadoFalso(escalar=self.docs_pendientes)
        if "FROM competencia_auditor" in sql and "tipo_competencia" in sql:
            return ResultadoFalso(self.competencias)
        if "FROM competencia_auditor" in sql:
            return ResultadoFalso(escalar=self.comp_pendientes)
        if sql.startswith("UPDATE postulacion_auditor"):
            self.estado = params["nuevo_estado"]
            return ResultadoFalso([{
                "id_postulacion": ID_POSTULACION, "id_usuario": ID_USUARIO,
                "estado": params["nuevo_estado"], "observaciones_tecnicas": params["observaciones"],
                "fecha_revision": None,
            }])
        return ResultadoFalso()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


async def _cambiar(sesion, nuevo, obs=""):
    return await AdministrarAuditoresService(sesion).cambiar_estado(
        id_postulacion=ID_POSTULACION, nuevo_estado=nuevo,
        observaciones=obs, id_usuario_actor=ID_ACTOR,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("nuevo", ["En Revisión", "Correcciones", "Aprobado", "Rechazado"])
async def test_un_borrador_no_se_revisa_ni_aprueba(nuevo):
    sesion = SesionPostulacion(estado="Borrador")
    with pytest.raises(HTTPException) as error:
        # Aun sin motivo de rechazo, un borrador responde 409 (no 422).
        await _cambiar(sesion, nuevo)
    assert error.value.status_code == 409
    assert not any(sql.startswith("UPDATE") for sql, _ in sesion.sentencias)


@pytest.mark.asyncio
async def test_aprobar_con_pendientes_explica_que_falta():
    sesion = SesionPostulacion(docs_pendientes=1, comp_pendientes=2)
    with pytest.raises(HTTPException) as error:
        await _cambiar(sesion, "Aprobado")
    assert error.value.status_code == 400
    # Antes el join se aplicaba al literal y el mensaje salía revuelto.
    assert error.value.detail == (
        "No se puede aprobar la postulacion. Faltan elementos validados o "
        "aprobados: documentos adjuntos, competencias."
    )


@pytest.mark.asyncio
async def test_aprobar_registra_revisor_y_activa_al_auditor():
    sesion = SesionPostulacion()
    respuesta = await _cambiar(sesion, "Aprobado", "ok")
    assert respuesta["estado_nuevo"] == "Aprobado"
    update = next(p for sql, p in sesion.sentencias if sql.startswith("UPDATE postulacion_auditor"))
    sql_update = next(sql for sql, _ in sesion.sentencias if sql.startswith("UPDATE postulacion_auditor"))
    assert update["id_usuario_revisor"] == ID_ACTOR
    assert "fecha_aprobacion" in sql_update and "motivo_rechazo" in sql_update
    assert any("SET estado_auditor = 'Activo'" in sql for sql, _ in sesion.sentencias)


# ---------------------------------------------------------------------------
# Rechazo de documento: no degrada a un auditor aprobado
# ---------------------------------------------------------------------------
class SesionDocumento:
    def __init__(self, estado_postulacion):
        self.estado_postulacion = estado_postulacion
        self.estado_auditor = "Activo"

    async def execute(self, statement, params=None):
        sql = _sql(statement)
        if sql.startswith("SELECT id_documento"):
            return ResultadoFalso([{
                "id_documento": uuid.uuid4(), "id_postulacion": ID_POSTULACION,
                "id_usuario": ID_USUARIO, "estado_revision": "Pendiente",
                "tipo_documento": "Soporte", "nombre_archivo": "x.pdf",
            }])
        if sql.startswith("UPDATE documento_auditor"):
            return ResultadoFalso([{"id_documento": uuid.uuid4(), "estado_revision": "Rechazado",
                                    "observacion_revision": "x", "fecha_revision": None}])
        if sql.startswith("UPDATE postulacion_auditor"):
            if self.estado_postulacion in ("Aprobado", "Rechazado", "Cancelado"):
                return ResultadoFalso([])
            self.estado_postulacion = "Correcciones"
            return ResultadoFalso([{"id_postulacion": ID_POSTULACION}])
        if sql.startswith("UPDATE usuario"):
            self.estado_auditor = "Postulante"
        return ResultadoFalso()

    async def commit(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("estado, esperado", [
    ("Rechazado", "Activo"),      # postulación antigua cerrada: no toca al auditor
    ("Aprobado", "Activo"),
    ("En Revisión", "Postulante"),  # postulación abierta: vuelve a Correcciones
])
async def test_rechazar_documento_solo_degrada_si_la_postulacion_vuelve_a_correcciones(estado, esperado):
    sesion = SesionDocumento(estado)
    await AdministrarAuditoresService(sesion).revisar_documento(
        id_documento=uuid.uuid4(), estado_revision="Rechazado",
        observacion="falta firma", id_usuario_actor=ID_ACTOR,
    )
    assert sesion.estado_auditor == esperado


# ---------------------------------------------------------------------------
# Permisos del banco: Auxiliar solo con permiso delegado
# ---------------------------------------------------------------------------
@pytest.fixture
def cliente_banco(monkeypatch):
    app = FastAPI()
    app.include_router(banco_router.router)
    llamadas = []

    async def _db():
        yield object()

    async def _cambiar_estado(self, **kwargs):
        llamadas.append(kwargs["nuevo_estado"])
        return {"estado_nuevo": kwargs["nuevo_estado"]}

    monkeypatch.setattr(AdministrarAuditoresService, "cambiar_estado", _cambiar_estado)
    app.dependency_overrides[get_db] = _db

    def con_rol(rol, permiso=False):
        async def _usuario():
            return {"id_usuario": str(ID_ACTOR), "role_name": rol}

        async def _permiso(db, usuario, codigo, detalle=None):
            return permiso

        import modules.permisos_auxiliar.permisos_auxiliar_service as permisos
        monkeypatch.setattr(permisos, "usar_permiso_delegado", _permiso)
        app.dependency_overrides[get_current_user] = _usuario
        return TestClient(app)

    return con_rol, llamadas


@pytest.mark.parametrize("accion", ["aprobar", "rechazar"])
def test_auxiliar_sin_permiso_delegado_no_aprueba_ni_rechaza(cliente_banco, accion):
    con_rol, llamadas = cliente_banco
    r = con_rol("Auxiliar").patch(f"/administradores/auditores/solicitudes/{ID_POSTULACION}/{accion}", json={})
    assert r.status_code == 403
    assert "AUD-01" in r.json()["detail"]
    assert llamadas == []


def test_auxiliar_con_permiso_delegado_aprueba(cliente_banco):
    con_rol, llamadas = cliente_banco
    r = con_rol("Auxiliar", permiso=True).patch(f"/administradores/auditores/solicitudes/{ID_POSTULACION}/aprobar", json={})
    assert r.status_code == 200
    assert llamadas == ["Aprobado"]


def test_coordinador_aprueba_sin_permiso_delegado(cliente_banco):
    con_rol, llamadas = cliente_banco
    r = con_rol("Coordinador").post(
        f"/administradores/auditores/solicitudes/{ID_POSTULACION}/estado",
        json={"nuevo_estado": "Rechazado"},
    )
    assert r.status_code == 200
    assert llamadas == ["Rechazado"]


def test_auxiliar_puede_pasar_a_revision_sin_permiso(cliente_banco):
    con_rol, llamadas = cliente_banco
    r = con_rol("Auxiliar").patch(f"/administradores/auditores/solicitudes/{ID_POSTULACION}/revision", json={})
    assert r.status_code == 200
    assert llamadas == ["En Revisión"]


# ---------------------------------------------------------------------------
# Registro: una lectura no crea filas; solo rol Auditor tiene postulación
# ---------------------------------------------------------------------------
class SesionRegistro:
    def __init__(self, rol="Auditor", postulacion=None):
        self.rol = rol
        self.postulacion = postulacion
        self.inserts = 0

    async def execute(self, statement, params=None):
        sql = _sql(statement)
        if sql.startswith("INSERT INTO postulacion_auditor"):
            self.inserts += 1
            return ResultadoFalso([{"id_postulacion": ID_POSTULACION, "id_usuario": ID_USUARIO,
                                    "estado": "Borrador", "fecha_postulacion": None,
                                    "fecha_revision": None, "observaciones_tecnicas": ""}])
        if "r.nombre AS rol" in sql:
            return ResultadoFalso([{"rol": self.rol}])
        if "FROM usuario" in sql:
            return ResultadoFalso([{"id_usuario": ID_USUARIO, "nombre": "X", "tipo_doc": "CC",
                                    "num_doc": "1", "correo": "x@x.co", "estado": "Activo",
                                    "estado_auditor": "Postulante"}])
        if "FROM postulacion_auditor" in sql:
            return ResultadoFalso([self.postulacion] if self.postulacion else [])
        return ResultadoFalso()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_consultar_registro_sin_postulacion_no_crea_borrador():
    sesion = SesionRegistro()
    with pytest.raises(HTTPException) as error:
        await AuditorService(sesion).obtener_borrador(ID_USUARIO)
    assert error.value.status_code == 404
    assert sesion.inserts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["Coordinador", "Auxiliar", "Comité", "Empresa", "Instructor"])
async def test_solo_rol_auditor_inicia_postulacion(rol):
    sesion = SesionRegistro(rol=rol)
    with pytest.raises(HTTPException) as error:
        await AuditorService(sesion).crear_nueva_postulacion(ID_USUARIO)
    assert error.value.status_code == 403
    assert sesion.inserts == 0


@pytest.mark.asyncio
async def test_auditor_inicia_su_primera_postulacion():
    sesion = SesionRegistro(rol="Auditor")
    respuesta = await AuditorService(sesion).crear_nueva_postulacion(ID_USUARIO)
    assert respuesta["estado"] == "Borrador"
    assert sesion.inserts == 1


# ---------------------------------------------------------------------------
# Conflictos de interés
# ---------------------------------------------------------------------------
def test_tipo_de_conflicto_invalido_es_422_y_no_500():
    with pytest.raises(ValidationError):
        ConflictoInteresCrear(id_empresa=uuid.uuid4(), tipo_conflicto="Amistad", descripcion="x")


def test_tipo_de_conflicto_se_normaliza_al_valor_de_la_base():
    datos = ConflictoInteresCrear(id_empresa=uuid.uuid4(), tipo_conflicto=" asesoria previa ", descripcion="x")
    assert datos.tipo_conflicto == "Asesoría Previa"


def test_conflicto_de_interes_bloquea_sin_importar_la_postulacion():
    sql = _sql(CTE_AUDITORES)
    bloque = sql[sql.index("FROM conflicto_interes ci"):sql.index("AS conflicto_interes")]
    # Los conflictos declarados después del registro quedan sin id_postulacion.
    assert "id_postulacion" not in bloque
    assert "ci.id_empresa = :id_empresa" in bloque


def test_ya_asignado_ignora_mayusculas_y_espacios_del_estado():
    sql = _sql(CTE_AUDITORES)
    bloque = sql[sql.index("FROM auditores_solicitud a"):sql.index("AS ya_asignado")]
    assert "UPPER(TRIM(COALESCE(a.estado_asignacion" in bloque


@pytest.mark.asyncio
async def test_declarar_conflicto_aprobado_queda_enlazado_a_la_postulacion_aprobada(monkeypatch):
    insertados = []

    class Sesion:
        async def execute(self, statement, params=None):
            sql = _sql(statement)
            if sql.startswith("INSERT INTO conflicto_interes"):
                insertados.append(params)
                return ResultadoFalso([{"id_conflicto": uuid.uuid4()}])
            if "FROM usuario" in sql:
                return ResultadoFalso(
                    [{"id_usuario": ID_USUARIO, "estado": "Activo", "estado_auditor": "Activo"}],
                    escalar=ID_USUARIO,
                )
            return ResultadoFalso()

        async def commit(self):
            return None

    async def _aprobada(self, id_usuario):
        return ID_POSTULACION

    monkeypatch.setattr(AuditorService, "_obtener_postulacion_del_conflicto", _aprobada)
    datos = ConflictoInteresCrear(id_empresa=uuid.uuid4(), tipo_conflicto="Exempleado", descripcion="x")
    await AuditorService(Sesion()).declarar_conflicto(ID_USUARIO, datos)
    await AuditorService(Sesion()).crear_conflicto_administrador(ID_USUARIO, datos)
    assert [p["id_postulacion"] for p in insertados] == [ID_POSTULACION, ID_POSTULACION]


def test_detalle_del_banco_lista_todos_los_conflictos_con_empresa():
    fuente = (RAIZ / "modules/administrar_auditores/administrar_auditores_service.py").read_text(encoding="utf-8")
    assert "e.nombre AS empresa_nombre" in fuente
    assert "conflictos = [conflicto] if conflicto else []" not in fuente
    pagina = (RAIZ / "static/banco_auditores_solicitud.html").read_text(encoding="utf-8")
    assert "item.empresa_nombre" in pagina
    assert "formatDate(item.fecha_declaracion)" in pagina


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------
def test_banco_carga_una_vez_y_filtra_cancelado():
    pagina = (RAIZ / "static/banco_auditores.html").read_text(encoding="utf-8")
    assert '<option value="Cancelado">' in pagina
    # Un solo listener de "change" sobre el select de estado y uno en Limpiar.
    assert pagina.count('getElementById("estado")?.addEventListener("change"') == 1
    assert "?estado=" not in pagina


def test_formulario_auditor_declara_las_marcas_de_rechazo():
    pagina = (RAIZ / "static/auditor.html").read_text(encoding="utf-8")
    assert "let tieneRechazoDocumentos = false;" in pagina
    assert "let tieneRechazoCompetencia = false;" in pagina


def test_estado_de_registro_avisa_del_borrador_pendiente():
    pagina = (RAIZ / "static/consultar_estado_registro.html").read_text(encoding="utf-8")
    assert "borrador_pendiente" in pagina
    fuente = (RAIZ / "modules/auditores/auditor_service.py").read_text(encoding="utf-8")
    assert '"borrador_pendiente": borrador_pendiente' in fuente


# ---------------------------------------------------------------------------
# Agenda y búsqueda SOL-041
# ---------------------------------------------------------------------------
def test_disponibilidad_extra_no_se_filtra_por_dia_de_la_semana():
    fuente = (RAIZ / "modules/agenda_auditor/agenda_service.py").read_text(encoding="utf-8")
    assert fuente.count(
        "OR LOWER(TRIM(COALESCE(da.tipo_registro, ''))) IN ('disponibilidad extra', 'disponibilidad_extra')"
    ) == 2


def test_busqueda_sol041_reconoce_los_tipos_reales_de_disponibilidad():
    fuente = (RAIZ / "modules/solicitudes/auditor_service.py").read_text(encoding="utf-8")
    assert "d.tipo_registro = 'Disponibilidad'" not in fuente
    assert "'horario semanal', 'disponibilidad extra'" in fuente
    assert "c.fecha_fin >= CURRENT_DATE" in fuente
