"""
Líder del Comité por expediente (17/11/2026) y ocultamiento al impedido.

"El administrador elige el líder de comité; puede ser diferente en cada
comité y ese líder debe haber participado en el comité." Se prueba con bases
falsas: nunca toca la base real.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modules.comite import lider_expediente
from modules.comite.imparcialidad import exigir_imparcialidad, filtro_visible

COORDINADOR = {"id_usuario": str(uuid4()), "nombre": "Coordinación", "role_name": "Coordinador"}
MIEMBRO = {"id_usuario": str(uuid4()), "nombre": "Marta", "role_name": "Comité"}


def _resultado(filas=None):
    resultado = MagicMock()
    filas = filas or []
    resultado.mappings.return_value.first.return_value = filas[0] if filas else None
    resultado.mappings.return_value.all.return_value = filas
    resultado.scalar.return_value = 1 if filas else None
    return resultado


class Base:
    """Responde según el texto del SQL y registra todo lo ejecutado."""

    def __init__(self, *, disponible=True, participantes=None, actual=None, lider=None, impedimento=None,
                 certificados=None):
        self.disponible = disponible
        self.participantes = participantes or []
        self.actual = actual
        self.lider = lider
        self.impedimento = impedimento
        self.certificados = certificados or []
        self.sql: list[str] = []
        self.params: list = []
        self.commits = 0

    async def execute(self, consulta, params=None):
        sql = str(consulta)
        self.sql.append(sql)
        self.params.append(params)
        if "AS disponible" in sql:
            return _resultado([{"disponible": self.disponible}])
        if "AS impedimento" in sql:
            return _resultado([{"impedimento": self.impedimento}])
        if "pg_advisory" in sql:
            return _resultado()
        if "FROM solicitud" in sql:
            return _resultado([{"id_solicitud": uuid4()}])
        if "FROM usuario u" in sql and "comite_accion pa" in sql:
            return _resultado(self.participantes)
        if "FOR UPDATE" in sql and "asignacion_lider_comite a" in sql and "por_expediente" not in sql:
            return _resultado([self.actual] if self.actual else [])
        if "FROM asignacion_lider_comite a" in sql:
            return _resultado([self.lider] if self.lider else [])
        if sql.strip().startswith("UPDATE certificado"):
            return _resultado(self.certificados)
        return _resultado()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    def hubo(self, texto):
        return any(texto in s for s in self.sql)


def _persona(nombre="Ana"):
    return {"id_usuario": uuid4(), "nombre": nombre, "correo": f"{nombre.lower()}@x.co"}


# ---------------------------------------------------------------- asignación por el Coordinador

def test_coordinador_asigna_un_participante_y_pasa_los_certificados_pendientes():
    ana, luis = _persona("Ana"), _persona("Luis")
    cert = {"id_certificado": uuid4()}
    db = Base(participantes=[ana, luis], certificados=[cert])
    id_solicitud = uuid4()
    respuesta = asyncio.run(lider_expediente.asignar(db, id_solicitud, luis["id_usuario"], COORDINADOR))
    assert respuesta["lider"]["nombre"] == "Luis"
    insert = next(i for i, s in enumerate(db.sql) if "INSERT INTO asignacion_lider_comite" in s)
    assert "id_solicitud" in db.sql[insert]
    assert db.params[insert]["id_solicitud"] == str(id_solicitud)
    assert db.params[insert]["id_usuario"] == str(luis["id_usuario"])
    assert respuesta["certificados_reasignados"] == [str(cert["id_certificado"])]
    assert db.commits == 1


def test_no_participante_no_puede_ser_lider_422():
    db = Base(participantes=[_persona("Ana")])
    with pytest.raises(HTTPException) as error:
        asyncio.run(lider_expediente.asignar(db, uuid4(), uuid4(), COORDINADOR))
    assert error.value.status_code == 422
    assert "participado" in error.value.detail
    assert not db.hubo("INSERT INTO asignacion_lider_comite") and db.commits == 0


def test_cambiar_lider_cierra_la_asignacion_anterior_del_expediente():
    ana, luis = _persona("Ana"), _persona("Luis")
    anterior = {"id_asignacion": uuid4(), "id_usuario": ana["id_usuario"]}
    db = Base(participantes=[ana, luis], actual=anterior)
    asyncio.run(lider_expediente.asignar(db, uuid4(), luis["id_usuario"], COORDINADOR))
    cierre = next(i for i, s in enumerate(db.sql) if "SET fecha_fin = CURRENT_TIMESTAMP" in s)
    assert db.params[cierre]["id_asignacion"] == str(anterior["id_asignacion"])


def test_sin_el_sql_no_se_asigna_y_se_avisa_503():
    db = Base(disponible=False, participantes=[_persona()])
    with pytest.raises(HTTPException) as error:
        asyncio.run(lider_expediente.asignar(db, uuid4(), uuid4(), COORDINADOR))
    assert error.value.status_code == 503
    assert error.value.detail == lider_expediente.MENSAJE_FALTA_SQL
    consulta = asyncio.run(lider_expediente.consultar(Base(disponible=False), uuid4()))
    assert consulta["disponible"] is False and consulta["aviso"] == lider_expediente.MENSAJE_FALTA_SQL


def test_participar_es_registrar_una_accion_de_evaluacion_en_la_ronda_vigente():
    sql = lider_expediente.sql_participacion("s.id_solicitud", "u.id_usuario")
    for accion in ("aprobar", "rechazar", "decision-borrador", "comentarios-debate", "solicitar-info-adicional"):
        assert f"'{accion}'" in sql
    for accion in ("firmar-acta", "acta-definitiva", "cerrar-expediente", "reabrir-dictamen'"):
        assert f"'{accion}'," not in sql and f"'{accion}')" not in sql
    assert "pa.fecha > COALESCE" in sql and "'reabrir-dictamen'" in sql


def test_compatibilidad_sin_la_columna_usa_el_lider_global():
    # Sin la columna, to_jsonb(a)->>'id_solicitud' es NULL y entra la fila global.
    condicion = lider_expediente.sql_asignacion_del_expediente(":id", "a")
    assert "(to_jsonb(a)->>'id_solicitud') = CAST(:id AS TEXT)" in condicion
    assert "OR (NOT EXISTS (" in condicion and "column_name = 'id_solicitud'" in condicion
    assert "(to_jsonb(a)->>'id_solicitud') IS NULL" in condicion


def test_reabrir_libera_el_lider_del_expediente():
    db = Base()
    asyncio.run(lider_expediente.terminar_por_reapertura(db, uuid4()))
    assert db.hubo("UPDATE asignacion_lider_comite a SET fecha_fin")


# ---------------------------------------------------------------- firma

def test_acta_solo_la_firma_el_lider_del_expediente():
    from modules.comite.comite_acta_service import ComiteActaService

    otro = {"id_asignacion": uuid4(), "id_usuario": uuid4(), "nombre": "Otro", "correo": "o@x.co",
            "fecha_inicio": datetime.now(timezone.utc), "por_expediente": True}
    db = Base(lider=otro)
    with pytest.raises(HTTPException) as error:
        asyncio.run(ComiteActaService(db).firmar(uuid4(), "clave", MIEMBRO))
    assert error.value.status_code == 403
    # La consulta del líder es la del expediente (no la global).
    assert db.params[0]["lider_solicitud"]


def test_acta_sin_lider_asignado_409():
    from modules.comite.comite_acta_service import ComiteActaService

    with pytest.raises(HTTPException) as error:
        asyncio.run(ComiteActaService(Base(lider=None)).firmar(uuid4(), "clave", MIEMBRO))
    assert error.value.status_code == 409 and "Coordinador" in error.value.detail


def test_lider_impedido_pasa_la_imparcialidad_solo_con_permitir_lider():
    yo = {"id_asignacion": uuid4(), "id_usuario": MIEMBRO["id_usuario"], "nombre": "Marta", "correo": "m@x.co",
          "fecha_inicio": None, "por_expediente": True}
    db = Base(impedimento="apelacion", lider=yo)
    asyncio.run(exigir_imparcialidad(db, uuid4(), MIEMBRO, permitir_lider=True))
    with pytest.raises(HTTPException) as error:
        asyncio.run(exigir_imparcialidad(db, uuid4(), MIEMBRO))
    assert error.value.status_code == 404


def test_certificado_de_expediente_impedido_da_404_salvo_al_lider():
    from modules.certificados.certificados_service import CertificadosService

    fila = {"id_certificado": uuid4(), "id_solicitud": uuid4(), "id_empresa": uuid4(),
            "estado_certificado": "VIGENTE", "publico_certificado": True}

    class BaseCert(Base):
        async def execute(self, consulta, params=None):
            if "WHERE c.id_certificado" in str(consulta):
                self.sql.append(str(consulta))
                return _resultado([fila])
            return await super().execute(consulta, params)

    with pytest.raises(HTTPException) as error:
        asyncio.run(CertificadosService(BaseCert(impedimento="solicitud"))._obtener(uuid4(), MIEMBRO))
    assert error.value.status_code == 404
    yo = {"id_asignacion": uuid4(), "id_usuario": MIEMBRO["id_usuario"], "nombre": "M", "correo": "m@x.co",
          "fecha_inicio": None, "por_expediente": True}
    assert asyncio.run(CertificadosService(BaseCert(impedimento="solicitud", lider=yo))._obtener(uuid4(), MIEMBRO))
    # El Coordinador no pasa por la regla.
    db = BaseCert(impedimento="solicitud")
    asyncio.run(CertificadosService(db)._obtener(uuid4(), COORDINADOR))
    assert not db.hubo("AS impedimento")


def test_pendientes_de_firma_solo_los_del_expediente_donde_es_lider():
    from modules.certificados.certificados_service import CertificadosService

    db = Base()
    asyncio.run(CertificadosService(db).listar(MIEMBRO))
    sql, params = db.sql[-1], db.params[-1]
    assert "al.id_usuario::TEXT = :id_usuario_lider" in sql and params["id_usuario_lider"] == MIEMBRO["id_usuario"]
    # Imparcialidad con excepción del líder del expediente.
    assert params["imp_usuario"] == MIEMBRO["id_usuario"] and "asignacion_lider_comite la" in sql


def test_mi_liderazgo_por_expediente():
    from modules.certificados.certificados_service import CertificadosService

    class BaseLiderazgo(Base):
        async def execute(self, consulta, params=None):
            sql = str(consulta)
            if "AS expedientes" in sql:
                self.sql.append(sql)
                return _resultado([{"por_expediente": True, "expedientes": 2}])
            return await super().execute(consulta, params)

    datos = asyncio.run(CertificadosService(BaseLiderazgo()).mi_liderazgo(MIEMBRO))
    assert datos["es_lider"] is True and datos["expedientes_liderados"] == 2 and datos["lider_por_expediente"] is True


# ---------------------------------------------------------------- ocultar al impedido

def test_filtro_visible_solo_para_el_comite():
    params: dict = {}
    assert filtro_visible(COORDINADOR, "s.id_solicitud", params) == "" and params == {}
    condicion = filtro_visible(MIEMBRO, "s.id_solicitud", params)
    assert "IS NULL" in condicion and params["imp_usuario"] == MIEMBRO["id_usuario"]


def test_apelaciones_del_impedido_no_aparecen():
    from modules.apelaciones.apelaciones_service import ApelacionesService

    db = Base()
    asyncio.run(ApelacionesService(db).get_all_apelaciones(MIEMBRO))
    sql, params = db.sql[-1], db.params[-1]
    assert "ap.id <> a.id" in sql and params["imp_usuario"] == MIEMBRO["id_usuario"]


def test_apelacion_de_solicitud_impedida_da_404():
    from modules.apelaciones.apelaciones_service import ApelacionesService

    class BaseApelacion(Base):
        def __init__(self, valor):
            super().__init__()
            self.valor = valor

        async def execute(self, consulta, params=None):
            sql = str(consulta)
            self.sql.append(sql)
            self.params.append(params)
            resultado = _resultado()
            resultado.scalar.return_value = self.valor
            return resultado

    # Asignado pero impedido (-1) → 404; una sola consulta con la regla dentro.
    db = BaseApelacion(-1)
    with pytest.raises(HTTPException) as error:
        asyncio.run(ApelacionesService(db).exigir_acceso(uuid4(), MIEMBRO))
    assert error.value.status_code == 404
    assert len(db.sql) == 1 and "ap.id <> a.id" in db.sql[0] and db.params[0]["imp_usuario"] == MIEMBRO["id_usuario"]
    # No asignado → 403 como antes; asignado y visible → pasa.
    with pytest.raises(HTTPException) as error:
        asyncio.run(ApelacionesService(BaseApelacion(None)).exigir_acceso(uuid4(), MIEMBRO))
    assert error.value.status_code == 403
    asyncio.run(ApelacionesService(BaseApelacion(1)).exigir_acceso(uuid4(), MIEMBRO))
