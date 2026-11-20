"""
Imparcialidad del Comité, calificación obligatoria del auditor líder antes de
decidir, vista unificada de expedientes y retiro de "Programaciones futuras".
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import get_current_user
from modules.comite.comite_service import ComiteService
from modules.comite.imparcialidad import MENSAJE_NO_ENCONTRADO, MENSAJES, sql_impedimento

MIEMBRO = {"id_usuario": str(uuid4()), "nombre": "Marta Comité", "role_name": "Comité"}
COORDINADOR = {"id_usuario": str(uuid4()), "nombre": "Coordinación", "role_name": "Coordinador"}


def _resultado(filas=None):
    resultado = MagicMock()
    filas = filas or []
    resultado.mappings.return_value.first.return_value = filas[0] if filas else None
    resultado.mappings.return_value.all.return_value = filas
    resultado.scalar.return_value = None
    return resultado


class BaseComite:
    """Base falsa para el registro de acciones del Comité."""

    def __init__(self, *, impedimento=None, tabla=True, visitas=None, estado="En revision"):
        self.impedimento = impedimento
        self.tabla = tabla
        self.visitas = visitas if visitas is not None else []
        self.estado = estado
        self.sql: list[str] = []
        self.params: list = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, consulta, params=None):
        sql = str(consulta)
        self.sql.append(sql)
        self.params.append(params)
        if "AS impedimento" in sql:
            return _resultado([{"impedimento": self.impedimento}])
        if "to_regclass" in sql:
            return _resultado([{"existe": self.tabla}])
        if "AS evaluaciones" in sql:
            return _resultado(self.visitas)
        if "FROM solicitud" in sql and "FOR UPDATE" in sql:
            return _resultado([{"id_solicitud": uuid4(), "estado": self.estado}])
        if sql.strip().startswith("UPDATE solicitud"):
            return _resultado([{"estado": "Aprobada"}])
        if "INSERT INTO historial_estado" in sql:
            return _resultado()
        if "INSERT INTO comite_accion" in sql:
            return _resultado([{"id_accion": uuid4(), "id_solicitud": uuid4(), "accion": params["accion"],
                                "fecha": datetime.now(timezone.utc)}])
        raise AssertionError(f"Consulta inesperada: {sql[:120]}")

    def hubo(self, texto):
        return any(texto in s for s in self.sql)


def _visita(dia, calificacion=None):
    """Visita con un auditor asignado y, si hay nota, su evaluación (rol único "Auditor")."""
    evaluaciones = [] if calificacion is None else [
        {"id_auditor": str(uuid4()), "nombre": f"Auditor {dia}", "rol": "Auditor", "calificacion": calificacion}
    ]
    return {"id_programacion": uuid4(), "fecha_inicio": datetime(2026, 11, dia, 8),
            "auditores_asignados": 1, "evaluaciones": evaluaciones}


def _payload():
    return {"expediente_id": str(uuid4()), "comentario": "Cumple los requisitos"}


# ---------------------------------------------------------------- regla de imparcialidad (acciones)

@pytest.mark.asyncio
@pytest.mark.parametrize("motivo", ["solicitud", "apelacion"])
@pytest.mark.parametrize("accion", ["aprobar", "rechazar", "decision-borrador", "comentarios-debate", "cerrar-expediente"])
async def test_miembro_impedido_no_registra_acciones(motivo, accion):
    db = BaseComite(impedimento=motivo, visitas=[_visita(10, 90)])
    with pytest.raises(HTTPException) as error:
        await ComiteService(db).registrar_accion(accion, _payload(), MIEMBRO)
    # 404: al impedido no se le revela que el expediente existe.
    assert error.value.status_code == 404
    assert error.value.detail == MENSAJE_NO_ENCONTRADO
    assert not db.hubo("UPDATE solicitud") and not db.hubo("INSERT INTO comite_accion")
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_miembro_nuevo_puede_evaluar_la_primera_vez():
    db = BaseComite(impedimento=None, visitas=[_visita(10, 90)])
    respuesta = await ComiteService(db).registrar_accion("aprobar", _payload(), MIEMBRO)
    assert respuesta["estado"] == "Aprobada"
    assert db.hubo("AS impedimento") and db.hubo("INSERT INTO comite_accion")
    # Se consulta con el id del miembro autenticado.
    consulta = db.params[db.sql.index(next(s for s in db.sql if "AS impedimento" in s))]
    assert consulta["imp_usuario"] == MIEMBRO["id_usuario"]


@pytest.mark.asyncio
async def test_el_coordinador_no_esta_sujeto_a_la_regla():
    db = BaseComite(impedimento="solicitud", visitas=[_visita(10, 90)])
    await ComiteService(db).registrar_accion("aprobar", _payload(), COORDINADOR)
    assert not db.hubo("AS impedimento")
    assert db.hubo("INSERT INTO comite_accion")


def test_impedimento_solo_por_decision_previa_o_decision_de_la_apelacion():
    sql = sql_impedimento("s.id_solicitud")
    # (b) Apelación: solo quien la aprobó o rechazó (id_usuario_revisa con la
    # apelación ya decidida). Comité asignado, evaluador y requerimientos ya no.
    assert "ap.id_usuario_revisa" in sql
    assert "IN ('APROBADA', 'RECHAZADA', 'NOTIFICADA', 'CERRADA')" in sql
    for fragmento in ("apelacion_comite", "id_auditor_evaluador", "requerimiento_apelacion"):
        assert fragmento not in sql
    # (a) Solicitud: solo las DECISIONES de una ronda anterior a la última reapertura.
    assert "ca.accion IN ('aprobar', 'rechazar', 'decisiones', 'decision-definitiva')" in sql
    assert "ca.fecha < (SELECT MAX(r.fecha)" in sql and "'reabrir-dictamen'" in sql
    # Borrador, debate, observaciones, información, acta... ya no impiden.
    for accion in ("decision-borrador", "comentarios-debate", "observaciones-acta",
                   "solicitar-info-adicional", "restricciones-alcance", "firmar-acta", "acta-definitiva"):
        assert f"'{accion}'" not in sql


def test_la_apelacion_propia_no_oculta_su_apelacion_al_que_la_decidio():
    sql = sql_impedimento("a.id_solicitud", columna_apelacion_propia="a.id")
    assert "AND ap.id <> a.id" in sql


# ---------------------------------------------------------------- calificación obligatoria del líder

@pytest.mark.asyncio
@pytest.mark.parametrize("accion", ["aprobar", "rechazar", "decisiones", "decision-definitiva"])
async def test_decision_bloqueada_sin_la_evaluacion_de_la_visita(accion):
    db = BaseComite(visitas=[_visita(10, 90), _visita(12)])
    with pytest.raises(HTTPException) as error:
        await ComiteService(db).registrar_accion(accion, _payload(), COORDINADOR)
    assert error.value.status_code == 409
    assert "falta la evaluación de la visita 2" in error.value.detail
    assert "líder" not in error.value.detail
    assert not db.hubo("UPDATE solicitud") and not db.hubo("INSERT INTO comite_accion")


@pytest.mark.asyncio
async def test_borrador_y_debate_no_exigen_la_calificacion():
    db = BaseComite(visitas=[_visita(12)])
    await ComiteService(db).registrar_accion("decision-borrador", _payload(), MIEMBRO)
    assert not db.hubo("to_regclass")


@pytest.mark.asyncio
async def test_sin_la_tabla_de_calificaciones_no_se_bloquea_la_decision():
    db = BaseComite(tabla=False, visitas=[_visita(12)])
    respuesta = await ComiteService(db).registrar_accion("aprobar", _payload(), MIEMBRO)
    assert respuesta["estado"] == "Aprobada"
    assert not db.hubo("AS evaluaciones")


# ---------------------------------------------------------------- rutas del Comité

class SesionRutas:
    def __init__(self, impedimento=None, filas=None, lider=None):
        self.impedimento = impedimento
        self.filas = filas or []
        self.lider = lider
        self.sql: list[str] = []
        self.params: list = []

    async def execute(self, consulta, params=None):
        sql = str(consulta)
        self.sql.append(sql)
        self.params.append(params)
        if "AS impedimento" in sql and "FROM solicitud s" not in sql:
            return _resultado([{"impedimento": self.impedimento}])
        if "FROM solicitud s" in sql and "WITH decision" in sql:
            return _resultado(self.filas)
        if "FROM norma" in sql:
            return _resultado([])
        if "FROM asignacion_lider_comite a" in sql:
            return _resultado([self.lider] if self.lider else [])
        if "AS disponible" in sql:
            return _resultado([{"disponible": True}])
        if "FROM comite_acta" in sql:
            return _resultado([])
        return _resultado([{"id": uuid4(), "codigo": "SOL-1", "estado": "En revision"}])


def _cliente(usuario, sesion):
    from main import app

    async def _db():
        yield sesion

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: usuario
    return app, TestClient(app)


@pytest.mark.parametrize("ruta", [
    "/comite/expediente-completo/{id}", "/comite/informe-auditor/{id}", "/comite/evidencias-fisicas/{id}",
    "/comite/no-conformidades/{id}", "/comite/observaciones-tecnicos/{id}", "/comite/auditor-responsable/{id}",
    "/comite/expediente-descargar/{id}",
])
def test_miembro_impedido_no_ve_el_expediente(ruta):
    sesion = SesionRutas(impedimento="apelacion")
    app, cliente = _cliente(MIEMBRO, sesion)
    try:
        respuesta = cliente.get(ruta.format(id=uuid4()))
    finally:
        app.dependency_overrides.clear()
    # 404 y no 403: no se revela que existe.
    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == MENSAJE_NO_ENCONTRADO


def test_coordinador_ve_el_expediente_aunque_otro_este_impedido():
    sesion = SesionRutas(impedimento="solicitud")
    app, cliente = _cliente(COORDINADOR, sesion)
    try:
        respuesta = cliente.get(f"/comite/expediente-completo/{uuid4()}")
    finally:
        app.dependency_overrides.clear()
    assert respuesta.status_code == 200
    assert not any("AS impedimento" in s for s in sesion.sql)


def test_acta_bloqueada_para_el_impedido_que_no_es_el_lider():
    otro = {"id_asignacion": uuid4(), "id_usuario": uuid4(), "nombre": "Otro líder", "correo": "o@x.co",
            "fecha_inicio": None, "por_expediente": True}
    sesion = SesionRutas(impedimento="solicitud", lider=otro)
    app, cliente = _cliente(MIEMBRO, sesion)
    try:
        acta = cliente.post("/comite/acta-definitiva", json={"expediente_id": str(uuid4()), "comentario": "Acta"})
        estado = cliente.get(f"/comite/acta-estado/{uuid4()}")
        firmada = cliente.get(f"/comite/acta-firmada/{uuid4()}")
    finally:
        app.dependency_overrides.clear()
    assert acta.status_code == 404 and estado.status_code == 404 and firmada.status_code == 404


def test_lider_del_expediente_impedido_puede_ver_y_firmar_su_acta():
    """El líder del comité de ese expediente nunca queda bloqueado para firmar lo suyo."""
    lider = {"id_asignacion": uuid4(), "id_usuario": MIEMBRO["id_usuario"], "nombre": "Marta", "correo": "m@x.co",
             "fecha_inicio": None, "por_expediente": True}
    sesion = SesionRutas(impedimento="apelacion", lider=lider)
    app, cliente = _cliente(MIEMBRO, sesion)
    try:
        estado = cliente.get(f"/comite/acta-estado/{uuid4()}")
    finally:
        app.dependency_overrides.clear()
    assert estado.status_code == 200
    assert estado.json()["lider"]["id_usuario"] == MIEMBRO["id_usuario"]


def _fila(**cambios):
    fila = {
        "id": uuid4(), "codigo": "SOL-1", "empresa": "ACME", "nit": "900", "empresa_ciudad": "Pereira",
        "sedes_departamentos": [], "sedes_paises": [], "norma": "ISO-9001", "estado": "En revision",
        "fecha_creacion": None, "fecha_radicacion": None, "accion": None, "comentario": None,
        "fecha_decision": None, "decidio": None, "estado_acta": None, "fecha_firma": None,
        "id_certificado": None, "codigo_verificacion": None, "estado_certificado": None,
        "certificado_firmado": None, "impedimento": None,
    }
    fila.update(cambios)
    return fila


def test_vista_unificada_marca_impedimento_decision_y_firma():
    filas = [
        _fila(codigo="SOL-PEND", impedimento="solicitud"),
        _fila(codigo="SOL-NUEVA"),
        _fila(codigo="SOL-APR", estado="Aprobada", accion="aprobar", decidio="Marta",
              fecha_decision=datetime(2026, 11, 1), estado_acta="FIRMADA", id_certificado=uuid4(),
              codigo_verificacion="CERT-1", estado_certificado="PENDIENTE_FIRMA", certificado_firmado=False),
        _fila(codigo="SOL-APEL", estado="Aprobada", accion="rechazar"),
        _fila(codigo="SOL-RECH", estado="Rechazada", accion="rechazar", estado_acta="FIRMADA"),
    ]
    sesion = SesionRutas(filas=filas)
    app, cliente = _cliente(MIEMBRO, sesion)
    try:
        todos = cliente.get("/comite/expedientes-pendientes", params={"estado": "todos"}).json()
        por_cert = cliente.get("/comite/expedientes-pendientes", params={"estado": "todos", "firma": "certificado-pendiente"}).json()
        rechazadas = cliente.get("/comite/expedientes-pendientes", params={"estado": "todos", "decision": "rechazada"}).json()
        firmadas = cliente.get("/comite/expedientes-pendientes", params={"estado": "todos", "firma": "firmado"}).json()
        pagina2 = cliente.get("/comite/expedientes-pendientes", params={"estado": "todos", "page": 2, "page_size": 2}).json()
    finally:
        app.dependency_overrides.clear()
    por_codigo = {f["codigo"]: f for f in todos["expedientes"]}
    # Una fila con impedimento solo llega si es el líder del expediente: solo firma.
    assert por_codigo["SOL-PEND"]["impedimento"] == MENSAJES["solicitud"]
    assert por_codigo["SOL-PEND"]["puede_evaluar"] is False and por_codigo["SOL-PEND"]["solo_firma"] is True
    assert por_codigo["SOL-NUEVA"]["solo_firma"] is False
    assert por_codigo["SOL-NUEVA"]["puede_evaluar"] is True and por_codigo["SOL-NUEVA"]["decision"] is None
    aprobada = por_codigo["SOL-APR"]
    assert aprobada["decision"] == "Aprobada" and aprobada["decidio"] == "Marta"
    assert aprobada["firma_dictamen"] == "Firmado" and aprobada["firma_certificado"] == "Pendiente de firma"
    assert aprobada["certificado_pendiente_firma"] is True and aprobada["puede_evaluar"] is False
    # Rechazada por el Comité y aprobada por apelación.
    assert por_codigo["SOL-APEL"]["decision"] == "Aprobada" and por_codigo["SOL-APEL"]["por_apelacion"] is True
    assert [f["codigo"] for f in por_cert["expedientes"]] == ["SOL-APR"]
    assert [f["codigo"] for f in rechazadas["expedientes"]] == ["SOL-RECH"]
    assert [f["codigo"] for f in firmadas["expedientes"]] == ["SOL-RECH"]
    assert pagina2["total"] == 5 and pagina2["paginas"] == 3
    assert [f["codigo"] for f in pagina2["expedientes"]] == ["SOL-APR", "SOL-APEL"]
    # La consulta usa el id del miembro para la regla de imparcialidad y
    # EXCLUYE en SQL lo impedido (contadores y paginación incluidos), salvo
    # que sea el líder del expediente.
    assert any(p and p.get("imp_usuario") == MIEMBRO["id_usuario"] for p in sesion.params)
    consulta = next(s for s in sesion.sql if "WITH decision" in s)
    assert "IS NULL OR" in consulta and "asignacion_lider_comite la" in consulta


def test_impedido_no_ve_decisiones_ni_en_la_exportacion_ni_en_la_busqueda():
    sesion = SesionRutas()
    app, cliente = _cliente(MIEMBRO, sesion)
    try:
        assert cliente.get("/comite/exportar-decisiones", params={"formato": "xlsx"}).status_code == 200
        assert cliente.get("/comite/exportar-decisiones").status_code == 200
        assert cliente.get("/comite/buscar-expediente", params={"query": "900"}).status_code == 200
        assert cliente.get("/comite/decisiones-historicas").status_code == 200
        assert cliente.get("/comite/historial-dictamenes").status_code == 200
        assert cliente.get(f"/comite/historial-por-empresa/{uuid4()}").status_code == 200
    finally:
        app.dependency_overrides.clear()
    filtradas = [s for s, p in zip(sesion.sql, sesion.params)
                 if p and p.get("imp_usuario") == MIEMBRO["id_usuario"] and "ap.id_usuario_revisa" in s]
    assert len(filtradas) == 6


def test_vista_unificada_sin_regla_para_el_coordinador():
    sesion = SesionRutas(filas=[_fila()])
    app, cliente = _cliente(COORDINADOR, sesion)
    try:
        datos = cliente.get("/comite/expedientes-pendientes").json()
    finally:
        app.dependency_overrides.clear()
    assert datos["expedientes"][0]["puede_evaluar"] is True
    assert not any(p and "imp_usuario" in p for p in sesion.params)


def test_exportacion_de_decisiones_sigue_disponible():
    sesion = SesionRutas()
    app, cliente = _cliente(COORDINADOR, sesion)
    try:
        respuesta = cliente.get("/comite/exportar-decisiones", params={"formato": "xlsx"})
    finally:
        app.dependency_overrides.clear()
    assert respuesta.status_code == 200
    assert "spreadsheet" in respuesta.headers["content-type"]


# ---------------------------------------------------------------- programaciones futuras (retirado)

def test_programaciones_futuras_redirige_y_sus_endpoints_ya_no_existen():
    from main import app

    cliente = TestClient(app)
    respuesta = cliente.get("/programaciones-futuras-auditor", follow_redirects=False)
    assert respuesta.status_code == 302
    assert respuesta.headers["location"] == "/consultar-auditorias-programadas"
    rutas = app.openapi()["paths"]
    assert not any("programaciones-futuras" in ruta for ruta in rutas)
