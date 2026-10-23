"""
M3 — EMPRESAS · seguridad y permisos REQ.

  1. Una cuenta Empresa solo accede a las empresas vinculadas a su usuario.
  2. Lo que la hoja marca REQ para el Auxiliar queda pendiente de aprobación
     y solo se ejecuta cuando lo aprueba un rol con el permiso concedido.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app

ID_EMPRESA = str(uuid.uuid4())
ID_SEDE = str(uuid.uuid4())
ID_CONTACTO = str(uuid.uuid4())
ID_APROBACION = str(uuid.uuid4())

SEDE = {"id_sede": ID_SEDE, "id_empresa": ID_EMPRESA, "nombre_sede": "Bodega", "ciudad": "Manizales", "estado": "Activa"}
CONTACTO = {"id_contacto": ID_CONTACTO, "id_sede": ID_SEDE, "nombre": "Ana Ramírez"}


class Resultado:
    def __init__(self, primera=None, todas=None, escalar=0):
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
    """Responde según el texto de cada consulta y guarda lo que se ejecutó."""

    def __init__(self, estado_empresa="Activa", vinculada=True, aprobacion=None, duplicada=False):
        self.estado_empresa = estado_empresa
        self.vinculada = vinculada
        self.aprobacion = aprobacion
        self.duplicada = duplicada
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        p = parametros or {}
        self.sentencias.append((sql, p))

        if "FROM user_empresa WHERE" in sql:
            return Resultado(primera={"id_user_empresa": "x"} if self.vinculada else None)
        if sql.startswith("SELECT COUNT(*) FROM aprobacion_pendiente"):
            return Resultado(escalar=1 if self.duplicada else 0)
        if sql.startswith("INSERT INTO aprobacion_pendiente"):
            return Resultado(primera={
                "id_aprobacion": ID_APROBACION, "codigo_permiso": p["codigo"], "descripcion": p["descripcion"],
                "detalle": p["detalle"], "id_empresa": p["id_empresa"], "datos": p["datos"],
                "estado": "Pendiente", "id_solicitante": p["id_solicitante"], "fecha_solicitud": None,
            })
        if "FROM aprobacion_pendiente a" in sql:
            return Resultado(primera=self.aprobacion, todas=[self.aprobacion] if self.aprobacion else [])
        if sql.startswith("UPDATE aprobacion_pendiente"):
            return Resultado(primera={**self.aprobacion, "estado": p["estado"], "observacion_revision": p["observacion"]})
        if "FROM solicitud_sede" in sql:
            return Resultado(escalar=0)
        if sql.startswith("UPDATE empresa SET estado"):
            return Resultado(primera={"id_empresa": ID_EMPRESA, "estado": p["estado"]})
        if sql.startswith("UPDATE empresa"):
            return Resultado(primera={"id_empresa": ID_EMPRESA, "nombre": p.get("nombre"), "estado": self.estado_empresa})
        if "FROM empresa" in sql:
            empresa = {"id_empresa": ID_EMPRESA, "nombre": "Empresa de prueba", "estado": self.estado_empresa}
            return Resultado(primera=empresa, todas=[empresa])
        if "sede_empresa" in sql:
            return Resultado(primera=SEDE, todas=[SEDE])
        if "contacto_sede" in sql:
            return Resultado(primera=CONTACTO, todas=[CONTACTO])
        return Resultado()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    def ejecuto(self, prefijo: str) -> bool:
        return any(sql.startswith(prefijo) for sql, _ in self.sentencias)


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"id_usuario": str(uuid.uuid4()), "role_name": rol}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


BASE = f"/api/empresas/{ID_EMPRESA}"


def aprobacion(codigo, datos=None, estado="Pendiente"):
    return {
        "id_aprobacion": ID_APROBACION, "codigo_permiso": codigo, "descripcion": "Acción",
        "detalle": "Detalle", "id_empresa": ID_EMPRESA, "datos": datos or {}, "estado": estado,
        "id_solicitante": str(uuid.uuid4()), "fecha_solicitud": None, "id_revisor": None,
        "fecha_revision": None, "observacion_revision": None,
    }


# ============================================================
# 1. LA EMPRESA SOLO ACCEDE A LO SUYO
# ============================================================

RUTAS_DE_EMPRESA = [
    ("get", "", {}),
    ("put", "", {"json": {"nombre": "X", "nit": "1", "ciudad": "C", "direccion": "D", "correo": "a@b.co"}}),
    ("get", "/solicitudes", {}),
    ("get", "/sedes", {}),
    ("post", "/sedes", {"json": {"nombre_sede": "S", "direccion": "D", "ciudad": "C"}}),
    ("get", f"/sedes/{ID_SEDE}", {}),
    ("put", f"/sedes/{ID_SEDE}", {"json": {"nombre_sede": "Otra"}}),
    ("delete", f"/sedes/{ID_SEDE}", {}),
    ("get", f"/sedes/{ID_SEDE}/contactos", {}),
    ("post", f"/sedes/{ID_SEDE}/contactos", {"json": {"nombre": "Ana Ramírez"}}),
    ("put", f"/sedes/{ID_SEDE}/contactos/{ID_CONTACTO}", {"json": {"cargo": "Jefe"}}),
    ("delete", f"/sedes/{ID_SEDE}/contactos/{ID_CONTACTO}", {}),
    ("get", "/documentos", {}),
]


@pytest.mark.parametrize("metodo,sufijo,extra", RUTAS_DE_EMPRESA)
async def test_la_empresa_no_accede_a_una_empresa_ajena(metodo, sufijo, extra):
    db = BaseFalsa(vinculada=False)

    respuesta = await pedir(db, "Empresa", metodo, BASE + sufijo, **extra)

    assert respuesta.status_code == 404
    # Se corta antes de leer o tocar nada de la empresa ajena.
    assert [sql for sql, _ in db.sentencias if "user_empresa" not in sql] == []


@pytest.mark.parametrize("metodo,sufijo,extra", RUTAS_DE_EMPRESA)
async def test_la_empresa_si_accede_a_la_suya(metodo, sufijo, extra):
    respuesta = await pedir(BaseFalsa(vinculada=True), "Empresa", metodo, BASE + sufijo, **extra)
    assert respuesta.status_code in (200, 201)


async def test_un_id_invalido_no_llega_a_la_base():
    db = BaseFalsa()
    respuesta = await pedir(db, "Empresa", "get", "/api/empresas/no-es-un-uuid")
    assert respuesta.status_code == 404
    assert db.sentencias == []


@pytest.mark.parametrize("rol", ["Administrador", "Auxiliar", "Auditor", "Comité"])
async def test_los_demas_roles_no_dependen_del_vinculo(rol):
    db = BaseFalsa(vinculada=False)

    respuesta = await pedir(db, rol, "get", BASE)

    assert respuesta.status_code == 200
    assert not any("user_empresa" in sql for sql, _ in db.sentencias)


# ============================================================
# 2. PERMISOS REQ: EL AUXILIAR SOLICITA, UN SUPERIOR APRUEBA
# ============================================================

ACCIONES_REQ = [
    ("EMP-006", "patch", "/estado", {"json": {"estado": "Suspendida"}}, "Activa"),
    ("EMP-007", "post", "/inactivar", {}, "Activa"),
    ("EMP-008", "post", "/reactivar", {}, "Inactiva"),
    ("EMP-023", "delete", f"/sedes/{ID_SEDE}", {}, "Activa"),
    ("EMP-029", "delete", f"/sedes/{ID_SEDE}/contactos/{ID_CONTACTO}", {}, "Activa"),
]


@pytest.mark.parametrize("codigo,metodo,sufijo,extra,estado_empresa", ACCIONES_REQ)
async def test_el_auxiliar_solicita_en_vez_de_ejecutar(codigo, metodo, sufijo, extra, estado_empresa):
    db = BaseFalsa(estado_empresa=estado_empresa)

    respuesta = await pedir(db, "Auxiliar", metodo, BASE + sufijo, **extra)

    assert respuesta.status_code == 202, respuesta.text
    assert respuesta.json()["aprobacion"]["codigo_permiso"] == codigo
    assert db.ejecuto("INSERT INTO aprobacion_pendiente")
    assert not db.ejecuto("UPDATE empresa")
    assert not db.ejecuto("DELETE")


async def test_no_se_duplica_una_solicitud_pendiente():
    db = BaseFalsa(duplicada=True)

    respuesta = await pedir(db, "Auxiliar", "post", f"{BASE}/inactivar")

    assert respuesta.status_code == 409
    assert not db.ejecuto("INSERT INTO aprobacion_pendiente")


async def test_la_solicitud_se_valida_antes_de_registrarse():
    db = BaseFalsa(estado_empresa="Inactiva")

    respuesta = await pedir(db, "Auxiliar", "post", f"{BASE}/inactivar")

    assert respuesta.status_code == 409
    assert not db.ejecuto("INSERT INTO aprobacion_pendiente")


async def test_el_administrador_aprueba_y_la_accion_se_ejecuta():
    db = BaseFalsa(aprobacion=aprobacion("EMP-007"))

    respuesta = await pedir(db, "Administrador", "post", f"/api/aprobaciones/{ID_APROBACION}/aprobar")

    assert respuesta.status_code == 200, respuesta.text
    assert [p["estado"] for sql, p in db.sentencias if sql.startswith("UPDATE empresa")] == ["Inactiva"]
    assert respuesta.json()["aprobacion"]["estado"] == "Aprobada"


@pytest.mark.parametrize("rol,esperado", [("Administrador", 403), ("Super Administrador", 200)])
async def test_solo_el_superadministrador_aprueba_una_reactivacion(rol, esperado):
    db = BaseFalsa(estado_empresa="Inactiva", aprobacion=aprobacion("EMP-008"))

    respuesta = await pedir(db, rol, "post", f"/api/aprobaciones/{ID_APROBACION}/aprobar")

    assert respuesta.status_code == esperado
    assert db.ejecuto("UPDATE empresa") is (esperado == 200)


async def test_aprobar_eliminar_sede_ejecuta_el_borrado():
    db = BaseFalsa(aprobacion=aprobacion("EMP-023", {"id_sede": ID_SEDE}))

    respuesta = await pedir(db, "Administrador", "post", f"/api/aprobaciones/{ID_APROBACION}/aprobar")

    assert respuesta.status_code == 200
    assert db.ejecuto("DELETE FROM sede_empresa")


@pytest.mark.parametrize("rol", ["Auxiliar", "Empresa", "Auditor"])
async def test_quien_solicita_no_puede_aprobar(rol):
    db = BaseFalsa(aprobacion=aprobacion("EMP-007"))
    respuesta = await pedir(db, rol, "post", f"/api/aprobaciones/{ID_APROBACION}/aprobar")
    assert respuesta.status_code == 403


async def test_no_se_aprueba_dos_veces():
    db = BaseFalsa(aprobacion=aprobacion("EMP-007", estado="Aprobada"))

    respuesta = await pedir(db, "Administrador", "post", f"/api/aprobaciones/{ID_APROBACION}/aprobar")

    assert respuesta.status_code == 409
    assert not db.ejecuto("UPDATE empresa")


async def test_rechazar_exige_motivo_y_no_ejecuta_la_accion():
    db = BaseFalsa(aprobacion=aprobacion("EMP-007"))
    ruta = f"/api/aprobaciones/{ID_APROBACION}/rechazar"

    assert (await pedir(db, "Administrador", "post", ruta, json={})).status_code == 422

    respuesta = await pedir(db, "Administrador", "post", ruta, json={"observacion": "No hay soporte suficiente"})

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "Rechazada"
    assert not db.ejecuto("UPDATE empresa")


@pytest.mark.parametrize("rol,filtra", [("Auxiliar", True), ("Administrador", False)])
async def test_el_auxiliar_solo_ve_sus_solicitudes(rol, filtra):
    db = BaseFalsa(aprobacion=aprobacion("EMP-007"))

    respuesta = await pedir(db, rol, "get", "/api/aprobaciones/", params={"estado": "Pendiente"})

    assert respuesta.status_code == 200
    [(sql, _)] = db.sentencias
    assert ("a.id_solicitante = :id_usuario" in sql) is filtra
