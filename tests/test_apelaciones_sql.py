"""
Apelaciones · el SQL del servicio contra el esquema real de la base.

Las pruebas existentes sustituyen el servicio por un simulacro, así que no
veían los fallos que tenía el módulo contra la base desplegada:

  · `apelacion.id` no tiene valor por defecto: el INSERT debe generarlo.
  · La columna de quien sube una evidencia es `id_usuario_subio` (UUID), no
    `id_usuario` (entero heredado).
  · `evidencia_apelacion.tipo_evidencia` solo admite unos valores concretos.
  · Un error de integridad que no sea duplicado no debe disfrazarse de
    "ya tiene una apelación registrada".

Aquí se ejercita el servicio con un doble que responde por el texto de cada
consulta y guarda lo que se ejecutó, sin necesidad de base de datos.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from modules.apelaciones.apelaciones_service import ApelacionesService, estado_es_rechazada

ID_EMPRESA = uuid.uuid4()
ID_USUARIO = uuid.uuid4()
ID_SOLICITUD = uuid.uuid4()
ID_APELACION = uuid.uuid4()

USUARIO = {"id_usuario": ID_USUARIO, "role_name": "Empresa", "nombre": "empresa"}


class Resultado:
    def __init__(self, primera=None, todas=None, escalar=None):
        self._primera, self._todas, self._escalar = primera, todas or [], escalar

    def mappings(self):
        return self

    def first(self):
        return self._primera

    def all(self):
        return self._todas

    def scalar(self):
        return self._escalar


class BaseFalsa:
    """Responde según el texto de la consulta y guarda lo ejecutado."""

    def __init__(self, estado_solicitud="Rechazada", error_insert=None, motivo_comite="No cumple el alcance declarado."):
        self.estado_solicitud = estado_solicitud
        self.error_insert = error_insert
        self.motivo_comite = motivo_comite
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

        if "FROM comite_accion" in sql:
            return Resultado(escalar=self.motivo_comite)
        if "FROM user_empresa" in sql:
            return Resultado(todas=[{"id_empresa": str(ID_EMPRESA)}])
        if "nextval" in sql:
            return Resultado(escalar=7)
        if "FROM solicitud" in sql:
            return Resultado(primera={
                "id_solicitud": ID_SOLICITUD, "id_empresa": ID_EMPRESA,
                "estado": self.estado_solicitud, "deleted_at": None, "observaciones": None,
            })
        if sql.startswith("SELECT id FROM apelacion"):
            return Resultado(escalar=None)
        if sql.startswith("INSERT INTO apelacion"):
            if self.error_insert is not None:
                raise self.error_insert
            return Resultado(primera={"id": ID_APELACION, "radicado": "APE-2026-000007", "estado": "ENVIADA"})
        if sql.startswith("SELECT id, id_solicitud"):
            return Resultado(primera={
                "id": ID_APELACION, "id_solicitud": ID_SOLICITUD, "estado": "ENVIADA",
            })
        if sql.startswith("INSERT INTO evidencia_apelacion"):
            return Resultado(primera={"id_evidencia": uuid.uuid4(), "id_usuario": ID_USUARIO})
        return Resultado()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def sql_de(self, prefijo: str) -> str:
        return next(sql for sql, _ in self.sentencias if sql.startswith(prefijo))

    def parametros_de(self, prefijo: str) -> dict:
        return next(p for sql, p in self.sentencias if sql.startswith(prefijo))


class Archivo:
    def __init__(self, filename):
        self.filename = filename

    async def read(self):
        return b"%PDF-1.4 contenido de prueba"


def error_de_integridad(sqlstate: str) -> IntegrityError:
    class Original(Exception):
        pass

    original = Original("fallo")
    original.sqlstate = sqlstate
    return IntegrityError("INSERT", {}, original)


async def test_la_apelacion_se_crea_generando_su_id():
    """`apelacion.id` no tiene valor por defecto en la base."""
    db = BaseFalsa()

    await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)

    sql = db.sql_de("INSERT INTO apelacion")
    assert "gen_random_uuid()" in sql
    assert sql.index("INSERT INTO apelacion ( id,") > -1


async def test_solo_se_apela_una_solicitud_rechazada():
    db = BaseFalsa(estado_solicitud="Radicada")

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)

    assert error.value.status_code == 409
    assert not any(sql.startswith("INSERT INTO apelacion") for sql, _ in db.sentencias)


async def test_el_duplicado_se_reporta_solo_cuando_lo_es():
    db = BaseFalsa(error_insert=error_de_integridad("23505"))

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)

    assert error.value.status_code == 409
    assert "ya tiene una apelación" in error.value.detail


async def test_otro_error_de_integridad_no_se_disfraza_de_duplicado():
    """Antes cualquier fallo se reportaba como 'ya tiene una apelación'."""
    db = BaseFalsa(error_insert=error_de_integridad("23502"))  # violación de NOT NULL

    with pytest.raises(IntegrityError):
        await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)


@pytest.mark.parametrize(
    "archivo,tipo",
    [("soporte.pdf", "Documento PDF"), ("foto.png", "Fotografía"), ("informe.docx", "Informe Técnico")],
)
async def test_la_evidencia_usa_la_columna_y_el_tipo_que_admite_la_base(archivo, tipo):
    db = BaseFalsa()

    await ApelacionesService(db).add_evidence(ID_APELACION, Archivo(archivo), "descripcion", USUARIO)

    sql = db.sql_de("INSERT INTO evidencia_apelacion")
    parametros = db.parametros_de("INSERT INTO evidencia_apelacion")
    assert "id_usuario_subio" in sql
    assert ", id_usuario," not in sql, "id_usuario es la columna entera heredada"
    assert parametros["tipo_evidencia"] == tipo
    assert parametros["id_usuario_subio"] == ID_USUARIO


async def test_queda_registrado_quien_revisa_la_apelacion():
    db = BaseFalsa()

    await ApelacionesService(db).registrar_decision_final(ID_APELACION, "RECHAZADA", "sin merito", USUARIO)

    sql = db.sql_de("UPDATE apelacion")
    assert "id_usuario_revisa = :id_usuario" in sql
    assert db.parametros_de("UPDATE apelacion")["id_usuario"] == ID_USUARIO


async def test_el_estado_lleva_tipo_explicito():
    """Sin el CAST, PostgreSQL rechaza la consulta por tipos ambiguos."""
    db = BaseFalsa()

    await ApelacionesService(db).registrar_decision_final(ID_APELACION, "APROBADA", None, USUARIO)

    assert "CAST(:decision AS VARCHAR)" in db.sql_de("UPDATE apelacion")


async def test_no_se_asigna_comite_a_una_apelacion_inexistente():
    class SinApelacion(BaseFalsa):
        async def execute(self, sentencia, parametros=None):
            sql = " ".join(str(sentencia).split())
            if sql.startswith("SELECT 1 FROM apelacion"):
                self.sentencias.append((sql, parametros or {}))
                return Resultado(escalar=None)
            return await super().execute(sentencia, parametros)

    db = SinApelacion()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_USUARIO])

    assert error.value.status_code == 404
    assert not any(sql.startswith("INSERT INTO apelacion_comite") for sql, _ in db.sentencias)


# ============================================================
# ESTADO DE LA SOLICITUD: cada modulo lo escribe distinto
# ============================================================
# El Comite guarda 'RECHAZADO' y M5 define 'Rechazada'. Comparar con un texto
# exacto dejaba sin apelacion a las solicitudes rechazadas desde el Comite.

@pytest.mark.parametrize("estado", ["Rechazada", "RECHAZADO", "rechazado", "RECHAZADA", " Rechazada "])
def test_se_reconocen_las_variantes_de_rechazada(estado):
    assert estado_es_rechazada(estado) is True


@pytest.mark.parametrize("estado", ["Radicada", "APROBADO", "EN_REVISION", "Borrador", "", None])
def test_no_se_confunden_otros_estados(estado):
    assert estado_es_rechazada(estado) is False


async def test_se_apela_una_solicitud_rechazada_por_el_comite():
    """El estado real que deja el Comite es 'RECHAZADO'."""
    db = BaseFalsa(estado_solicitud="RECHAZADO")

    await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)

    assert any(sql.startswith("INSERT INTO apelacion") for sql, _ in db.sentencias)


# ============================================================
# MOTIVO DEL RECHAZO: el que escribio el Comite
# ============================================================
# El Comite guarda su comentario en comite_accion.datos; antes la apelacion
# mostraba las observaciones de la solicitud, que son otra cosa.

async def test_la_apelacion_guarda_el_motivo_que_escribio_el_comite():
    db = BaseFalsa(estado_solicitud="RECHAZADO", motivo_comite="Falta el soporte del alcance.")

    await ApelacionesService(db).create_apelacion({"id_solicitud": str(ID_SOLICITUD), "motivo": "motivo"}, USUARIO)

    assert db.parametros_de("INSERT INTO apelacion")["razones_rechazo"] == "Falta el soporte del alcance."
    consulta = db.sql_de("SELECT datos->>'comentario'")
    assert "FROM comite_accion" in consulta
    assert "'rechazar'" in consulta


async def test_el_contexto_dice_si_la_solicitud_se_puede_apelar():
    """Lo usa la pantalla para habilitar el boton de enviar apelacion."""
    db = BaseFalsa(estado_solicitud="RECHAZADO", motivo_comite="porque no")

    contexto = await ApelacionesService(db).contexto_de_solicitud(ID_SOLICITUD, USUARIO)

    assert contexto["apelable"] is True
    assert contexto["estado"] == "RECHAZADO"
    assert contexto["motivo_rechazo"] == "porque no"


async def test_el_contexto_no_habilita_una_solicitud_sin_rechazar():
    db = BaseFalsa(estado_solicitud="Radicada")

    contexto = await ApelacionesService(db).contexto_de_solicitud(ID_SOLICITUD, USUARIO)

    assert contexto["apelable"] is False


# ============================================================
# COMITE DE LA APELACION: distinto al que evaluo la solicitud
# ============================================================
# La apelacion la resuelve un comite diferente del que rechazo la solicitud, y
# ese comite solo entra a las apelaciones que le asignaron.

ID_EVALUADOR = uuid.uuid4()
ID_MIEMBRO = uuid.uuid4()

COMITE_ASIGNADO = {"id_usuario": ID_MIEMBRO, "role_name": "Comité", "nombre": "comite"}
COMITE_AJENO = {"id_usuario": ID_EVALUADOR, "role_name": "Comité", "nombre": "otro comite"}
ADMINISTRADOR = {"id_usuario": uuid.uuid4(), "role_name": "Administrador", "nombre": "admin"}


class BaseConComite(BaseFalsa):
    """Agrega al doble lo que necesita el comite de la apelacion."""

    def __init__(self, evaluadores=(ID_EVALUADOR,), asignados=(ID_MIEMBRO,), conocidos=None, **resto):
        super().__init__(**resto)
        self.evaluadores = [str(e) for e in evaluadores]
        self.asignados = [str(a) for a in asignados]
        self.conocidos = {str(ID_MIEMBRO): "Miembro nuevo", str(ID_EVALUADOR): "Leonel"} if conocidos is None else conocidos

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        parametros = parametros or {}

        # El servicio tiene dos consultas parecidas: la de los nombres y la
        # del rol de cada uno. Se distinguen por la columna del rol.
        if sql.startswith("SELECT u.id_usuario, COALESCE(u.nombre") and "r.nombre AS rol" not in sql:
            self.sentencias.append((sql, parametros))
            pedidos = parametros.get("identificadores") or []
            return Resultado(todas=[{"id_usuario": i, "nombre": self.conocidos[i]}
                                    for i in pedidos if i in self.conocidos])
        if sql.startswith("SELECT DISTINCT id_usuario FROM comite_accion"):
            self.sentencias.append((sql, parametros))
            return Resultado(todas=[(e,) for e in self.evaluadores])
        if sql.startswith("SELECT 1 FROM apelacion_comite"):
            self.sentencias.append((sql, parametros))
            esta = str(parametros.get("id_usuario")) in self.asignados
            return Resultado(escalar=1 if esta else None)
        if sql.startswith("SELECT ac.id_usuario"):
            self.sentencias.append((sql, parametros))
            return Resultado(todas=[{"id_usuario": a, "nombre": "miembro", "correo": "m@sena.edu.co",
                                     "asignado_en": None} for a in self.asignados])
        if sql.startswith("SELECT a.accion"):
            self.sentencias.append((sql, parametros))
            return Resultado(todas=[{"accion": "rechazar", "comentario": "porque no",
                                     "fecha": None, "usuario": "Leonel"}])
        if sql.startswith("SELECT id_solicitud FROM apelacion"):
            self.sentencias.append((sql, parametros))
            return Resultado(escalar=ID_SOLICITUD)
        # Al asignar, el servicio mira quien no es del Comite para cambiarle
        # el rol. Aqui todos lo son ya, asi que no hay nada que cambiar.
        if "r.nombre AS rol" in sql:
            self.sentencias.append((sql, parametros))
            return Resultado(todas=[])
        if sql.startswith("SELECT id_rol FROM rol"):
            self.sentencias.append((sql, parametros))
            return Resultado(escalar=uuid.uuid4())
        return await super().execute(sentencia, parametros)


async def test_no_se_asigna_al_comite_que_evaluo_la_solicitud_original():
    """Quien rechazo la solicitud no puede resolver la apelacion de esa solicitud."""
    db = BaseConComite()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_EVALUADOR])

    assert error.value.status_code == 409
    assert "distinto" in error.value.detail
    assert "Leonel" in error.value.detail  # se nombra a quien ya evaluo, no su identificador
    assert not any(sql.startswith("INSERT INTO apelacion_comite") for sql, _ in db.sentencias)


async def test_no_se_asigna_un_usuario_que_no_existe():
    """Antes rompia con un error de llave foranea que llegaba como error interno."""
    db = BaseConComite()
    desconocido = uuid.uuid4()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [desconocido])

    assert error.value.status_code == 400
    assert str(desconocido) in error.value.detail
    assert not any(sql.startswith("INSERT INTO apelacion_comite") for sql, _ in db.sentencias)


async def test_se_asigna_un_comite_distinto_y_queda_la_traza_de_quien_evaluo():
    db = BaseConComite()

    resultado = await ApelacionesService(db).assign_committee(ID_APELACION, [ID_MIEMBRO])

    assert resultado["miembros_comite"] == [ID_MIEMBRO]
    assert db.parametros_de("INSERT INTO apelacion_comite")["id_usuario"] == ID_MIEMBRO
    # Se guarda quien evaluo antes, aunque el Administrador no lo indique.
    assert db.parametros_de("UPDATE apelacion")["id_auditor_evaluador"] == str(ID_EVALUADOR)


async def test_una_asignacion_mixta_se_rechaza_completa():
    """Si uno de los miembros ya evaluo, no se asigna ninguno."""
    db = BaseConComite()

    with pytest.raises(HTTPException):
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_MIEMBRO, ID_EVALUADOR])

    assert not any(sql.startswith("DELETE FROM apelacion_comite") for sql, _ in db.sentencias)


async def test_no_se_asigna_comite_a_una_apelacion_que_no_existe():
    db = BaseConComite()
    db.execute_original = db.execute

    async def sin_apelacion(sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        if sql.startswith("SELECT id_solicitud FROM apelacion"):
            return Resultado(escalar=None)
        return await db.execute_original(sentencia, parametros)

    db.execute = sin_apelacion

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_MIEMBRO])

    assert error.value.status_code == 404


# ============================================================
# VISIBILIDAD DEL EXPEDIENTE
# ============================================================

async def test_el_comite_asignado_entra_a_la_apelacion():
    db = BaseConComite()

    await ApelacionesService(db).exigir_acceso(ID_APELACION, COMITE_ASIGNADO)


async def test_un_comite_que_no_tiene_la_apelacion_asignada_no_entra():
    db = BaseConComite()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).exigir_acceso(ID_APELACION, COMITE_AJENO)

    assert error.value.status_code == 403


@pytest.mark.parametrize("usuario", [ADMINISTRADOR, USUARIO])
async def test_la_administracion_y_la_empresa_no_quedan_atadas_al_comite(usuario):
    """La restriccion es solo para el rol Comite; no cambia a los demas."""
    db = BaseConComite(asignados=())

    await ApelacionesService(db).exigir_acceso(ID_APELACION, usuario)

    assert not any(sql.startswith("SELECT 1 FROM apelacion_comite") for sql, _ in db.sentencias)


async def test_el_listado_del_comite_se_limita_a_sus_apelaciones():
    db = BaseConComite()

    await ApelacionesService(db).get_all_apelaciones(COMITE_ASIGNADO)

    sql, parametros = next((s, p) for s, p in db.sentencias if s.startswith("SELECT a.id, a.id_solicitud"))
    assert "FROM apelacion_comite ac" in sql
    assert parametros["solo_asignadas"] is True
    assert parametros["filtro_empresa"] is False


async def test_el_listado_del_administrador_no_se_limita():
    db = BaseConComite()

    await ApelacionesService(db).get_all_apelaciones(ADMINISTRADOR)

    parametros = db.parametros_de("SELECT a.id, a.id_solicitud")
    assert parametros["solo_asignadas"] is False
    assert parametros["filtro_empresa"] is False


async def test_el_expediente_reune_solicitud_evaluacion_apelacion_y_evidencias(monkeypatch):
    from modules.solicitudes.solicitud_service import SolicitudService

    async def solicitud_ampliada(self, id_solicitud, usuario):
        return {"id_solicitud": str(id_solicitud), "numero_radicado": "SOL-2026-0002", "estado": "RECHAZADO"}

    monkeypatch.setattr(SolicitudService, "consultar_ampliada", solicitud_ampliada)
    db = BaseConComite()

    expediente = await ApelacionesService(db).expediente_apelacion(ID_APELACION, COMITE_ASIGNADO)

    assert expediente["solicitud_original"]["numero_radicado"] == "SOL-2026-0002"
    assert expediente["evaluacion_previa"][0]["comentario"] == "porque no"
    assert expediente["apelacion"]["id"] == ID_APELACION
    assert expediente["evidencias"] == []
    assert [m["id_usuario"] for m in expediente["comite_asignado"]] == [str(ID_MIEMBRO)]


async def test_el_expediente_se_le_niega_a_un_comite_ajeno():
    db = BaseConComite()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).expediente_apelacion(ID_APELACION, COMITE_AJENO)

    assert error.value.status_code == 403
