"""
Permisos delegados por el Administrador al Auxiliar (modules/permisos_auxiliar).

  · Solo el Administrador otorga y revoca.
  · Un auxiliar con el permiso vigente ejecuta directo una acción REQ.
  · Sin permiso, la acción REQ sigue quedando pendiente de aprobación (202).
  · Un permiso vencido o revocado no vale; un no-auxiliar nunca obtiene True.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.aprobaciones import aprobacion_service
from modules.permisos_auxiliar import permisos_auxiliar_service as servicio
from modules.permisos_auxiliar.permisos_auxiliar_service import (
    PermisosAuxiliarService,
    auxiliar_tiene_permiso,
    permiso_es_vigente,
    permisos_delegables,
    registrar_permiso_delegable,
)

ID_EMPRESA = str(uuid.uuid4())
ID_AUXILIAR = str(uuid.uuid4())
HOY = date(2026, 11, 4)


# ============================================================
# DOBLES
# ============================================================

class SesionFalsa(AsyncSession):
    """AsyncSession sin base: devuelve las filas indicadas para cada SELECT."""

    def __init__(self, filas: list[dict]):
        super().__init__()
        self.filas = filas
        self.consultas: list[str] = []

    @asynccontextmanager
    async def _savepoint(self):
        yield self

    def begin_nested(self):  # type: ignore[override]
        return self._savepoint()

    async def execute(self, sentencia, parametros=None, **_):  # type: ignore[override]
        self.consultas.append(str(sentencia))
        resultado = MagicMock()
        resultado.mappings().all.return_value = list(self.filas)
        resultado.mappings().first.return_value = self.filas[0] if self.filas else None
        return resultado


def fila_permiso(**cambios) -> dict:
    base = {
        "id_permiso": 7,
        "activo": True,
        "fecha_vencimiento": None,
        "fecha_revocado": None,
        "estado_usuario": "Activo",
        "role_name": "Auxiliar",
    }
    return {**base, **cambios}


def sesion_http(registro: dict) -> AsyncMock:
    resultado = MagicMock()
    resultado.mappings().all.return_value = [registro]
    resultado.mappings().first.return_value = registro
    resultado.scalar.return_value = 0
    db = AsyncMock()
    db.execute.return_value = resultado
    return db


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": ID_AUXILIAR,
        "role_name": rol,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


def sentencias(db) -> list[str]:
    return [" ".join(str(llamada.args[0]).split()) for llamada in db.execute.call_args_list]


# ============================================================
# REGLA DE VIGENCIA
# ============================================================

def test_permiso_activo_sin_vencimiento_vale():
    assert permiso_es_vigente(fila_permiso(), HOY) is True


def test_permiso_vale_hasta_el_dia_de_vencimiento_inclusive():
    assert permiso_es_vigente(fila_permiso(fecha_vencimiento=HOY), HOY) is True
    assert permiso_es_vigente(fila_permiso(fecha_vencimiento=HOY - timedelta(days=1)), HOY) is False


@pytest.mark.parametrize(
    "cambios",
    [
        {"activo": False},
        {"fecha_revocado": "2026-11-01 10:00:00"},
        {"estado_usuario": "Inactivo"},
        {"role_name": "Administrador"},
        {"role_name": "Empresa"},
        {"role_name": None},
    ],
)
def test_revocado_inactivo_o_no_auxiliar_no_vale(cambios):
    assert permiso_es_vigente(fila_permiso(**cambios), HOY) is False


def test_sin_fila_no_vale():
    assert permiso_es_vigente(None, HOY) is False


# ============================================================
# auxiliar_tiene_permiso
# ============================================================

async def test_auxiliar_con_permiso_vigente_obtiene_true():
    assert await auxiliar_tiene_permiso(SesionFalsa([fila_permiso()]), ID_AUXILIAR, "EMP-007") is True


async def test_permiso_vencido_no_vale(monkeypatch):
    monkeypatch.setattr(servicio, "_hoy", lambda: HOY)
    vencido = fila_permiso(fecha_vencimiento=HOY - timedelta(days=3))
    assert await auxiliar_tiene_permiso(SesionFalsa([vencido]), ID_AUXILIAR, "EMP-007") is False


async def test_sin_permiso_otorgado_obtiene_false():
    assert await auxiliar_tiene_permiso(SesionFalsa([]), ID_AUXILIAR, "EMP-007") is False


@pytest.mark.parametrize("rol", ["Administrador", "Super Administrador", "Empresa", "Auditor", "Comité"])
async def test_un_no_auxiliar_nunca_obtiene_true(rol):
    sesion = SesionFalsa([fila_permiso(role_name=rol)])
    assert await auxiliar_tiene_permiso(sesion, ID_AUXILIAR, "EMP-007") is False


async def test_un_doble_que_no_es_sesion_real_nunca_concede():
    # Ni siquiera llega a consultar (y no deja corrutinas sin esperar).
    db = AsyncMock()
    assert await auxiliar_tiene_permiso(db, ID_AUXILIAR, "EMP-007") is False
    db.execute.assert_not_called()
    db.begin_nested.assert_not_called()


async def test_si_la_consulta_falla_no_concede():
    class SesionRota(SesionFalsa):
        async def execute(self, *a, **k):
            raise RuntimeError("tabla inexistente")

    assert await auxiliar_tiene_permiso(SesionRota([]), ID_AUXILIAR, "EMP-007") is False


# ============================================================
# CATÁLOGO
# ============================================================

def test_catalogo_incluye_req_de_la_matriz_y_los_nuevos():
    codigos = {p["codigo"] for p in permisos_delegables()}
    for codigo in ("EMP-006", "EMP-007", "SOL-048", "AUT-057", "CER-015", "USR-CORREO", "USR-CLAVE", "PQR-005"):
        assert codigo in codigos


def test_registrar_mantiene_el_grupo_por_prefijo():
    registrar_permiso_delegable("USR-CLAVE", "Restablecer contraseña", "Usuarios")
    item = next(p for p in permisos_delegables() if p["codigo"] == "USR-CLAVE")
    assert item["modulo"].startswith("M2")


def test_catalogo_ordenado_por_numero_de_modulo():
    modulos = []
    for p in permisos_delegables():
        if p["modulo"] not in modulos:
            modulos.append(p["modulo"])
    assert modulos.index("M2 — Gestión de usuarios") < modulos.index("M10 — Apelaciones")


# ============================================================
# API: SOLO EL ADMINISTRADOR OTORGA Y REVOCA
# ============================================================

OTORGAR = f"/api/permisos-auxiliar/auxiliares/{ID_AUXILIAR}/otorgar"
REVOCAR = f"/api/permisos-auxiliar/auxiliares/{ID_AUXILIAR}/revocar/EMP-007"


@pytest.fixture
def servicio_espiado(monkeypatch):
    llamadas = []

    async def otorgar(self, id_usuario, codigo, motivo, vence, admin):
        llamadas.append(("otorgar", codigo, motivo, vence))
        return {"codigo_permiso": codigo, "activo": True}

    async def revocar(self, id_usuario, codigo, motivo, admin):
        llamadas.append(("revocar", codigo, motivo))
        return {"codigo_permiso": codigo, "activo": False}

    monkeypatch.setattr(PermisosAuxiliarService, "otorgar", otorgar)
    monkeypatch.setattr(PermisosAuxiliarService, "revocar", revocar)
    return llamadas


@pytest.mark.parametrize("rol", ["Auxiliar", "Empresa", "Auditor", "Comité", "Super Administrador"])
async def test_otorgar_y_revocar_rechazan_a_quien_no_es_administrador(rol, servicio_espiado):
    cuerpo = {"codigo_permiso": "EMP-007", "motivo": "Cubre vacaciones"}
    assert (await pedir(AsyncMock(), rol, "post", OTORGAR, json=cuerpo)).status_code == 403
    assert (await pedir(AsyncMock(), rol, "post", REVOCAR, json={"motivo": "Ya no aplica"})).status_code == 403
    assert servicio_espiado == []


async def test_el_administrador_otorga_y_revoca(servicio_espiado):
    cuerpo = {"codigo_permiso": "EMP-007", "motivo": "Cubre vacaciones", "fecha_vencimiento": "2099-01-31"}
    respuesta = await pedir(AsyncMock(), "Administrador", "post", OTORGAR, json=cuerpo)
    assert respuesta.status_code == 201
    respuesta = await pedir(AsyncMock(), "Administrador", "post", REVOCAR, json={"motivo": "Regresó el titular"})
    assert respuesta.status_code == 200
    assert servicio_espiado == [
        ("otorgar", "EMP-007", "Cubre vacaciones", date(2099, 1, 31)),
        ("revocar", "EMP-007", "Regresó el titular"),
    ]


async def test_otorgar_exige_motivo(servicio_espiado):
    respuesta = await pedir(AsyncMock(), "Administrador", "post", OTORGAR, json={"codigo_permiso": "EMP-007", "motivo": ""})
    assert respuesta.status_code == 422
    assert servicio_espiado == []


@pytest.mark.parametrize("rol", ["Auxiliar", "Empresa"])
async def test_catalogo_auxiliares_e_historial_son_solo_del_administrador(rol):
    for ruta in ("/catalogo", "/auxiliares", "/historial", f"/auxiliares/{ID_AUXILIAR}"):
        respuesta = await pedir(AsyncMock(), rol, "get", "/api/permisos-auxiliar" + ruta)
        assert respuesta.status_code == 403, ruta


async def test_el_auxiliar_consulta_sus_permisos(monkeypatch):
    async def mios(self, usuario):
        return [{"codigo_permiso": "EMP-007", "descripcion": "Inactivar empresa"}]

    monkeypatch.setattr(PermisosAuxiliarService, "mios", mios)
    respuesta = await pedir(AsyncMock(), "Auxiliar", "get", "/api/permisos-auxiliar/mios")
    assert respuesta.status_code == 200
    assert respuesta.json()["codigos"] == ["EMP-007"]


async def test_otorgar_rechaza_codigo_fuera_del_catalogo():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await PermisosAuxiliarService(AsyncMock()).otorgar(
            ID_AUXILIAR, "SOL-001", "Motivo válido", None, {"id_usuario": str(uuid.uuid4())}
        )
    assert error.value.status_code == 400


# ============================================================
# INTEGRACIÓN CON EL FLUJO REQ (M3: EMP-007 inactivar empresa)
# ============================================================

def registro_empresa() -> dict:
    return {
        "id_empresa": ID_EMPRESA,
        "nombre": "Cafe del Eje",
        "estado": "Activa",
        "id_aprobacion": str(uuid.uuid4()),
        "codigo_permiso": "EMP-007",
        "descripcion": "Inactivar empresa",
        "detalle": "Inactivar Cafe del Eje",
        "datos": "{}",
        "id_solicitante": ID_AUXILIAR,
    }


def _con_permiso(monkeypatch, concedido: bool):
    llamadas = []

    async def falso(session, id_usuario, codigo):
        llamadas.append((str(id_usuario), codigo))
        return concedido

    monkeypatch.setattr(aprobacion_service, "auxiliar_tiene_permiso", falso)
    return llamadas


async def test_auxiliar_con_permiso_ejecuta_directo_la_accion_req(monkeypatch):
    llamadas = _con_permiso(monkeypatch, True)
    db = sesion_http(registro_empresa())

    respuesta = await pedir(db, "Auxiliar", "post", f"/api/empresas/{ID_EMPRESA}/inactivar")

    assert respuesta.status_code == 200
    assert respuesta.headers.get("X-Permiso-Delegado") == "EMP-007"
    assert llamadas == [(ID_AUXILIAR, "EMP-007")]
    sql = sentencias(db)
    assert any(s.startswith("UPDATE empresa SET estado") for s in sql)
    # Queda en el historial de aprobaciones como aprobada por permiso delegado.
    cierre = [c for c in db.execute.call_args_list if "UPDATE aprobacion_pendiente" in str(c.args[0])]
    assert cierre and cierre[0].args[1]["estado"] == "Aprobada"
    assert "permiso delegado" in cierre[0].args[1]["observacion"]


async def test_auxiliar_sin_permiso_sigue_creando_aprobacion(monkeypatch):
    _con_permiso(monkeypatch, False)
    db = sesion_http(registro_empresa())

    respuesta = await pedir(db, "Auxiliar", "post", f"/api/empresas/{ID_EMPRESA}/inactivar")

    assert respuesta.status_code == 202
    sql = sentencias(db)
    assert any(s.startswith("INSERT INTO aprobacion_pendiente") for s in sql)
    assert not any(s.startswith("UPDATE empresa SET estado") for s in sql)
    assert not any("UPDATE aprobacion_pendiente" in s for s in sql)


async def test_si_la_accion_delegada_falla_no_queda_nada(monkeypatch):
    _con_permiso(monkeypatch, True)
    from fastapi import HTTPException

    async def falla(db, aprobacion):
        raise HTTPException(status_code=409, detail="La empresa ya está inactiva.")

    definicion = aprobacion_service.obtener_accion("EMP-007")
    monkeypatch.setitem(
        aprobacion_service._ACCIONES, "EMP-007",
        aprobacion_service.AccionAprobable(definicion.codigo, definicion.descripcion, definicion.aprobadores, falla),
    )
    db = sesion_http(registro_empresa())

    respuesta = await pedir(db, "Auxiliar", "post", f"/api/empresas/{ID_EMPRESA}/inactivar")

    assert respuesta.status_code == 409
    db.rollback.assert_awaited()
    db.commit.assert_not_awaited()


async def test_el_administrador_no_pasa_por_el_permiso_delegado(monkeypatch):
    llamadas = _con_permiso(monkeypatch, True)
    db = sesion_http(registro_empresa())

    respuesta = await pedir(db, "Administrador", "post", f"/api/empresas/{ID_EMPRESA}/inactivar")

    assert respuesta.status_code == 200
    assert llamadas == []
