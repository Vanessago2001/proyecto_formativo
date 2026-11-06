"""
Módulo PQRS: permisos por rol (incluidos los "Cond." y "Propias" de la hoja
"pqr"), flujo de estados, radicado único, reapertura, consulta pública con
radicado + correo y validación de adjuntos.

La base real no se toca: el servicio trabaja contra `RepoMemoria`, que imita
la interfaz de PqrsRepositorio, y el permiso delegado del auxiliar se simula.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers, UploadFile

from core.security import get_current_user
from main import app
from modules.permisos_auxiliar import permisos_auxiliar_service as permisos_aux
from modules.pqrs import pqrs_notificaciones, pqrs_rate_limit, pqrs_reglas as reglas
from modules.pqrs import pqrs_service
from modules.pqrs.pqrs_router import obtener_servicio
from modules.pqrs.pqrs_service import PqrsService

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "documentacion" / "permisos.xlsx"

PDF = b"%PDF-1.4\n%prueba\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


# ======================================================================
# Doble del repositorio
# ======================================================================

class RepoMemoria:
    def __init__(self):
        self.casos: dict[str, dict] = {}
        self.historiales: list[dict] = []
        self.adjuntos_: list[dict] = []
        self.vinculos: dict[str, set[str]] = {}       # usuario -> empresas
        self.auditorias: dict[str, dict] = {}         # id_auditoria -> {id_empresa, auditores}
        self.empresas: dict[str, dict] = {}
        self.usuarios: dict[str, dict] = {}
        self.secuencia = 0
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def siguiente_consecutivo(self):
        self.secuencia += 1
        return self.secuencia

    async def plazos(self):
        return [{"tipo": "Queja", "dias_habiles": 10, "dias_alerta": 2}]

    async def actualizar_plazo(self, tipo, dias, alerta, id_usuario):
        return {"tipo": tipo, "dias_habiles": dias, "dias_alerta": alerta}

    async def insertar(self, datos):
        if any(c["radicado"] == datos["radicado"] for c in self.casos.values()):
            raise AssertionError("radicado duplicado")
        id_pqrs = uuid.uuid4()
        self.casos[str(id_pqrs)] = {
            **datos, "id_pqrs": id_pqrs, "id_responsable": None, "respuesta": None,
            "fecha_respuesta": None, "fecha_cierre": None, "veces_reabierta": 0,
        }
        return id_pqrs

    def _con_responsable(self, caso):
        if caso is None:
            return None
        responsable = self.usuarios.get(str(caso.get("id_responsable")))
        return {**caso, "responsable": responsable["nombre"] if responsable else None}

    async def obtener(self, id_pqrs):
        return self._con_responsable(self.casos.get(str(id_pqrs)))

    async def obtener_por_radicado(self, radicado):
        for caso in self.casos.values():
            if caso["radicado"] == radicado:
                return self._con_responsable(caso)
        return None

    async def actualizar(self, id_pqrs, estado_esperado, campos):
        caso = self.casos.get(str(id_pqrs))
        if not caso or caso["estado"] != estado_esperado:
            return False
        caso.update(campos)
        return True

    async def listar(self, alcance, filtros, limite=500):
        filas = []
        for caso in self.casos.values():
            uid = str(alcance.get("id_usuario"))
            if alcance["tipo"] == "empresa":
                if str(caso.get("id_usuario_peticionario")) != uid and str(caso.get("id_empresa")) not in self.vinculos.get(uid, set()):
                    continue
            elif alcance["tipo"] == "auditor":
                auditoria = self.auditorias.get(str(caso.get("id_auditoria")), {})
                if str(caso.get("id_responsable")) != uid and uid not in auditoria.get("auditores", set()):
                    continue
            if filtros.get("estado") and caso["estado"] != filtros["estado"]:
                continue
            if filtros.get("tipo") and caso["tipo"] != filtros["tipo"]:
                continue
            filas.append(self._con_responsable(caso))
        return filas

    async def registrar_historial(self, datos):
        self.historiales.append({**datos, "id_historial": uuid.uuid4(), "fecha": datetime.now(timezone.utc)})

    async def historial(self, id_pqrs, solo_visibles=False):
        return [h for h in self.historiales
                if str(h["id_pqrs"]) == str(id_pqrs) and (h["visible_peticionario"] or not solo_visibles)]

    async def insertar_adjunto(self, datos):
        fila = {**datos, "id_adjunto": uuid.uuid4(), "fecha_subida": datetime.now(timezone.utc)}
        self.adjuntos_.append(fila)
        return fila

    async def adjuntos(self, id_pqrs):
        return [a for a in self.adjuntos_ if str(a["id_pqrs"]) == str(id_pqrs)]

    async def adjunto(self, id_pqrs, id_adjunto):
        for a in self.adjuntos_:
            if str(a["id_pqrs"]) == str(id_pqrs) and str(a["id_adjunto"]) == str(id_adjunto):
                return a
        return None

    async def empresas_de_usuario(self, id_usuario):
        return set(self.vinculos.get(str(id_usuario), set()))

    async def empresa(self, id_empresa):
        return self.empresas.get(str(id_empresa))

    async def empresa_de_auditoria(self, id_auditoria):
        auditoria = self.auditorias.get(str(id_auditoria))
        return {"id_auditoria": id_auditoria, "id_empresa": auditoria["id_empresa"]} if auditoria else None

    async def auditor_vinculado(self, id_auditoria, id_usuario):
        return str(id_usuario) in self.auditorias.get(str(id_auditoria), {}).get("auditores", set())

    async def usuario(self, id_usuario):
        return self.usuarios.get(str(id_usuario))

    async def usuarios_internos_activos(self):
        return [u for u in self.usuarios.values()
                if reglas.rol_pqrs(u) in (reglas.ROL_ADMIN, reglas.ROL_AUXILIAR, reglas.ROL_AUDITOR)]


# ======================================================================
# Utilidades
# ======================================================================

def usuario(rol: str, nombre: str | None = None) -> dict:
    u = {"id_usuario": str(uuid.uuid4()), "nombre": nombre or rol, "correo": f"{uuid.uuid4().hex[:6]}@x.co",
         "estado": "Activo", "role_name": rol}
    return u


DATOS = {
    "tipo": "Queja",
    "asunto": "Demora en la atención",
    "descripcion": "La solicitud lleva varias semanas sin respuesta del equipo.",
    "nombre_peticionario": "Ana Pérez",
    "tipo_documento": "Cédula de Ciudadanía",
    "numero_documento": "1020304050",
    "correo": "ana@example.com",
    "telefono": None,
    "empresa_nombre": None,
    "nit": None,
    "acepta_tratamiento_datos": True,
    "id_empresa": None,
    "id_auditoria": None,
    "canal": None,
    "sitio_web": None,
}


class Reloj:
    """Hora fija para el servicio."""

    def __init__(self, cuando: datetime):
        self.cuando = cuando

    def __call__(self):
        return self.cuando


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    repo = RepoMemoria()
    correos: list[tuple[str, dict]] = []
    permisos_auxiliar: dict[tuple[str, str], bool] = {}

    async def falso_permiso(session, id_usuario, codigo):
        return permisos_auxiliar.get((str(id_usuario), codigo), False)

    async def falso_uso(session, id_usuario, codigo, detalle=None, id_aprobacion=None):
        return None

    monkeypatch.setattr(permisos_aux, "auxiliar_tiene_permiso", falso_permiso)
    monkeypatch.setattr(permisos_aux, "registrar_uso", falso_uso)
    monkeypatch.setattr(pqrs_service, "CARPETA_ADJUNTOS", tmp_path / "storage" / "pqrs")
    monkeypatch.setattr(pqrs_service, "RAIZ_PROYECTO", tmp_path)

    for nombre in ("notificar_radicacion", "notificar_respuesta"):
        async def falso(pqrs, _n=nombre):
            correos.append((_n, pqrs))
            return True
        monkeypatch.setattr(pqrs_notificaciones, nombre, falso)

    async def falso_info(pqrs, solicitud):
        correos.append(("notificar_solicitud_informacion", pqrs))
        return True
    monkeypatch.setattr(pqrs_notificaciones, "notificar_solicitud_informacion", falso_info)

    reloj = Reloj(datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc))

    def servicio():
        s = PqrsService(None, repo=repo)
        s.ahora = reloj
        return s

    class E:
        pass

    e = E()
    e.repo, e.correos, e.permisos, e.servicio, e.reloj = repo, correos, permisos_auxiliar, servicio, reloj

    def dar(u, *codigos):
        for codigo in codigos:
            permisos_auxiliar[(str(u["id_usuario"]), codigo)] = True
    e.dar = dar

    def registrar_usuario(u):
        repo.usuarios[str(u["id_usuario"])] = u
        return u
    e.registrar = registrar_usuario
    return e


async def radicar_publica(e, **cambios):
    return await e.servicio().radicar({**DATOS, **cambios}, None)


async def llevar_a(e, id_pqrs, admin, estado):
    """Lleva la PQRS por el flujo hasta `estado`."""
    s = e.servicio()
    caso = e.repo.casos[str(id_pqrs)]
    if caso["estado"] == reglas.RADICADA:
        await s.asignar(id_pqrs, admin["id_usuario"], None, admin)
    if estado == reglas.ASIGNADA:
        return
    await s.cambiar_estado(id_pqrs, "En trámite", None, admin)
    if estado == reglas.EN_TRAMITE:
        return
    if estado == reglas.INFO_SOLICITADA:
        await s.solicitar_informacion(id_pqrs, "Adjunte el contrato firmado, por favor.", admin)
        return
    await s.responder(id_pqrs, "Revisamos el caso y la solicitud ya fue tramitada.", admin)
    if estado == reglas.RESPONDIDA:
        return
    await s.cerrar(id_pqrs, None, admin)


def archivo(nombre: str, contenido: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(contenido), filename=nombre, headers=Headers({}))


# ======================================================================
# Matriz
# ======================================================================

@pytest.mark.skipif(not RUTA_EXCEL.exists(), reason="permisos.xlsx no disponible")
def test_la_matriz_coincide_con_la_hoja_pqr_del_excel():
    openpyxl = pytest.importorskip("openpyxl")
    libro = openpyxl.load_workbook(RUTA_EXCEL, read_only=True, data_only=True)
    filas = [f for f in libro["pqr"].iter_rows(values_only=True) if f and f[0]]
    assert tuple(filas[0][2:10]) == reglas.COLUMNAS_MATRIZ
    excel = {f[0].strip(): (f[1].strip(), tuple(str(v).strip() for v in f[2:10])) for f in filas[1:]}
    assert excel == reglas.PERMISOS_PQR


def test_comite_y_aprendiz_no_tienen_ninguna_operacion():
    for rol in ("Comité", "Aprendiz", "Instructor"):
        r = reglas.rol_pqrs({"role_name": rol})
        assert r == reglas.ROL_SIN_ACCESO
        assert not any(reglas.tiene_permiso(c, r) for c in reglas.PERMISOS_PQR)


def test_super_administrador_se_trata_como_administrador():
    assert reglas.rol_pqrs({"role_name": "Super Administrador"}) == reglas.ROL_ADMIN
    assert reglas.rol_pqrs({"role_name": "Administrador"}) == reglas.ROL_ADMIN


def test_codigos_delegables_son_los_cond_del_auxiliar():
    esperados = {c for c, (_, v) in reglas.PERMISOS_PQR.items() if v[2] == "Cond."}
    assert set(pqrs_service.CODIGOS_DELEGABLES_AUXILIAR) == esperados
    assert "PQR-002" not in esperados and "PQR-009" not in esperados
    delegables = {p["codigo"] for p in permisos_aux.permisos_delegables() if p["modulo"] == "PQRS"}
    assert esperados <= delegables


# ======================================================================
# Radicado
# ======================================================================

async def test_radicado_publico_unico_y_con_formato(entorno):
    primera = await radicar_publica(entorno)
    segunda = await radicar_publica(entorno, correo="otro@example.com")
    assert primera["radicado"] == "PQRS-2026-000001"
    assert segunda["radicado"] == "PQRS-2026-000002"
    assert primera["estado"] == "Radicada"
    caso = entorno.repo.casos[primera["id_pqrs"]]
    assert caso["canal"] == "Web" and caso["id_usuario_radica"] is None
    # Plazo de Queja en el doble: 10 días hábiles desde el 4/11/2026 (festivos 16/11).
    assert caso["fecha_limite"] == date(2026, 11, 19)
    assert entorno.correos[0][0] == "notificar_radicacion"


def test_generar_radicado():
    assert reglas.generar_radicado(2026, 1) == "PQRS-2026-000001"
    assert reglas.RADICADO_PATRON.fullmatch(reglas.generar_radicado(2026, 1234567))


async def test_campo_trampa_bloquea_robots(entorno):
    with pytest.raises(HTTPException) as error:
        await radicar_publica(entorno, sitio_web="http://spam")
    assert error.value.status_code == 400
    assert not entorno.repo.casos


async def test_publico_no_puede_vincular_empresa_ni_auditoria(entorno):
    resultado = await radicar_publica(entorno, id_empresa=uuid.uuid4(), id_auditoria=uuid.uuid4())
    caso = entorno.repo.casos[resultado["id_pqrs"]]
    assert caso["id_empresa"] is None and caso["id_auditoria"] is None


async def test_fallo_de_correo_no_rompe_la_radicacion(entorno, monkeypatch):
    async def falla(pqrs):
        return False
    monkeypatch.setattr(pqrs_notificaciones, "notificar_radicacion", falla)
    resultado = await radicar_publica(entorno)
    assert resultado["radicado"]
    notas = [h for h in entorno.repo.historiales if h["accion"] == "notificar"]
    assert notas and "No se pudo" in notas[0]["comentario"]


async def test_empresa_radica_a_nombre_de_su_empresa(entorno):
    empresa = usuario("Empresa")
    id_empresa = str(uuid.uuid4())
    entorno.repo.vinculos[empresa["id_usuario"]] = {id_empresa}
    entorno.repo.empresas[id_empresa] = {"id_empresa": id_empresa, "nombre": "ACME", "nit": "900123"}
    detalle = await entorno.servicio().radicar(dict(DATOS), empresa)
    assert detalle["empresa_nombre"] == "ACME" and detalle["nit"] == "900123"
    assert str(detalle["id_empresa"]) == id_empresa
    # No ve datos internos de gestión.
    assert "id_responsable" not in detalle


async def test_empresa_no_radica_a_nombre_de_empresa_ajena(entorno):
    empresa = usuario("Empresa")
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().radicar({**DATOS, "id_empresa": uuid.uuid4()}, empresa)
    assert error.value.status_code == 403


async def test_auxiliar_radica_solo_con_permiso_delegado(entorno):
    aux = usuario("Auxiliar")
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().radicar(dict(DATOS), aux)
    assert error.value.status_code == 403
    entorno.dar(aux, "PQR-001", "PQR-003")
    detalle = await entorno.servicio().radicar({**DATOS, "canal": "Telefónico"}, aux)
    assert detalle["canal"] == "Telefónico"


async def test_auditor_y_comite_no_radican(entorno):
    for rol in ("Auditor", "Comité"):
        with pytest.raises(HTTPException) as error:
            await entorno.servicio().radicar(dict(DATOS), usuario(rol))
        assert error.value.status_code == 403


# ======================================================================
# Consultar (PQR-003/004/010)
# ======================================================================

async def test_empresa_ve_solo_las_propias(entorno):
    empresa = usuario("Empresa")
    otra = usuario("Empresa")
    propia = await entorno.servicio().radicar(dict(DATOS), empresa)
    ajena = await radicar_publica(entorno)
    lista = await entorno.servicio().listar(empresa)
    assert [str(f["id_pqrs"]) for f in lista] == [str(propia["id_pqrs"])]
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().detalle(ajena["id_pqrs"], empresa)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await entorno.servicio().detalle(propia["id_pqrs"], otra)


async def test_empresa_ve_las_de_su_empresa_aunque_las_radique_otro(entorno):
    empresa = usuario("Empresa")
    admin = usuario("Administrador")
    id_empresa = str(uuid.uuid4())
    entorno.repo.vinculos[empresa["id_usuario"]] = {id_empresa}
    entorno.repo.empresas[id_empresa] = {"id_empresa": id_empresa, "nombre": "ACME", "nit": "1"}
    creada = await entorno.servicio().radicar({**DATOS, "id_empresa": id_empresa}, admin)
    detalle = await entorno.servicio().detalle(creada["id_pqrs"], empresa)
    assert detalle["radicado"] == creada["radicado"]


async def test_empresa_no_ve_notas_internas_del_historial(entorno):
    empresa = usuario("Empresa")
    admin = entorno.registrar(usuario("Administrador"))
    creada = await entorno.servicio().radicar(dict(DATOS), empresa)
    await entorno.servicio().asignar(creada["id_pqrs"], admin["id_usuario"], "nota interna", admin)
    historial = await entorno.servicio().historial(creada["id_pqrs"], empresa)
    assert all("nota interna" not in (h["comentario"] or "") for h in historial)
    assert all(h["actor"] in ("Peticionario", "CertiSENA") for h in historial)
    completo = await entorno.servicio().historial(creada["id_pqrs"], admin)
    assert any("nota interna" in (h["comentario"] or "") for h in completo)


async def test_auditor_no_tiene_acceso_a_pqrs(entorno):
    # Decisión del equipo (06/11/2026): las PQRS solo las gestionan el
    # Administrador y los auxiliares con permiso delegado. El auditor no
    # consulta ni gestiona ninguna, ni siquiera las de sus auditorías.
    admin = entorno.registrar(usuario("Administrador"))
    auditor = entorno.registrar(usuario("Auditor"))
    id_auditoria, id_empresa = str(uuid.uuid4()), str(uuid.uuid4())
    entorno.repo.auditorias[id_auditoria] = {"id_empresa": id_empresa, "auditores": {auditor["id_usuario"]}}
    entorno.repo.empresas[id_empresa] = {"id_empresa": id_empresa, "nombre": "ACME", "nit": "1"}
    vinculada = await entorno.servicio().radicar({**DATOS, "id_auditoria": id_auditoria}, admin)
    s = entorno.servicio()
    for accion in (
        lambda: s.listar(auditor),
        lambda: s.estado(vinculada["id_pqrs"], auditor),
        lambda: s.historial(vinculada["id_pqrs"], auditor),
        lambda: s.cambiar_estado(vinculada["id_pqrs"], "En trámite", None, auditor),
        lambda: s.responder(vinculada["id_pqrs"], "x" * 30, auditor),
        lambda: s.cerrar(vinculada["id_pqrs"], None, auditor),
        lambda: s.asignar(vinculada["id_pqrs"], admin["id_usuario"], None, auditor),
        lambda: s.adjuntar(vinculada["id_pqrs"], [archivo("a.pdf", PDF)], None, auditor),
        lambda: s.reporte(auditor),
    ):
        with pytest.raises(HTTPException) as error:
            await accion()
        assert error.value.status_code == 403


async def test_no_se_asigna_pqrs_a_un_auditor(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    auditor = entorno.registrar(usuario("Auditor"))
    creada = await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().asignar(creada["id_pqrs"], auditor["id_usuario"], None, admin)
    assert error.value.status_code == 422


async def test_auxiliar_sin_permiso_no_consulta_y_con_permiso_ve_todas(entorno):
    aux = usuario("Auxiliar")
    await radicar_publica(entorno)
    await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().listar(aux)
    assert error.value.status_code == 403
    assert "administrador no te ha otorgado" in error.value.detail
    entorno.dar(aux, "PQR-003")
    assert len(await entorno.servicio().listar(aux)) == 2


async def test_comite_no_consulta(entorno):
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().listar(usuario("Comité"))
    assert error.value.status_code == 403


# ======================================================================
# Flujo de estados
# ======================================================================

async def test_flujo_completo_valido(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    id_pqrs = creada["id_pqrs"]
    s = entorno.servicio()
    assert (await s.asignar(id_pqrs, admin["id_usuario"], None, admin))["estado"] == "Asignada"
    assert (await s.cambiar_estado(id_pqrs, "en tramite", None, admin))["estado"] == "En trámite"
    assert (await s.solicitar_informacion(id_pqrs, "Envíe la factura del servicio.", admin))["estado"] == "Información solicitada"
    resultado = await s.adjuntar_publica(creada["radicado"], "ANA@example.com", [archivo("f.pdf", PDF)], "Adjunto factura")
    assert resultado["estado"] == "En trámite"
    respondida = await s.responder(id_pqrs, "Se corrigió la factura y se reenvió al correo.", admin)
    assert respondida["estado"] == "Respondida"
    assert (await s.cerrar(id_pqrs, None, admin))["estado"] == "Cerrada"
    acciones = [h["accion"] for h in entorno.repo.historiales if h["accion"] != "notificar"]
    assert acciones == ["radicar", "asignar", "cambiar_estado", "solicitar_informacion",
                        "aportar_informacion", "responder", "cerrar"]
    enviados = [n for n, _ in entorno.correos]
    assert enviados == ["notificar_radicacion", "notificar_solicitud_informacion", "notificar_respuesta"]


@pytest.mark.parametrize("actual,nuevo", [
    ("Radicada", "Respondida"),
    ("Radicada", "En trámite"),
    ("Asignada", "Cerrada"),
    ("En trámite", "Cerrada"),
    ("Cerrada", "En trámite"),
    ("Cerrada", "Respondida"),
    ("Reabierta", "Respondida"),
])
def test_transiciones_invalidas(actual, nuevo):
    with pytest.raises(reglas.ReglaPqrsError):
        reglas.validar_transicion(actual, nuevo)


@pytest.mark.parametrize("actual,nuevo", [
    ("Radicada", "Asignada"), ("Asignada", "En trámite"), ("En trámite", "Información solicitada"),
    ("Información solicitada", "En trámite"), ("En trámite", "Respondida"), ("Respondida", "Cerrada"),
    ("Cerrada", "Reabierta"), ("Reabierta", "En trámite"),
])
def test_transiciones_validas(actual, nuevo):
    reglas.validar_transicion(actual, nuevo)


async def test_no_se_responde_sin_pasar_por_tramite(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().responder(creada["id_pqrs"], "Respuesta prematura del caso.", admin)
    assert error.value.status_code == 409


async def test_cambio_manual_solo_a_en_tramite(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.EN_TRAMITE)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().cambiar_estado(creada["id_pqrs"], "Respondida", None, admin)
    assert error.value.status_code == 422 and "Registrar respuesta" in error.value.detail


async def test_admin_no_asigna_ni_adjunta_en_cerrada(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.CERRADA)
    otro = entorno.registrar(usuario("Administrador"))
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().asignar(creada["id_pqrs"], otro["id_usuario"], None, admin)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().adjuntar(creada["id_pqrs"], [archivo("a.pdf", PDF)], None, admin)
    assert error.value.status_code == 409


async def test_cerrar_desde_informacion_solicitada_exige_motivo(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.INFO_SOLICITADA)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().cerrar(creada["id_pqrs"], None, admin)
    assert error.value.status_code == 422
    cerrada = await entorno.servicio().cerrar(creada["id_pqrs"], "Desistimiento: no aportó lo pedido.", admin)
    assert cerrada["estado"] == "Cerrada"


async def test_conflicto_si_el_estado_cambio_entretanto(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.EN_TRAMITE)
    s = entorno.servicio()
    viejo = dict(await entorno.repo.obtener(creada["id_pqrs"]))
    entorno.repo.casos[str(creada["id_pqrs"])]["estado"] = reglas.RESPONDIDA   # otro gestor se adelantó

    async def obtener_viejo(_id):
        return viejo
    s.repo.obtener = obtener_viejo
    with pytest.raises(HTTPException) as error:
        await s.solicitar_informacion(creada["id_pqrs"], "Algo que ya no aplica.", admin)
    assert error.value.status_code == 409


# ======================================================================
# Asignación y auxiliar
# ======================================================================

async def test_auxiliar_con_permisos_gestiona_cualquier_pqrs(entorno):
    aux = entorno.registrar(usuario("Auxiliar"))
    admin = entorno.registrar(usuario("Administrador"))
    entorno.dar(aux, "PQR-003", "PQR-005", "PQR-006", "PQR-008", "PQR-012")
    creada = await radicar_publica(entorno)          # no asignada al auxiliar
    s = entorno.servicio()
    await s.asignar(creada["id_pqrs"], admin["id_usuario"], None, aux)
    await s.cambiar_estado(creada["id_pqrs"], "En trámite", None, aux)
    await s.responder(creada["id_pqrs"], "Respuesta registrada por el auxiliar.", aux)
    assert (await s.cerrar(creada["id_pqrs"], None, aux))["estado"] == "Cerrada"


async def test_auxiliar_sin_un_permiso_concreto_no_hace_esa_accion(entorno):
    aux = entorno.registrar(usuario("Auxiliar"))
    admin = entorno.registrar(usuario("Administrador"))
    entorno.dar(aux, "PQR-003", "PQR-006")                  # sin PQR-008
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.EN_TRAMITE)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().responder(creada["id_pqrs"], "Respuesta sin permiso delegado.", aux)
    assert error.value.status_code == 403
    detalle = await entorno.servicio().detalle(creada["id_pqrs"], aux)
    assert "responder" not in detalle["acciones"]


async def test_responsables_auxiliares_solo_con_pqr_008(entorno):
    admin = entorno.registrar(usuario("Administrador", "Admin"))
    aux_si = entorno.registrar(usuario("Auxiliar", "Aux con permiso"))
    aux_no = entorno.registrar(usuario("Auxiliar", "Aux sin permiso"))
    auditor = entorno.registrar(usuario("Auditor", "Auditora"))
    entorno.dar(aux_si, "PQR-008", "PQR-005")
    nombres = {r["nombre"] for r in await entorno.servicio().responsables_disponibles(admin)}
    # Los auditores no aparecen como responsables posibles para nadie.
    assert nombres == {"Admin", "Aux con permiso"}
    nombres_aux = {r["nombre"] for r in await entorno.servicio().responsables_disponibles(aux_si)}
    assert nombres_aux == {"Admin", "Aux con permiso"}

    creada = await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().asignar(creada["id_pqrs"], aux_no["id_usuario"], None, admin)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().asignar(creada["id_pqrs"], auditor["id_usuario"], None, aux_si)
    assert error.value.status_code == 422
    asignada = await entorno.servicio().asignar(creada["id_pqrs"], aux_si["id_usuario"], None, admin)
    assert asignada["responsable"] == "Aux con permiso"


async def test_no_se_asigna_a_inactivo_ni_a_empresa(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    inactivo = entorno.registrar({**usuario("Administrador"), "estado": "Inactivo"})
    empresa = entorno.registrar(usuario("Empresa"))
    creada = await radicar_publica(entorno)
    for destino in (inactivo, empresa):
        with pytest.raises(HTTPException) as error:
            await entorno.servicio().asignar(creada["id_pqrs"], destino["id_usuario"], None, admin)
        assert error.value.status_code == 422


# ======================================================================
# Reapertura (PQR-013)
# ======================================================================

async def test_reapertura_publica_en_plazo_y_una_sola_vez(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.CERRADA)
    entorno.reloj.cuando += timedelta(days=15)
    vista = await entorno.servicio().reabrir_publica(creada["radicado"], "ana@example.com", "La respuesta no resolvió el caso.")
    assert vista["estado"] == "Reabierta"
    caso = entorno.repo.casos[str(creada["id_pqrs"])]
    assert caso["veces_reabierta"] == 1 and caso["fecha_cierre"] is None
    # Nuevo plazo desde la reapertura.
    assert caso["fecha_limite"] > date(2026, 11, 19)

    s = entorno.servicio()
    await s.cambiar_estado(creada["id_pqrs"], "En trámite", None, admin)
    await s.responder(creada["id_pqrs"], "Segunda respuesta, ahora completa.", admin)
    await s.cerrar(creada["id_pqrs"], None, admin)
    with pytest.raises(HTTPException) as error:
        await s.reabrir_publica(creada["radicado"], "ana@example.com", "Otra vez quiero reabrirla.")
    assert error.value.status_code == 409 and "una vez" in error.value.detail
    # El administrador sí puede reabrir de nuevo.
    assert (await s.reabrir(creada["id_pqrs"], "Revisión de calidad interna.", admin))["estado"] == "Reabierta"


async def test_reapertura_fuera_de_plazo(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    empresa = usuario("Empresa")
    creada = await entorno.servicio().radicar(dict(DATOS), empresa)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.CERRADA)
    entorno.reloj.cuando += timedelta(days=16)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().reabrir(creada["id_pqrs"], "Ya pasó mucho tiempo, pero insisto.", empresa)
    assert error.value.status_code == 409 and "plazo" in error.value.detail
    detalle = await entorno.servicio().detalle(creada["id_pqrs"], empresa)
    assert "reabrir" not in detalle["acciones"]


async def test_no_se_reabre_lo_que_no_esta_cerrado(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.RESPONDIDA)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().reabrir_publica(creada["radicado"], "ana@example.com", "Quiero reabrir ya mismo.")
    assert error.value.status_code == 409


# ======================================================================
# Consulta pública
# ======================================================================

async def test_consulta_publica_con_radicado_y_correo(entorno):
    creada = await radicar_publica(entorno)
    vista = await entorno.servicio().consultar_publica(creada["radicado"], " Ana@Example.com ")
    assert vista["radicado"] == creada["radicado"] and vista["estado"] == "Radicada"
    assert "correo" not in vista and "numero_documento" not in vista
    assert "adjuntar" in vista["acciones"]


async def test_consulta_publica_mensaje_generico(entorno):
    creada = await radicar_publica(entorno)
    s = entorno.servicio()
    with pytest.raises(HTTPException) as mal_correo:
        await s.consultar_publica(creada["radicado"], "intruso@example.com")
    with pytest.raises(HTTPException) as no_existe:
        await s.consultar_publica("PQRS-2026-999999", "ana@example.com")
    assert mal_correo.value.status_code == no_existe.value.status_code == 404
    assert mal_correo.value.detail == no_existe.value.detail


async def test_consulta_publica_muestra_la_informacion_pedida(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.INFO_SOLICITADA)
    vista = await entorno.servicio().consultar_publica(creada["radicado"], "ana@example.com")
    assert vista["informacion_solicitada"] == "Adjunte el contrato firmado, por favor."
    assert vista["respuesta"] is None


# ======================================================================
# Adjuntos (PQR-011)
# ======================================================================

@pytest.mark.parametrize("nombre,contenido,codigo", [
    ("virus.exe", b"MZ....", 415),
    ("falso.pdf", b"MZ no es pdf", 415),
    ("vacio.png", b"", 400),
    ("grande.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024), 413),
], ids=["exe", "pdf-falso", "vacio", "mayor-5mb"])
def test_validacion_de_adjuntos_rechaza(nombre, contenido, codigo):
    with pytest.raises(reglas.ReglaPqrsError) as error:
        reglas.validar_adjunto(nombre, contenido)
    assert error.value.codigo == codigo


@pytest.mark.parametrize("nombre,contenido", [
    ("a.pdf", PDF), ("foto.PNG", PNG), ("foto.jpg", b"\xff\xd8\xff\xe0abc"), ("carta.docx", b"PK\x03\x04abc"),
])
def test_validacion_de_adjuntos_acepta(nombre, contenido):
    nombre_seguro, extension, mime = reglas.validar_adjunto(nombre, contenido)
    assert extension in reglas.EXTENSIONES_ADJUNTO and mime


def test_nombre_de_adjunto_sin_rutas():
    nombre, _, _ = reglas.validar_adjunto("../../etc/passwd.pdf", PDF)
    assert nombre == "passwd.pdf"


async def test_adjunto_se_guarda_en_disco_y_peticionario_no_adjunta_en_cerrada(entorno, tmp_path):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    s = entorno.servicio()
    resultado = await s.adjuntar_publica(creada["radicado"], "ana@example.com", [archivo("prueba.pdf", PDF)], None)
    assert resultado["agregados"] == 1
    guardado = entorno.repo.adjuntos_[0]
    assert (tmp_path / guardado["ruta_archivo"]).read_bytes() == PDF
    assert guardado["origen"] == "peticionario" and len(guardado["hash_sha256"]) == 64
    ruta, nombre, _ = await s.archivo_adjunto_publico(creada["radicado"], "ana@example.com", guardado["id_adjunto"])
    assert nombre == "prueba.pdf" and ruta.is_file()

    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.CERRADA)
    with pytest.raises(HTTPException) as error:
        await s.adjuntar_publica(creada["radicado"], "ana@example.com", [archivo("otra.pdf", PDF)], None)
    assert error.value.status_code == 409


async def test_adjunto_invalido_no_deja_nada(entorno, tmp_path):
    creada = await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().adjuntar_publica(
            creada["radicado"], "ana@example.com", [archivo("bien.pdf", PDF), archivo("mal.exe", b"MZ")], None)
    assert error.value.status_code == 415
    assert not entorno.repo.adjuntos_
    assert not (tmp_path / "storage" / "pqrs").exists()


async def test_gestion_debe_enviar_archivo(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    creada = await radicar_publica(entorno)
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().adjuntar(creada["id_pqrs"], [], "solo texto", admin)
    assert error.value.status_code == 400


async def test_empresa_responde_informacion_con_comentario(entorno):
    admin = entorno.registrar(usuario("Administrador"))
    empresa = usuario("Empresa")
    creada = await entorno.servicio().radicar(dict(DATOS), empresa)
    await llevar_a(entorno, creada["id_pqrs"], admin, reglas.INFO_SOLICITADA)
    resultado = await entorno.servicio().adjuntar(creada["id_pqrs"], [], "El contrato se firmó el 2 de octubre.", empresa)
    assert resultado["estado"] == "En trámite"


# ======================================================================
# Tiempos y reportes (PQR-014 / PQR-015)
# ======================================================================

def test_festivos_y_dias_habiles():
    assert date(2026, 11, 16) in reglas.festivos_colombia(2026)    # Independencia de Cartagena (lunes)
    assert date(2026, 4, 3) in reglas.festivos_colombia(2026)      # Viernes Santo
    assert reglas.sumar_dias_habiles(date(2026, 11, 13), 1) == date(2026, 11, 17)
    assert reglas.dias_habiles_entre(date(2026, 11, 13), date(2026, 11, 17)) == 1


def test_semaforo():
    hoy = date(2026, 11, 4)
    assert reglas.semaforo({"estado": "En trámite", "fecha_limite": date(2026, 11, 3)}, hoy) == "vencida"
    assert reglas.semaforo({"estado": "En trámite", "fecha_limite": date(2026, 11, 6)}, hoy) == "proxima"
    assert reglas.semaforo({"estado": "Asignada", "fecha_limite": date(2026, 11, 30)}, hoy) == "en_termino"
    assert reglas.semaforo({"estado": "Información solicitada", "fecha_limite": date(2026, 11, 3)}, hoy) == "en_espera"
    assert reglas.semaforo({"estado": "Cerrada", "fecha_limite": date(2026, 11, 3),
                            "fecha_respuesta": datetime(2026, 11, 2)}, hoy) == "atendida_a_tiempo"
    assert reglas.semaforo({"estado": "Respondida", "fecha_limite": date(2026, 11, 3),
                            "fecha_respuesta": datetime(2026, 11, 4)}, hoy) == "atendida_tarde"


async def test_tiempos_marca_vencidas_por_alcance(entorno):
    empresa = usuario("Empresa")
    propia = await entorno.servicio().radicar(dict(DATOS), empresa)
    await radicar_publica(entorno)
    entorno.reloj.cuando += timedelta(days=30)
    tiempos = await entorno.servicio().tiempos(empresa)
    assert tiempos["resumen"]["total"] == 1 and tiempos["resumen"]["vencida"] == 1
    assert tiempos["abiertas"][0]["radicado"] == propia["radicado"]
    admin = usuario("Administrador")
    assert (await entorno.servicio().tiempos(admin))["resumen"]["total"] == 2


async def test_reporte_permisos(entorno):
    await radicar_publica(entorno)
    with pytest.raises(HTTPException):
        await entorno.servicio().reporte(usuario("Empresa"))
    aux = usuario("Auxiliar")
    with pytest.raises(HTTPException):
        await entorno.servicio().reporte(aux)
    entorno.dar(aux, "PQR-015")
    assert len(await entorno.servicio().reporte(aux)) == 1
    with pytest.raises(HTTPException) as error:
        await entorno.servicio().reporte(usuario("Auditor"))
    assert error.value.status_code == 403


def test_reporte_ya_no_ofrece_csv():
    from modules.pqrs.pqrs_exportacion import formatos_disponibles, respuesta_reporte
    assert "csv" not in formatos_disponibles()
    with pytest.raises(HTTPException) as error:
        respuesta_reporte("csv", [], "Prueba")
    assert error.value.status_code == 422


def test_reporte_pdf_y_excel():
    from modules.pqrs.pqrs_exportacion import formatos_disponibles, respuesta_reporte
    filas = [{"radicado": "PQRS-2026-000001", "tipo": "Queja", "estado": "Radicada", "semaforo": "vencida"}]
    pdf = respuesta_reporte("pdf", filas, "Prueba")
    assert pdf.body.startswith(b"%PDF")
    if "xlsx" in formatos_disponibles():
        assert respuesta_reporte("xlsx", filas, "Prueba").body.startswith(b"PK")
    with pytest.raises(HTTPException):
        respuesta_reporte("doc", filas, "Prueba")


# ======================================================================
# Rutas HTTP
# ======================================================================

@pytest.fixture
def cliente(entorno):
    pqrs_rate_limit.reiniciar()
    app.dependency_overrides[obtener_servicio] = entorno.servicio
    yield entorno
    app.dependency_overrides.clear()
    pqrs_rate_limit.reiniciar()


async def _http():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_http_radicar_y_consultar_publico(cliente):
    async with await _http() as ac:
        r = await ac.post("/api/pqrs/publica/radicar", json={**DATOS, "tipo": "peticion"})
        assert r.status_code == 201, r.text
        radicado = r.json()["radicado"]
        r = await ac.post("/api/pqrs/publica/consultar", json={"radicado": radicado, "correo": "ana@example.com"})
        assert r.status_code == 200 and r.json()["tipo"] == "Petición"
        r = await ac.post("/api/pqrs/publica/consultar", json={"radicado": radicado, "correo": "otro@example.com"})
        assert r.status_code == 404


async def test_http_validaciones_de_radicacion(cliente):
    async with await _http() as ac:
        sin_datos = {**DATOS, "acepta_tratamiento_datos": False}
        assert (await ac.post("/api/pqrs/publica/radicar", json=sin_datos)).status_code == 422
        assert (await ac.post("/api/pqrs/publica/radicar", json={**DATOS, "correo": "no-es-correo"})).status_code == 422
        assert (await ac.post("/api/pqrs/publica/radicar", json={**DATOS, "tipo": "Denuncia"})).status_code == 422
        assert (await ac.post("/api/pqrs/publica/consultar",
                              json={"radicado": "abc' OR 1=1", "correo": "a@b.co"})).status_code == 422


async def test_http_limite_de_radicaciones_publicas(cliente):
    async with await _http() as ac:
        codigos = [(await ac.post("/api/pqrs/publica/radicar", json=DATOS)).status_code for _ in range(6)]
    assert codigos[:5] == [201] * 5 and codigos[5] == 429


async def test_http_adjunto_publico(cliente):
    async with await _http() as ac:
        radicado = (await ac.post("/api/pqrs/publica/radicar", json=DATOS)).json()["radicado"]
        r = await ac.post("/api/pqrs/publica/adjuntos",
                          data={"radicado": radicado, "correo": "ana@example.com"},
                          files=[("archivos", ("soporte.pdf", PDF, "application/pdf"))])
        assert r.status_code == 201, r.text
        r = await ac.post("/api/pqrs/publica/adjuntos",
                          data={"radicado": radicado, "correo": "ana@example.com"},
                          files=[("archivos", ("script.exe", b"MZ", "application/octet-stream"))])
        assert r.status_code == 415


async def test_http_gestion_requiere_sesion_y_rol(cliente):
    async with await _http() as ac:
        assert (await ac.get("/api/pqrs")).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: usuario("Comité")
        assert (await ac.get("/api/pqrs")).status_code == 403
        assert (await ac.get("/api/pqrs/tiempos")).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: usuario("Administrador")
        assert (await ac.get("/api/pqrs")).status_code == 200
        r = await ac.get("/api/pqrs/reporte", params={"formato": "csv"})
        assert r.status_code == 422
        r = await ac.get("/api/pqrs/reporte", params={"formato": "pdf"})
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        r = await ac.get("/api/pqrs/mis-permisos")
        assert r.json()["permisos"]["PQR-015"] is True and "csv" not in r.json()["formatos_reporte"]


async def test_http_paginas():
    async with await _http() as ac:
        for ruta in ("/pqrs", "/pqrs-gestion"):
            r = await ac.get(ruta)
            assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    gestion = Path("static/pqrs_gestion.html").read_text(encoding="utf-8")
    for vista in ("bandeja", "tiempos", "reportes"):
        assert f'data-view="{vista}"' in gestion
    assert "/static/nav.js" in gestion and "/static/session.js" in gestion
