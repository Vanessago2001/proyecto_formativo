"""
M7 — AUDITORÍAS · los siete bloques (AUT-001 a AUT-070).

Lo primero que se comprueba es que la matriz del código siga siendo la del
Excel, igual que en M5. Lo demás son las reglas del flujo de campo:

  · una solicitud no tiene dos auditorías abiertas a la vez;
  · una auditoría sin auditores asignados no se inicia;
  · solo las no conformidades se clasifican en Mayor o Menor;
  · al finalizar el informe la auditoría queda bloqueada;
  · no se firma un borrador ni se envía al Comité algo sin firmar;
  · no se cierra una auditoría con no conformidades abiertas.
"""

import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from core.database import get_db
from core.security import get_current_user
from main import app
from modules.auditorias.auditoria_permissions import (
    PERMISOS_M7,
    ROLES_EJECUTAN_CAMPO,
    nivel_permiso,
    tiene_permiso,
)
from modules.auditorias.evidencia_service import EvidenciaService
from modules.auditorias.hallazgo_service import HallazgoService

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "documentacion" / "permisos.xlsx"
HOJA_M7 = "M7 — AUDITORÍAS"

ID_AUDITORIA = str(uuid.uuid4())
ID_SOLICITUD = str(uuid.uuid4())
ID_VARIABLE = str(uuid.uuid4())
ID_HALLAZGO = str(uuid.uuid4())
ID_EVIDENCIA = str(uuid.uuid4())

BASE = f"/auditorias/{ID_AUDITORIA}"


# ============================================================
# 1. LA MATRIZ DEL CÓDIGO COINCIDE CON EL EXCEL
# ============================================================

def _leer_hoja_excel(ruta: Path, nombre_hoja: str) -> list[list[str]]:
    """Lee una hoja del .xlsx con la librería estándar (sin openpyxl)."""
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }

    with zipfile.ZipFile(ruta) as z:
        cadenas: list[str] = []
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in raiz.findall("m:si", ns):
            cadenas.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))

        relaciones = {
            rel.get("Id"): rel.get("Target").lstrip("/")
            for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        }

        libro = ET.fromstring(z.read("xl/workbook.xml"))
        destino = None
        for hoja in libro.find("m:sheets", ns):
            if hoja.get("name") == nombre_hoja:
                destino = relaciones[hoja.get(f"{{{ns['r']}}}id")]
                break

        assert destino, f"No se encontró la hoja '{nombre_hoja}' en {ruta.name}"
        if not destino.startswith("xl/"):
            destino = f"xl/{destino}"

        def indice_columna(referencia: str) -> int:
            letras = re.match(r"([A-Z]+)", referencia).group(1)
            numero = 0
            for letra in letras:
                numero = numero * 26 + ord(letra) - 64
            return numero

        filas: list[list[str]] = []
        hoja_xml = ET.fromstring(z.read(destino))
        for fila in hoja_xml.iter(f"{{{ns['m']}}}row"):
            celdas: dict[int, str] = {}
            for celda in fila.findall("m:c", ns):
                valor = celda.find("m:v", ns)
                if valor is None:
                    continue
                texto = cadenas[int(valor.text)] if celda.get("t") == "s" else valor.text
                celdas[indice_columna(celda.get("r"))] = (texto or "").strip()
            if celdas:
                filas.append([celdas.get(i, "") for i in range(1, max(celdas) + 1)])

        return filas


@pytest.mark.skipif(not RUTA_EXCEL.exists(), reason="permisos.xlsx no disponible")
def test_la_matriz_del_codigo_coincide_con_el_excel():
    """La hoja manda: si allí cambia un permiso y aquí no, esto falla."""
    filas = _leer_hoja_excel(RUTA_EXCEL, HOJA_M7)

    esperado = {
        fila[1]: (fila[2], tuple(fila[3:11]))
        for fila in filas
        if len(fila) >= 11 and fila[1] in PERMISOS_M7
    }

    assert set(esperado) == set(PERMISOS_M7)

    for codigo, (descripcion_excel, valores_excel) in esperado.items():
        descripcion_codigo, valores_codigo = PERMISOS_M7[codigo]
        assert descripcion_codigo == descripcion_excel, f"{codigo}: descripción distinta."
        assert tuple(v.value for v in valores_codigo) == valores_excel, (
            f"{codigo}: la fila de permisos difiere del Excel.\n"
            f"  Excel:  {valores_excel}\n"
            f"  Código: {tuple(v.value for v in valores_codigo)}"
        )


def test_la_matriz_cubre_los_setenta_permisos():
    assert sorted(PERMISOS_M7) == sorted(f"AUT-{n:03d}" for n in range(1, 71))


def test_cada_fila_tiene_un_valor_por_rol():
    for codigo, (_, valores) in PERMISOS_M7.items():
        assert len(valores) == 8, f"{codigo} no tiene un valor por cada columna."


def test_el_rol_publico_no_ejecuta_la_auditoria():
    """La hoja le deja consultar, pero nunca registrar ni decidir."""
    for codigo in ("AUT-001", "AUT-008", "AUT-011", "AUT-021", "AUT-031", "AUT-044", "AUT-057"):
        assert not tiene_permiso(codigo, "Publico"), f"{codigo} no debería ser del rol Publico."


def test_la_hoja_deja_la_ejecucion_de_campo_en_una_sola_columna():
    """
    Deja constancia de una anomalía de la hoja: AUT-001 (iniciar la auditoría
    de campo) no está concedido a la columna AUD sino a COM. El módulo
    transcribe la hoja tal cual; este test la documenta para que, cuando la
    institución la corrija, salte y se actualice la matriz.
    """
    assert "AUD" not in ROLES_EJECUTAN_CAMPO
    assert "COM" in ROLES_EJECUTAN_CAMPO


def test_suspender_la_auditoria_es_exclusivo_del_superadministrador():
    """AUT-010: SA para el SuperAdministrador y REQ para el Auxiliar."""
    assert nivel_permiso("AUT-010", "Super Administrador").value == "SA"
    assert nivel_permiso("AUT-010", "Auxiliar").value == "REQ"
    assert nivel_permiso("AUT-010", "Administrador").value == "F"


# ============================================================
# 2. EL DOBLE DE BASE
# ============================================================

def auditoria(estado: str = "En ejecucion", bloqueada: bool = False) -> dict:
    return {
        "id_auditoria": ID_AUDITORIA,
        "id_solicitud": ID_SOLICITUD,
        "id_programacion": None,
        "estado": estado,
        "fecha_inicio": None,
        "fecha_fin": None,
        "hora_inicio": None,
        "hora_fin": None,
        "observaciones_iniciales": None,
        "observaciones_cierre": None,
        "incidencias": None,
        "bloqueada": bloqueada,
        "id_usuario_creacion": None,
        "fecha_creacion": None,
        "fecha_cierre": None,
    }


def hallazgo(tipo: str = "NO_CONFORMIDAD", estado: str = "Pendiente", clasificacion=None) -> dict:
    return {
        "id_hallazgo": ID_HALLAZGO,
        "id_auditoria": ID_AUDITORIA,
        "id_evaluacion": None,
        "tipo": tipo,
        "clasificacion": clasificacion,
        "titulo": "Titulo del hallazgo",
        "descripcion": "Descripcion suficientemente larga del hallazgo.",
        "requisito_relacionado": None,
        "estado": estado,
        "fecha_registro": None,
        "fecha_cierre": None,
        "usuario_registra": None,
    }


class Respuesta:
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
    """Responde por el texto de la consulta y guarda lo ejecutado."""

    def __init__(self, fila_auditoria=None, registro=None, escalar=None, filas=None,
                 abierta=None, asignados=1):
        self.fila_auditoria = fila_auditoria if fila_auditoria is not None else auditoria()
        self.registro = registro
        self.escalar = escalar
        self.filas = filas or []
        self.abierta = abierta
        self.asignados = asignados
        self.sentencias: list[tuple[str, dict]] = []

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

        if "FROM auditoria WHERE id_auditoria" in sql:
            return Respuesta(primera=self.fila_auditoria)
        if "SELECT id_auditoria FROM auditoria" in sql:
            return Respuesta(escalar=self.abierta)
        if "COUNT(*) FROM auditores_solicitud" in sql:
            return Respuesta(escalar=self.asignados)
        if sql.startswith("SELECT COUNT(*)"):
            return Respuesta(escalar=self.escalar or 0)
        if "FROM solicitud" in sql:
            return Respuesta(primera={"id_solicitud": ID_SOLICITUD, "numero_radicado": "SOL-1",
                                      "id_empresa": str(uuid.uuid4()), "empresa": "Cafe del Eje"})
        return Respuesta(primera=self.registro, todas=self.filas, escalar=self.escalar)

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def pedir(db, rol, metodo, ruta, **kwargs):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "id_usuario": str(uuid.uuid4()),
        "role_name": rol,
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            return await getattr(cliente, metodo)(ruta, **kwargs)
    finally:
        app.dependency_overrides.clear()


# ============================================================
# 3. BLOQUE 1 · EJECUCIÓN
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 201), ("Comité", 201), ("Administrador", 403),
     ("Auxiliar", 403), ("Empresa", 403), ("Publico", 403)],
)
async def test_iniciar_auditoria_segun_la_hoja(rol, esperado):
    db = BaseFalsa(registro=auditoria())

    respuesta = await pedir(db, rol, "post", "/auditorias", json={"id_solicitud": ID_SOLICITUD})

    assert respuesta.status_code == esperado


async def test_no_se_inicia_una_segunda_auditoria_sobre_la_misma_solicitud():
    db = BaseFalsa(abierta=ID_AUDITORIA)

    respuesta = await pedir(db, "Comité", "post", "/auditorias", json={"id_solicitud": ID_SOLICITUD})

    assert respuesta.status_code == 409
    assert "en curso" in respuesta.json()["detail"]


async def test_no_se_inicia_una_auditoria_sin_auditores_asignados():
    db = BaseFalsa(asignados=0)

    respuesta = await pedir(db, "Comité", "post", "/auditorias", json={"id_solicitud": ID_SOLICITUD})

    assert respuesta.status_code == 409
    assert "auditores asignados" in respuesta.json()["detail"]


async def test_sobre_una_auditoria_bloqueada_no_se_registra_nada():
    db = BaseFalsa(fila_auditoria=auditoria(bloqueada=True))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/observaciones-iniciales",
                            json={"observaciones": "Texto de la observación."})

    assert respuesta.status_code == 409
    assert "bloqueada" in respuesta.json()["detail"]


@pytest.mark.parametrize("estado", ["Suspendida", "Cerrada"])
async def test_una_auditoria_suspendida_o_cerrada_no_admite_registros(estado):
    db = BaseFalsa(fila_auditoria=auditoria(estado=estado))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/observaciones-iniciales",
                            json={"observaciones": "Texto de la observación."})

    assert respuesta.status_code == 409


async def test_suspender_exige_un_motivo_escrito():
    db = BaseFalsa()

    corta = await pedir(db, "Super Administrador", "post", f"{BASE}/suspender", json={"motivo": "no"})

    assert corta.status_code == 422


# ============================================================
# 4. BLOQUE 3 · HALLAZGOS
# ============================================================

def servicio_hallazgos():
    return HallazgoService(AsyncMock())


@pytest.mark.parametrize("tipo", ["OBSERVACION", "OPORTUNIDAD_MEJORA"])
def test_solo_las_no_conformidades_se_clasifican(tipo):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        HallazgoService._validar(tipo, "MAYOR")

    assert error.value.status_code == 400
    assert "no conformidades" in error.value.detail


@pytest.mark.parametrize("clasificacion", ["Mayor", "grave", "ALTA"])
def test_la_clasificacion_solo_admite_mayor_o_menor(clasificacion):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        HallazgoService._validar("NO_CONFORMIDAD", clasificacion)

    assert error.value.status_code == 400


def test_los_tipos_de_hallazgo_son_los_que_admite_la_tabla():
    """La base tiene una restricción CHECK con estos tres valores."""
    from modules.auditorias.hallazgo_service import TIPOS

    assert set(TIPOS) == {"NO_CONFORMIDAD", "OBSERVACION", "OPORTUNIDAD_MEJORA"}


async def test_no_se_elimina_un_hallazgo_ya_confirmado():
    db = BaseFalsa(registro=hallazgo(estado="Confirmado", clasificacion="MAYOR"))

    respuesta = await pedir(db, "Comité", "delete", f"{BASE}/hallazgos/{ID_HALLAZGO}")

    assert respuesta.status_code == 409


async def test_no_se_elimina_un_hallazgo_con_evidencias():
    db = BaseFalsa(registro=hallazgo(), escalar=2)

    respuesta = await pedir(db, "Comité", "delete", f"{BASE}/hallazgos/{ID_HALLAZGO}")

    assert respuesta.status_code == 409
    assert "evidencias" in respuesta.json()["detail"]


# ============================================================
# 5. BLOQUE 4 · EVIDENCIAS
# ============================================================

@pytest.mark.parametrize("nombre", ["programa.exe", "hoja.xlsx", "sin_extension"])
def test_se_rechazan_los_formatos_de_evidencia_no_permitidos(nombre):
    from fastapi import HTTPException, UploadFile

    archivo = UploadFile(filename=nombre, file=MagicMock())
    with pytest.raises(HTTPException) as error:
        EvidenciaService.validar_formato(archivo, 1000)

    assert error.value.status_code == 415


def test_una_evidencia_vacia_no_se_acepta():
    from fastapi import HTTPException, UploadFile

    archivo = UploadFile(filename="foto.jpg", file=MagicMock())
    with pytest.raises(HTTPException) as error:
        EvidenciaService.validar_formato(archivo, 0)

    assert error.value.status_code == 400


def test_la_evidencia_admite_fotos_y_video_de_campo():
    from fastapi import UploadFile

    for nombre in ("foto.jpg", "acta.pdf", "recorrido.mp4", "informe.docx"):
        archivo = UploadFile(filename=nombre, file=MagicMock())
        assert EvidenciaService.validar_formato(archivo, 1000).startswith(".")


# ============================================================
# 6. BLOQUE 5 · INFORME
# ============================================================

class BaseInforme(BaseFalsa):
    def __init__(self, informe=None, sin_clasificar=0, **resto):
        super().__init__(**resto)
        self.informe = informe
        self.sin_clasificar = sin_clasificar

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        self.sentencias.append((sql, parametros or {}))

        if "FROM auditoria WHERE id_auditoria" in sql:
            return Respuesta(primera=self.fila_auditoria)
        if "FROM informe_auditoria" in sql or sql.startswith("UPDATE informe_auditoria"):
            return Respuesta(primera=self.informe)
        if "FROM hallazgo WHERE id_auditoria" in sql and "clasificacion IS NULL" in sql:
            return Respuesta(escalar=self.sin_clasificar)
        if sql.startswith("SELECT COUNT(*)"):
            return Respuesta(escalar=0)
        return Respuesta(primera=self.registro, todas=self.filas)


def informe(estado: str = "Borrador", firma=None, hash_documento=None, envio=None) -> dict:
    return {
        "id_informe": str(uuid.uuid4()),
        "id_auditoria": ID_AUDITORIA,
        "version": 1,
        "tipo": "Preliminar",
        "contenido": {"empresa": {"nombre": "Cafe del Eje"}},
        "url_archivo": None,
        "estado": estado,
        "fecha_generacion": None,
        "fecha_finalizacion": None,
        "fecha_envio_comite": envio,
        "usuario_generacion": None,
        "usuario_finalizacion": None,
        "hash_documento": hash_documento,
        "firma_digital": firma,
        "fecha_firma": None,
    }


async def test_no_se_finaliza_el_informe_con_no_conformidades_sin_clasificar():
    db = BaseInforme(informe=informe(), sin_clasificar=2)

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/informe/finalizar")

    assert respuesta.status_code == 409
    assert "sin clasificar" in respuesta.json()["detail"]


async def test_no_se_firma_un_informe_en_borrador():
    db = BaseInforme(informe=informe("Borrador"))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/informe/firmar")

    assert respuesta.status_code == 409
    assert "finalizar" in respuesta.json()["detail"]


async def test_no_se_firma_dos_veces_el_mismo_informe():
    db = BaseInforme(informe=informe("Finalizado", firma="abc", hash_documento="h"))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/informe/firmar")

    assert respuesta.status_code == 409
    assert "ya está firmado" in respuesta.json()["detail"]


async def test_no_se_envia_al_comite_un_informe_sin_firmar():
    db = BaseInforme(informe=informe("Finalizado", hash_documento="h"))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/informe/comite")

    assert respuesta.status_code == 409
    assert "firmado" in respuesta.json()["detail"]


async def test_no_se_envia_dos_veces_al_comite():
    db = BaseInforme(informe=informe("Enviado", firma="abc", hash_documento="h", envio="2026-10-21"))

    respuesta = await pedir(db, "Comité", "post", f"{BASE}/informe/comite")

    assert respuesta.status_code == 409


async def test_finalizar_el_informe_bloquea_la_auditoria():
    db = BaseInforme(informe=informe())

    await pedir(db, "Comité", "post", f"{BASE}/informe/finalizar")

    assert any("UPDATE auditoria SET bloqueada = TRUE" in sql for sql, _ in db.sentencias)


# ============================================================
# 7. BLOQUE 6 · CIERRE
# ============================================================

async def test_no_se_cierra_la_auditoria_con_no_conformidades_abiertas():
    db = BaseFalsa(escalar=3)

    respuesta = await pedir(db, "Administrador", "post", f"{BASE}/cerrar",
                            json={"observaciones": "Cierre de la auditoría de prueba."})

    assert respuesta.status_code == 409
    assert "no conformidades" in respuesta.json()["detail"]


async def test_solo_se_reabre_una_auditoria_cerrada():
    db = BaseFalsa(fila_auditoria=auditoria(estado="En ejecucion"))

    respuesta = await pedir(db, "Super Administrador", "post", f"{BASE}/reabrir",
                            json={"motivo": "Se detectó un error en el informe."})

    assert respuesta.status_code == 409


async def test_reabrir_exige_justificacion_larga():
    db = BaseFalsa(fila_auditoria=auditoria(estado="Cerrada"))

    respuesta = await pedir(db, "Super Administrador", "post", f"{BASE}/reabrir", json={"motivo": "porque"})

    assert respuesta.status_code == 422


async def test_una_accion_correctiva_siempre_responde_a_un_hallazgo():
    db = BaseFalsa()

    respuesta = await pedir(db, "Auditor", "post", f"{BASE}/acciones-correctivas",
                            json={"descripcion": "Documentar el análisis del contexto."})

    assert respuesta.status_code == 400
    assert "hallazgo" in respuesta.json()["detail"]


# ============================================================
# 8. LOS PERMISOS REQ NO SE EJECUTAN: QUEDAN PENDIENTES
# ============================================================

@pytest.mark.parametrize(
    "rol,esperado",
    [("Super Administrador", 200), ("Administrador", 200), ("Auxiliar", 202), ("Comité", 403)],
)
async def test_cerrar_la_auditoria_segun_la_hoja(rol, esperado):
    """AUT-057: el Auxiliar la pide (REQ) y un superior la aprueba."""
    db = BaseFalsa(escalar=0, registro={"id_auditoria": ID_AUDITORIA, "estado": "Cerrada",
                                        "fecha_fin": None, "fecha_cierre": None,
                                        "observaciones_cierre": None})

    respuesta = await pedir(db, rol, "post", f"{BASE}/cerrar",
                            json={"observaciones": "Cierre de la auditoría de prueba."})

    assert respuesta.status_code == esperado


async def test_el_auxiliar_no_cierra_la_auditoria_solo_lo_pide():
    # El registro hace de fila devuelta por el INSERT de la aprobación.
    db = BaseFalsa(escalar=0, registro={"id_aprobacion": str(uuid.uuid4()),
                                        "codigo_permiso": "AUT-057", "datos": "{}",
                                        "estado": "Pendiente"})

    await pedir(db, "Auxiliar", "post", f"{BASE}/cerrar",
                json={"observaciones": "Cierre de la auditoría de prueba."})

    ejecutadas = [sql for sql, _ in db.sentencias]
    assert not any(s.startswith("UPDATE auditoria SET estado") for s in ejecutadas)
    assert any("INSERT INTO aprobacion_pendiente" in s for s in ejecutadas)


async def test_exportar_las_evidencias_no_necesita_aprobacion_aunque_sea_req():
    """AUT-039 es REQ para el Auxiliar, pero solo lee: se resuelve al momento."""
    db = BaseFalsa(filas=[])

    respuesta = await pedir(db, "Auxiliar", "get", f"{BASE}/evidencias/paquete")

    assert respuesta.status_code == 200
