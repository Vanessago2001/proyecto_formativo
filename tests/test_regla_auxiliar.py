"""
Regla del Auxiliar (decisión del equipo): "Los permisos del auxiliar deben ser
puestos exclusivamente por el Coordinador."

  · regla central (modules/permisos_auxiliar/regla_auxiliar.py)
  · matrices M5, M7 y M9 y chequeos de rol directos pasan por ella
  · catálogo completo de delegables (V, REQ y Cond. de la columna AUX)
  · get_current_user carga los permisos delegados vigentes
  · menú (static/nav.js) y botones con data-permiso-aux

Sin base real: todo con dobles.
"""

import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.database import get_db
from core.security import create_access_token, get_current_user, require_role
from modules.permisos_auxiliar import permisos_auxiliar_service as servicio
from modules.permisos_auxiliar.permisos_auxiliar_catalogo import CATALOGO_BASE, NO_DELEGABLES
from modules.permisos_auxiliar.regla_auxiliar import (
    MENSAJE_SIN_PERMISO,
    PROPIO,
    con_aprobacion,
    delegable,
    exigir_permiso_auxiliar,
    nivel_efectivo,
    tiene_delegado,
)
from modules.solicitudes.solicitud_permissions import COLUMNAS_MATRIZ, NivelPermiso, PERMISOS_M5

RAIZ = Path(__file__).resolve().parent.parent
AUX = {"id_usuario": str(uuid.uuid4()), "role_name": "Auxiliar"}


def aux(*codigos):
    return {**AUX, "permisos_delegados": tuple(codigos)}


# ============================================================
# 1. LA REGLA CENTRAL
# ============================================================

@pytest.mark.parametrize("nivel", [NivelPermiso.CONCEDIDO, "V", "Cond."])
def test_v_y_cond_sin_permiso_delegado_es_403_con_el_aviso(nivel):
    with pytest.raises(HTTPException) as error:
        nivel_efectivo(aux(), "SOL-006", nivel)
    assert error.value.status_code == 403
    assert error.value.detail.startswith(MENSAJE_SIN_PERMISO)
    assert "SOL-006" in error.value.detail


def test_v_con_permiso_delegado_queda_permitido():
    assert nivel_efectivo(aux("SOL-006"), "SOL-006", NivelPermiso.CONCEDIDO) is NivelPermiso.CONCEDIDO


def test_otro_codigo_delegado_no_sirve():
    with pytest.raises(HTTPException):
        nivel_efectivo(aux("SOL-007"), "SOL-006", NivelPermiso.CONCEDIDO)


@pytest.mark.parametrize("delegados", [(), ("SOL-054",)])
def test_req_sin_cambio(delegados):
    """REQ sigue igual: sin permiso va a aprobación; con él, el flujo REQ lo ejecuta directo."""
    assert nivel_efectivo(aux(*delegados), "SOL-054", NivelPermiso.REQUIERE_APROBACION) is NivelPermiso.REQUIERE_APROBACION


@pytest.mark.parametrize("nivel", [NivelPermiso.DENEGADO, NivelPermiso.SOLO_SUPERADMIN])
def test_f_sigue_f_aunque_tenga_el_codigo(nivel):
    assert nivel_efectivo(aux("SOL-001"), "SOL-001", nivel) is nivel


@pytest.mark.parametrize("rol", ["Coordinador", "Empresa", "Auditor", "Comité"])
def test_los_demas_roles_no_cambian(rol):
    usuario = {"role_name": rol}
    assert nivel_efectivo(usuario, "SOL-006", NivelPermiso.CONCEDIDO) is NivelPermiso.CONCEDIDO
    exigir_permiso_auxiliar(usuario, "EMP-003")  # no lanza


def test_sin_la_clave_de_permisos_el_auxiliar_no_tiene_nada():
    assert not tiene_delegado(AUX, "SOL-006")
    with pytest.raises(HTTPException):
        exigir_permiso_auxiliar(AUX, "SOL-006")


def test_exigir_basta_uno_de_los_codigos():
    exigir_permiso_auxiliar(aux("EMP-005"), "EMP-003", "EMP-004", "EMP-005")
    with pytest.raises(HTTPException):
        exigir_permiso_auxiliar(aux("EMP-001"), "EMP-003", "EMP-004")


# ============================================================
# 2. MATRICES M5, M7 Y M9 PASAN POR LA REGLA
# ============================================================

async def _verificar(fabrica, codigo, usuario, **extra):
    dependencia = fabrica(codigo)
    if "db" in dependencia.__code__.co_varnames[: dependencia.__code__.co_argcount]:
        return await dependencia(current_user=dict(usuario), db=MagicMock())
    return await dependencia(current_user=dict(usuario))


@pytest.mark.parametrize("modulo,codigo", [
    ("modules.solicitudes.solicitud_permissions", "SOL-006"),
    ("modules.auditorias.auditoria_permissions", "AUT-051"),
    ("modules.certificados.certificados_permissions", "CER-011"),
])
async def test_requiere_permiso_de_cada_matriz(modulo, codigo):
    import importlib

    fabrica = importlib.import_module(modulo).requiere_permiso
    with pytest.raises(HTTPException) as error:
        await _verificar(fabrica, codigo, aux())
    assert error.value.status_code == 403
    assert MENSAJE_SIN_PERMISO in error.value.detail
    assert await _verificar(fabrica, codigo, aux(codigo))
    assert await _verificar(fabrica, codigo, {"role_name": "Coordinador"})


@pytest.mark.parametrize("modulo,codigo", [
    ("modules.solicitudes.solicitud_permissions", "SOL-021"),
    ("modules.auditorias.auditoria_permissions", "AUT-001"),
])
async def test_f_del_auxiliar_sigue_siendo_403_de_la_matriz(modulo, codigo):
    import importlib

    with pytest.raises(HTTPException) as error:
        await _verificar(importlib.import_module(modulo).requiere_permiso, codigo, aux(codigo))
    assert "denegado" in error.value.detail


def test_exigir_permisos_de_m5_y_m7_aplica_la_regla():
    from modules.auditorias.auditoria_permissions import exigir_permisos as exigir_m7
    from modules.solicitudes.solicitud_permissions import exigir_permisos as exigir_m5

    with pytest.raises(HTTPException):
        exigir_m5(aux(), "SOL-042")
    exigir_m5(aux("SOL-042"), "SOL-042")
    with pytest.raises(HTTPException):
        exigir_m7(aux("AUT-003"), "AUT-003", "AUT-004")
    exigir_m7(aux("AUT-003", "AUT-004"), "AUT-003", "AUT-004")


async def test_req_de_m5_sigue_llegando_al_flujo_de_aprobacion():
    from modules.solicitudes.solicitud_permissions import requiere_permiso

    usuario = await requiere_permiso("SOL-054")(current_user=dict(aux()))
    assert usuario["permiso_nivel"] == "REQ"


# ============================================================
# 3. CHEQUEOS DE ROL DIRECTOS
# ============================================================

def _app_rol(*args, **kwargs):
    app = FastAPI()

    @app.get("/x")
    async def ruta(usuario: dict = Depends(require_role(*args, **kwargs))):
        return {"ok": True}

    return app


def _get(app, usuario):
    app.dependency_overrides[get_current_user] = lambda: usuario
    return TestClient(app).get("/x")


def test_require_role_sin_codigo_no_deja_pasar_al_auxiliar():
    app = _app_rol(["admin", "auxiliar"])
    assert _get(app, aux("EMP-003")).status_code == 403
    assert _get(app, {"role_name": "Coordinador"}).status_code == 200


def test_require_role_con_codigo_delegable():
    app = _app_rol(["admin", "auxiliar"], auxiliar=delegable("EMP-003", "EMP-004"))
    respuesta = _get(app, aux())
    assert respuesta.status_code == 403
    assert MENSAJE_SIN_PERMISO in respuesta.json()["detail"]
    assert _get(app, aux("EMP-004")).status_code == 200


@pytest.mark.parametrize("regla", [con_aprobacion("EMP-006"), PROPIO])
def test_req_y_propio_dejan_pasar_al_auxiliar(regla):
    assert _get(_app_rol(["admin", "auxiliar"], auxiliar=regla), aux()).status_code == 200


def _dependencias(dependant, salida):
    for sub in dependant.dependencies:
        salida.append(sub.call)
        _dependencias(sub, salida)
    return salida


def _rutas(rutas):
    for ruta in rutas:
        if hasattr(ruta, "original_router"):
            yield from _rutas(ruta.original_router.routes)
        elif hasattr(ruta, "dependant"):
            yield ruta


def test_toda_ruta_que_admite_al_auxiliar_por_rol_declara_su_permiso():
    """Ninguna ruta con require_role que incluya al Auxiliar queda sin código."""
    from main import app

    sin_codigo = []
    for ruta in _rutas(app.routes):
        for llamada in _dependencias(ruta.dependant, []):
            if getattr(llamada, "__qualname__", "") != "require_role.<locals>.role_dependency":
                continue
            celdas = dict(zip(llamada.__code__.co_freevars, (c.cell_contents for c in llamada.__closure__)))
            if "auxiliar" in celdas.get("roles_lower", set()) and celdas.get("auxiliar") is None:
                sin_codigo.append(f"{sorted(ruta.methods)} {ruta.path}")
    assert sin_codigo == []


def test_no_quedan_chequeos_administrativos_sin_codigo():
    """es_rol_administrativo / require_self_or_admin sin código ya no habilitan al Auxiliar."""
    from modules.auth.dependencies import es_rol_administrativo

    assert es_rol_administrativo({"role_name": "Coordinador"})
    assert not es_rol_administrativo(aux("AUD-033"))
    assert es_rol_administrativo(aux("AUD-033"), "AUD-033")
    # dependencies.py define estas ayudas (sin código = solo el Coordinador).
    fuentes = [
        p for p in (RAIZ / "modules").rglob("*.py")
        if "permisos_auxiliar" not in str(p) and p.name != "dependencies.py"
    ]
    usos = []
    for archivo in fuentes:
        texto = archivo.read_text(encoding="utf-8")
        usos += [f"{archivo.name}: {m}" for m in re.findall(r"es_rol_administrativo\((?:current_user|usuario)\)", texto)]
        usos += [f"{archivo.name}: Depends(require_self_or_admin)" for _ in re.findall(r"Depends\(require_self_or_admin\)", texto)]
        usos += [f"{archivo.name}: Depends(require_admin_access)" for _ in re.findall(r"Depends\(require_admin_access\)", texto)]
    assert usos == []


# Un Auxiliar sin ningún permiso: 403 claro en cada módulo, antes de tocar la base.
RUTAS_AUXILIAR = [
    "/api/empresas/",
    "/comite/expedientes-pendientes",
    "/api/reportes/estadistico-empresas",
    "/api/apelaciones/",
    "/administradores/auditores/solicitudes",
    "/admin/auditores-registrados",
    "/asignacion-auditores/solicitudes",
    "/asignacion-auditores/conteo-etapas",
    "/solicitudes/",
    "/certificados/",
    "/auditorias/historial",
    "/auth/historial-accesos",
    "/conflictos-auditor/empresas-restringidas",
    "/agenda-auditor/bloqueos/vigentes",
]


@pytest.mark.parametrize("ruta", RUTAS_AUXILIAR)
def test_auxiliar_sin_permisos_recibe_403_en_cada_modulo(ruta):
    from main import app

    db = MagicMock()
    db.execute.side_effect = AssertionError("No debe consultar la base")

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: dict(AUX)
    app.dependency_overrides[get_db] = _db
    try:
        respuesta = TestClient(app).get(ruta)
    finally:
        app.dependency_overrides.clear()
    assert respuesta.status_code == 403, ruta
    assert MENSAJE_SIN_PERMISO in respuesta.json()["detail"], ruta


def test_catalogo_de_reportes_del_auxiliar_sin_permisos_esta_vacio():
    from main import app

    app.dependency_overrides[get_current_user] = lambda: dict(AUX)
    try:
        assert TestClient(app).get("/api/reportes").json() == []
    finally:
        app.dependency_overrides.clear()


# ============================================================
# 4. get_current_user CARGA LOS PERMISOS DELEGADOS VIGENTES
# ============================================================

class _Fila:
    def __init__(self, fila):
        self.fila = fila

    def mappings(self):
        return self

    def first(self):
        return self.fila


class _Sesion:
    def __init__(self, rol):
        self.rol = rol

    async def execute(self, *_a, **_k):
        return _Fila({"id_usuario": AUX["id_usuario"], "nombre": "Aux", "correo": "a@x.co",
                      "estado": "Activo", "rol_id": 3, "role_name": self.rol})


@pytest.mark.parametrize("rol,esperado", [("Auxiliar", ("EMP-003", "SOL-006")), ("Coordinador", None)])
async def test_get_current_user_carga_los_codigos_del_auxiliar(monkeypatch, rol, esperado):
    async def _codigos(_db, id_usuario):
        assert id_usuario == AUX["id_usuario"]
        return ("EMP-003", "SOL-006")

    monkeypatch.setattr(servicio, "codigos_vigentes", _codigos)
    token = create_access_token({"sub": "aux", "user_id": AUX["id_usuario"]})
    usuario = await get_current_user(token=token, db=_Sesion(rol))
    assert usuario.get("permisos_delegados") == esperado


async def test_codigos_vigentes_con_un_doble_no_concede_nada():
    assert await servicio.codigos_vigentes(MagicMock(), AUX["id_usuario"]) == ()


# ============================================================
# 5. CATÁLOGO COMPLETO DE DELEGABLES
# ============================================================

def _hoja_permisos():
    """Filas (código, permiso, AUX) de la hoja "permisos" (sin openpyxl)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(RAIZ / "documentacion" / "permisos.xlsx") as z:
        cadenas = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
                   for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        rel = {r.get("Id"): r.get("Target").lstrip("/") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        destino = next(rel[h.get(f"{{{ns['r']}}}id")] for h in libro.find("m:sheets", ns) if h.get("name") == "permisos")
        destino = destino if destino.startswith("xl/") else f"xl/{destino}"
        filas = []
        for fila in ET.fromstring(z.read(destino)).iter(f"{{{ns['m']}}}row"):
            celdas = {}
            for c in fila.findall("m:c", ns):
                columna = re.match(r"[A-Z]+", c.get("r")).group(0)
                v = c.find("m:v", ns)
                if v is None:
                    t = c.find("m:is/m:t", ns)
                    valor = t.text if t is not None else ""
                else:
                    valor = cadenas[int(v.text)] if c.get("t") == "s" else v.text
                celdas[columna] = (valor or "").strip()
            if re.match(r"^[A-Z]{3}-\d{3}$", celdas.get("B", "")):
                filas.append((celdas["B"], celdas.get("C", ""), celdas.get("F", "").upper()))
        return filas


def test_el_catalogo_tiene_todo_lo_que_el_auxiliar_podria_tener_segun_la_hoja():
    catalogo = {p["codigo"]: p for p in servicio.permisos_delegables()}
    faltan, sobran = [], []
    for codigo, _permiso, aux_celda in _hoja_permisos():
        delegable_hoja = aux_celda != "F" and not codigo.startswith("PUB-") and codigo not in NO_DELEGABLES
        if delegable_hoja and codigo not in catalogo:
            faltan.append(codigo)
        if not delegable_hoja and codigo in catalogo:
            sobran.append(codigo)
        if delegable_hoja and codigo in catalogo:
            assert catalogo[codigo]["nivel"] == aux_celda, codigo
    assert faltan == []
    assert sobran == []


def test_el_catalogo_cubre_las_matrices_en_codigo_y_pqrs():
    from modules.auditorias.auditoria_permissions import PERMISOS_M7
    from modules.certificados.certificados_permissions import PERMISOS_M9
    from modules.pqrs.pqrs_reglas import COND, PERMISOS_PQR

    columna = COLUMNAS_MATRIZ.index("AUX")
    for matriz in (PERMISOS_M5, PERMISOS_M7, PERMISOS_M9):
        for codigo, (_d, valores) in matriz.items():
            assert servicio.es_delegable(codigo) == (valores[columna].value in ("V", "REQ")), codigo
    for codigo, (_d, valores) in PERMISOS_PQR.items():
        if valores[columna] == COND:
            assert servicio.es_delegable(codigo), codigo
    assert servicio.es_delegable("USR-CORREO") and servicio.es_delegable("USR-CLAVE")


def test_el_catalogo_va_agrupado_por_modulo_con_descripcion():
    from modules.permisos_auxiliar.permisos_auxiliar_router import catalogo

    import asyncio

    respuesta = asyncio.run(catalogo({"role_name": "Coordinador"}))
    modulos = [m["modulo"] for m in respuesta["modulos"]]
    assert modulos[:3] == ["M1 — Seguridad y autenticación", "M2 — Gestión de usuarios", "M3 — Empresas"]
    assert modulos[-1] == "PQRS"
    assert respuesta["total"] == len(servicio.permisos_delegables()) >= len(CATALOGO_BASE)
    for modulo in respuesta["modulos"]:
        for permiso in modulo["permisos"]:
            assert permiso["descripcion"] and permiso["descripcion"] != permiso["codigo"]
    # Orden numérico dentro del módulo: SOL-006 antes que SOL-010.
    sol = next(m for m in respuesta["modulos"] if m["modulo"].startswith("M5"))["permisos"]
    codigos = [p["codigo"] for p in sol]
    assert codigos.index("SOL-006") < codigos.index("SOL-010") < codigos.index("SOL-041")


# ============================================================
# 6. MENÚ Y PANTALLAS (static/nav.js)
# ============================================================

NAV = (RAIZ / "static" / "nav.js").read_text(encoding="utf-8")


def test_nav_consulta_mios_con_cache_en_sessionstorage_protegida():
    assert '"/api/permisos-auxiliar/mios"' in NAV
    bloque = NAV[NAV.index("function leerPermisosGuardados"):NAV.index("function tienePermisoAuxiliar")]
    assert bloque.count("try {") == 2 and "sessionStorage.getItem" in bloque and "sessionStorage.setItem" in bloque
    assert "VIGENCIA_PERMISOS_MS" in NAV


def test_nav_muestra_el_aviso_sin_permisos():
    assert "Aún no tienes permisos asignados. El Coordinador puede otorgártelos." in NAV
    assert "ajustarPanelAuxiliar" in NAV


def test_cada_opcion_del_menu_de_administracion_declara_permisos():
    inicio = NAV.index("var MENU_ADMINISTRACION")
    menu = NAV[inicio:NAV.index("var MENU_AUDITOR")]
    # Grupos y opciones con destino: todos llevan permisos, salvo panel, perfil, MFA y salir.
    for texto in ("Registradas", "Registrar empresa", "Consultar auditorías programadas", "Banco de auditores",
                  "Auditores registrados", "Conflictos de interés"):
        linea = next(l for l in menu.splitlines() if f'texto: "{texto}"' in l)
        assert "permisos:" in linea, texto
    assert "permisos: e[2]" in menu and "permisos: s[2]" in menu
    assert "permisos: PERMISOS_REPORTES" in menu
    for grupo in ("GRUPO_CERTIFICADOS", "GRUPO_PQRS"):
        definicion = NAV[NAV.index("var " + grupo):NAV.index("};", NAV.index("var " + grupo))]
        assert "permisos" in definicion, grupo


def test_las_pantallas_marcan_las_acciones_con_su_permiso():
    solicitudes = (RAIZ / "static" / "solicitudes.html").read_text(encoding="utf-8")
    assert 'id="advertenciaConfirmar" data-permiso-aux="SOL-048"' in solicitudes
    assert 'id="advertenciaForzar" data-permiso-aux="SOL-048"' in solicitudes
    for etapa in ("radicadas", "revision", "por-asignar", "con-auditores", "todas"):
        assert re.search(rf'data-etapa="{etapa}" data-permiso-aux="[A-Z0-9 -]+"', solicitudes), etapa
    asignacion = (RAIZ / "static" / "solicitudes-asignacion.js").read_text(encoding="utf-8")
    assert "CertiPermisos.tiene('SOL-048')" in asignacion
    assert "data-permiso-aux" in (RAIZ / "static" / "empresas.html").read_text(encoding="utf-8")


def test_el_estilo_oculta_lo_que_no_tiene_permiso():
    assert ".ma-sin-permiso{display:none !important}" in NAV
    assert 'querySelectorAll("[data-permiso-aux]")' in NAV
