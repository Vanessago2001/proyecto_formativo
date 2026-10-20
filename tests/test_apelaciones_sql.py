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

from modules.apelaciones.apelaciones_service import ApelacionesService

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

    def __init__(self, estado_solicitud="Rechazada", error_insert=None):
        self.estado_solicitud = estado_solicitud
        self.error_insert = error_insert
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

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
