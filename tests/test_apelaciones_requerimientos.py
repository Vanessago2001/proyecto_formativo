"""
M10 — APELACIONES · lo que el Comité pide y lo que la empresa adjunta.

Cubre los cuatro cambios pedidos sobre el módulo:

  1. El Comité detalla por escrito qué documentos necesita, y eso queda en
     `requerimiento_apelacion` en vez de pisar las observaciones.
  2. Las acciones dependen del estado (lo comprueba la pantalla; aquí se
     comprueba que el servicio tampoco deje pasar lo que no toca).
  3. Se adjuntan varios documentos de una vez y la carga suma, no reemplaza.
  4. Al asignar el comité se admite a los auditores, y al asignarlos se les
     pasa el rol a Comité.
"""

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile

from modules.apelaciones import apelaciones_service
from modules.apelaciones.apelaciones_service import ApelacionesService


@pytest.fixture(autouse=True)
def archivos_en_temporal(tmp_path, monkeypatch):
    """Las evidencias de prueba se escriben en una carpeta temporal."""
    monkeypatch.setattr(apelaciones_service, "CARPETA_EVIDENCIAS", tmp_path / "apelaciones")
    monkeypatch.setattr(apelaciones_service, "RAIZ_PROYECTO", tmp_path)

ID_APELACION = uuid.uuid4()
ID_SOLICITUD = uuid.uuid4()
ID_EMPRESA = uuid.uuid4()
ID_AUDITOR = uuid.uuid4()
ID_MIEMBRO = uuid.uuid4()
ID_EVALUADOR = uuid.uuid4()
ID_ROL_COMITE = uuid.uuid4()

COMITE = {"id_usuario": ID_MIEMBRO, "role_name": "Comité"}
EMPRESA = {"id_usuario": uuid.uuid4(), "role_name": "Empresa"}


def archivo(nombre: str) -> UploadFile:
    return UploadFile(filename=nombre, file=io.BytesIO(b"%PDF-1.4 soporte"))


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
    """Doble que responde por el texto de cada consulta."""

    def __init__(self, estado="EN_REVISION", elegibles=None, requerimientos=None,
                 pendientes=1, rol_comite=ID_ROL_COMITE, sin_comite=None):
        self.estado = estado
        self.elegibles = elegibles if elegibles is not None else [
            {"id_usuario": ID_MIEMBRO, "nombre": "Ana", "correo": "ana@sena.edu.co", "rol": "Comité"},
            {"id_usuario": ID_AUDITOR, "nombre": "Beto", "correo": "beto@sena.edu.co", "rol": "Auditor"},
        ]
        self.requerimientos = requerimientos or []
        self.pendientes = pendientes
        self.rol_comite = rol_comite
        # Usuarios que todavía no son del Comité, tal como los devuelve la consulta.
        self.sin_comite = sin_comite if sin_comite is not None else [
            {"id_usuario": ID_AUDITOR, "nombre": "Beto", "rol": "Auditor"}
        ]
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

        if sql.startswith("SELECT id, id_solicitud"):
            return Resultado(primera={
                "id": ID_APELACION, "id_solicitud": ID_SOLICITUD, "id_empresa": ID_EMPRESA,
                "estado": self.estado, "radicado": "APE-2026-000001", "motivo": "No procede",
                "observaciones": None, "fallo": False, "razones_rechazo": None,
                "fecha": None, "fecha_decision": None, "id_auditor_evaluador": None,
            })
        if sql.startswith("SELECT 1 FROM apelacion_comite"):
            return Resultado(escalar=1)
        # `get_apelacion_by_id` comprueba además que el usuario vea la solicitud.
        if "FROM solicitud" in sql:
            return Resultado(primera={
                "id_solicitud": ID_SOLICITUD, "numero_radicado": "SOL-2026-0002",
                "estado": "RECHAZADO", "id_empresa": ID_EMPRESA, "id_norma": None,
                "alcance_certificacion": None, "deleted_at": None, "observaciones": None,
            }, todas=[{"id_empresa": ID_EMPRESA}])
        if "FROM user_empresa" in sql:
            return Resultado(todas=[{"id_empresa": ID_EMPRESA}], escalar=ID_EMPRESA)
        if sql.startswith("SELECT id_solicitud FROM apelacion"):
            return Resultado(escalar=ID_SOLICITUD)
        if sql.startswith("SELECT DISTINCT id_usuario FROM comite_accion"):
            return Resultado(todas=[(str(ID_EVALUADOR),)])
        if sql.startswith("SELECT ac.id_usuario"):
            return Resultado(todas=[])
        if sql.startswith("SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol"):
            return Resultado(todas=self.elegibles)
        if sql.startswith("SELECT u.id_usuario, COALESCE(u.nombre, u.correo) AS nombre, r.nombre AS rol"):
            return Resultado(todas=self.sin_comite)
        if sql.startswith("SELECT id_rol FROM rol"):
            return Resultado(escalar=self.rol_comite)
        if sql.startswith("SELECT u.id_usuario, COALESCE(u.nombre, u.correo) AS nombre FROM usuario"):
            return Resultado(todas=[{"id_usuario": ID_MIEMBRO, "nombre": "Ana"},
                                    {"id_usuario": ID_AUDITOR, "nombre": "Beto"},
                                    {"id_usuario": ID_EVALUADOR, "nombre": "Leonel"}])
        if sql.startswith("INSERT INTO requerimiento_apelacion"):
            return Resultado(primera={
                "id_requerimiento": uuid.uuid4(), "id_apelacion": ID_APELACION,
                "documentos": (parametros or {}).get("documentos"),
                "observaciones": (parametros or {}).get("observaciones"),
                "estado": "Pendiente", "fecha_solicitud": None,
            })
        if sql.startswith("SELECT r.id_requerimiento"):
            return Resultado(todas=self.requerimientos)
        if sql.startswith("UPDATE requerimiento_apelacion"):
            return Resultado(todas=[(uuid.uuid4(),)] * self.pendientes)
        if sql.startswith("UPDATE apelacion SET estado = 'INFORMACION_SOLICITADA'"):
            return Resultado(primera={"id": ID_APELACION, "estado": "INFORMACION_SOLICITADA",
                                      "observaciones": None})
        if sql.startswith("INSERT INTO evidencia_apelacion"):
            return Resultado(primera={
                "id_evidencia": uuid.uuid4(), "id_apelacion": ID_APELACION,
                "nombre_archivo": (parametros or {}).get("nombre_archivo"),
                "id_usuario": EMPRESA["id_usuario"],
            })
        if sql.startswith("SELECT nextval"):
            return Resultado(escalar=1)
        return Resultado()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def sql_de(self, prefijo: str) -> str:
        return next(sql for sql, _ in self.sentencias if sql.startswith(prefijo))

    def parametros_de(self, prefijo: str) -> dict:
        return next(p for sql, p in self.sentencias if sql.startswith(prefijo))

    def hubo(self, prefijo: str) -> bool:
        return any(sql.startswith(prefijo) for sql, _ in self.sentencias)


# ============================================================
# 1. EL REQUERIMIENTO DE INFORMACIÓN
# ============================================================

async def test_el_requerimiento_se_guarda_aparte_de_las_observaciones():
    """Antes el texto pisaba `apelacion.observaciones`, que es otra cosa."""
    db = BaseFalsa()

    await ApelacionesService(db).solicitar_info_adicional(
        ID_APELACION, "1) Cámara de comercio. 2) Acta del comité de calidad.", COMITE
    )

    parametros = db.parametros_de("INSERT INTO requerimiento_apelacion")
    assert parametros["documentos"].startswith("1) Cámara de comercio")
    assert parametros["estado"] if "estado" in parametros else True
    # La apelación cambia de estado, pero ya no se le escriben las observaciones.
    assert "observaciones = :requerimiento" not in db.sql_de("UPDATE apelacion SET estado")


async def test_el_requerimiento_admite_una_nota_interna():
    db = BaseFalsa()

    await ApelacionesService(db).solicitar_info_adicional(
        ID_APELACION, "Adjunte el acta firmada del comité.", COMITE,
        observaciones="Plazo de cinco días.",
    )

    assert db.parametros_de("INSERT INTO requerimiento_apelacion")["observaciones"] == "Plazo de cinco días."


@pytest.mark.parametrize("texto", ["", "   ", "corto", "123456789"])
async def test_no_se_pide_informacion_sin_decir_que_documentos(texto):
    db = BaseFalsa()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).solicitar_info_adicional(ID_APELACION, texto, COMITE)

    assert error.value.status_code == 400
    assert not db.hubo("INSERT INTO requerimiento_apelacion")


@pytest.mark.parametrize("estado", ["APROBADA", "RECHAZADA", "CANCELADA"])
async def test_no_se_pide_informacion_sobre_una_apelacion_ya_resuelta(estado):
    db = BaseFalsa(estado=estado)

    resultado = await ApelacionesService(db).solicitar_info_adicional(
        ID_APELACION, "Adjunte el acta firmada del comité.", COMITE
    )

    assert resultado is None
    assert not db.hubo("INSERT INTO requerimiento_apelacion")


async def test_se_pueden_consultar_los_requerimientos_hechos():
    db = BaseFalsa(requerimientos=[
        {"id_requerimiento": uuid.uuid4(), "documentos": "Cámara de comercio",
         "observaciones": None, "estado": "Pendiente", "fecha_solicitud": None,
         "fecha_atendido": None, "solicitado_por": "Ana"},
    ])

    requerimientos = await ApelacionesService(db).listar_requerimientos(ID_APELACION, COMITE)

    assert len(requerimientos) == 1
    assert requerimientos[0]["estado"] == "Pendiente"


# ============================================================
# 3. VARIOS DOCUMENTOS DE UNA VEZ
# ============================================================

async def test_se_adjuntan_varios_documentos_en_un_solo_envio():
    db = BaseFalsa()

    resultado = await ApelacionesService(db).add_evidences(
        ID_APELACION,
        [archivo("camara.pdf"), archivo("acta.pdf"), archivo("foto.png")],
        "Respuesta al requerimiento", EMPRESA,
    )

    assert resultado["agregadas"] == 3
    insertados = [p for sql, p in db.sentencias if sql.startswith("INSERT INTO evidencia_apelacion")]
    assert [p["nombre_archivo"] for p in insertados] == ["camara.pdf", "acta.pdf", "foto.png"]


async def test_adjuntar_no_borra_lo_que_ya_estaba():
    """El botón suma: en ningún caso se ejecuta un borrado de evidencias."""
    db = BaseFalsa()

    await ApelacionesService(db).add_evidences(ID_APELACION, [archivo("uno.pdf")], None, EMPRESA)

    assert not db.hubo("DELETE FROM evidencia_apelacion")
    assert not any("UPDATE evidencia_apelacion" in sql for sql, _ in db.sentencias)


async def test_adjuntar_da_por_atendido_el_requerimiento_pendiente():
    db = BaseFalsa(estado="INFORMACION_SOLICITADA", pendientes=1)

    resultado = await ApelacionesService(db).add_evidences(
        ID_APELACION, [archivo("acta.pdf")], None, EMPRESA
    )

    assert resultado["requerimientos_atendidos"] == 1
    assert db.hubo("UPDATE requerimiento_apelacion")
    # Y la apelación vuelve a manos del comité.
    assert any("estado = 'EN_REVISION'" in sql for sql, _ in db.sentencias)


async def test_sin_requerimientos_pendientes_no_se_cambia_el_estado():
    db = BaseFalsa(pendientes=0)

    resultado = await ApelacionesService(db).add_evidences(
        ID_APELACION, [archivo("anexo.pdf")], None, EMPRESA
    )

    assert resultado["requerimientos_atendidos"] == 0
    assert not any("estado = 'EN_REVISION'" in sql for sql, _ in db.sentencias)


async def test_no_se_admite_un_envio_sin_archivos():
    db = BaseFalsa()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).add_evidences(ID_APELACION, [], None, EMPRESA)

    assert error.value.status_code == 400


# ============================================================
# 4. ELEGIBLES Y CAMBIO DE ROL
# ============================================================

async def test_los_elegibles_incluyen_a_los_auditores():
    db = BaseFalsa()

    elegibles = await ApelacionesService(db).comite_elegible(ID_APELACION)

    roles = {e["nombre"]: e["rol_actual"] for e in elegibles}
    assert roles == {"Ana": "Comité", "Beto": "Auditor"}
    consulta = db.sql_de("SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol")
    assert "auditor%" in consulta


async def test_se_avisa_a_quien_hay_que_cambiarle_el_rol():
    db = BaseFalsa()

    elegibles = await ApelacionesService(db).comite_elegible(ID_APELACION)

    por_nombre = {e["nombre"]: e for e in elegibles}
    assert por_nombre["Beto"]["necesita_cambio_de_rol"] is True
    assert por_nombre["Ana"]["necesita_cambio_de_rol"] is False


async def test_asignar_a_un_auditor_le_pasa_el_rol_a_comite():
    db = BaseFalsa()

    resultado = await ApelacionesService(db).assign_committee(ID_APELACION, [ID_AUDITOR])

    assert resultado["cambios_de_rol"] == [{
        "id_usuario": str(ID_AUDITOR),
        "nombre": "Beto",
        "rol_anterior": "Auditor",
        "rol_nuevo": "Comité",
    }]
    parametros = db.parametros_de("UPDATE usuario SET rol_id")
    assert parametros["id_rol"] == ID_ROL_COMITE


async def test_a_quien_ya_es_del_comite_no_se_le_toca_el_rol():
    db = BaseFalsa(sin_comite=[])

    resultado = await ApelacionesService(db).assign_committee(ID_APELACION, [ID_MIEMBRO])

    assert resultado["cambios_de_rol"] == []
    assert not db.hubo("UPDATE usuario SET rol_id")


async def test_si_no_existe_el_rol_comite_no_se_asigna_nada():
    db = BaseFalsa(rol_comite=None)

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_AUDITOR])

    assert error.value.status_code == 409
    assert not db.hubo("INSERT INTO apelacion_comite")


async def test_el_cambio_de_rol_no_alcanza_a_quien_evaluo_la_solicitud():
    """La regla del comité distinto se comprueba antes de tocar ningún rol."""
    db = BaseFalsa()

    with pytest.raises(HTTPException) as error:
        await ApelacionesService(db).assign_committee(ID_APELACION, [ID_EVALUADOR])

    assert error.value.status_code == 409
    assert not db.hubo("UPDATE usuario SET rol_id")
