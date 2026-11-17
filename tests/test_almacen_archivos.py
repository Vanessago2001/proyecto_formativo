"""Archivos compartidos entre computadores (core/almacen_archivos.py).

Se simulan dos "computadores" (dos carpetas temporales distintas) que usan la
misma base simulada: lo que sube A se descarga en B aunque B no lo tenga en su
disco. No se toca la base real.
"""

import hashlib
import io
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from core import almacen_archivos as almacen
from core import archivos_firmados as af
from core.config import settings


# ----------------------------------------------------------------------
# Dobles: base compartida en memoria y sesión de la petición
# ----------------------------------------------------------------------

class BaseSimulada:
    """Imita la tabla archivo_almacenado (compartida por todos los computadores)."""

    def __init__(self, hay_tabla: bool = True):
        self.filas: dict[str, dict] = {}
        self.hay_tabla = hay_tabla
        self.escrituras = 0
        self.lecturas = 0

    def acepta(self, _db):
        return True

    def sin_tabla_reciente(self):
        return False

    async def disponible(self, _sesion):
        return self.hay_tabla

    async def escribir(self, _sesion, fila):
        self.escrituras += 1
        self.filas[fila["ruta"]] = dict(fila)

    async def obtener(self, _sesion, clave):
        self.lecturas += 1
        fila = self.filas.get(clave)
        return fila["contenido"] if fila else None

    async def existe(self, _sesion, clave):
        return clave in self.filas

    async def tamanos(self, _sesion, claves):
        return {c: self.filas[c]["tamano_bytes"] for c in claves if c in self.filas}

    async def huellas(self, _sesion):
        return {c: f["sha256"] for c, f in self.filas.items()}

    async def borrar(self, _sesion, claves):
        for clave in claves:
            self.filas.pop(clave, None)


class _Contexto:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class SesionSimulada:
    def __init__(self, filas=None):
        self.commits = 0
        self.rollbacks = 0
        self._filas = filas or []

    def begin_nested(self):
        return _Contexto()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def execute(self, *_args, **_kwargs):
        filas = self._filas
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: filas[0] if filas else None))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.fixture
def base(monkeypatch):
    simulada = BaseSimulada()
    monkeypatch.setattr(almacen, "backend", simulada)
    return simulada


@pytest.fixture
def computadores(tmp_path):
    a = (tmp_path / "computador_a").resolve()
    b = (tmp_path / "computador_b").resolve()
    a.mkdir()
    b.mkdir()
    return a, b


def _en(monkeypatch, raiz):
    """Hace que el almacén trabaje con la carpeta del proyecto de ese computador."""
    monkeypatch.setattr(almacen, "RAIZ_PROYECTO", raiz)


# ----------------------------------------------------------------------
# Núcleo
# ----------------------------------------------------------------------

async def test_guardar_escribe_en_la_base_y_en_el_disco(base, computadores, monkeypatch):
    a, _ = computadores
    _en(monkeypatch, a)
    db = SesionSimulada()
    usuario = {"id_usuario": str(uuid4())}

    clave = await almacen.guardar("/uploads/auditores/hoja.pdf", b"%PDF-1", db=db, usuario=usuario)

    assert clave == "uploads/auditores/hoja.pdf"
    assert (a / "uploads" / "auditores" / "hoja.pdf").read_bytes() == b"%PDF-1"
    fila = base.filas[clave]
    assert fila["contenido"] == b"%PDF-1"
    assert fila["sha256"] == hashlib.sha256(b"%PDF-1").hexdigest()
    assert fila["tamano_bytes"] == 6
    assert fila["content_type"] == "application/pdf"
    assert fila["subido_por"] == usuario["id_usuario"]
    # Va en la transacción del módulo: el almacén no hace commit por su cuenta.
    assert db.commits == 0


async def test_subir_en_a_y_descargar_en_b(base, computadores, monkeypatch):
    a, b = computadores
    db = SesionSimulada()

    _en(monkeypatch, a)
    await almacen.guardar("storage\\apelaciones\\x\\acta.pdf", b"contenido A", db=db)

    _en(monkeypatch, b)
    assert not (b / "storage" / "apelaciones" / "x" / "acta.pdf").exists()
    assert await almacen.existe("storage/apelaciones/x/acta.pdf", db=db)
    assert await almacen.leer("storage/apelaciones/x/acta.pdf", db=db) == b"contenido A"
    # Queda en la caché local de B: la segunda lectura no consulta la base.
    lecturas = base.lecturas
    ruta = await almacen.ruta_local("/storage/apelaciones/x/acta.pdf", db=db)
    assert ruta == b / "storage" / "apelaciones" / "x" / "acta.pdf"
    assert ruta.read_bytes() == b"contenido A"
    assert base.lecturas == lecturas


async def test_eliminar_borra_de_la_base_y_del_disco(base, computadores, monkeypatch):
    a, _ = computadores
    _en(monkeypatch, a)
    db = SesionSimulada()
    await almacen.guardar("uploads/x.png", b"png", db=db)

    await almacen.eliminar("/uploads/x.png", db=db, confirmar=True)

    assert "uploads/x.png" not in base.filas
    assert not (a / "uploads" / "x.png").exists()
    assert db.commits == 1


async def test_sin_tabla_funciona_solo_con_disco_y_avisa_una_vez(computadores, monkeypatch, caplog):
    a, b = computadores

    class SinTabla(almacen._AlmacenBD):
        consultas = 0

        def acepta(self, _db):
            return True

        async def disponible(self, sesion):
            SinTabla.consultas += 1
            return await super().disponible(sesion)

    class SesionSinTabla(SesionSimulada):
        async def execute(self, *_a, **_k):
            return SimpleNamespace(scalar=lambda: False)

    monkeypatch.setattr(almacen, "backend", SinTabla())
    db = SesionSinTabla()
    _en(monkeypatch, a)

    with caplog.at_level(logging.WARNING, logger="API_RAIZ"):
        await almacen.guardar("uploads/a.pdf", b"uno", db=db)
        await almacen.guardar("uploads/b.pdf", b"dos", db=db)
    assert (a / "uploads" / "a.pdf").read_bytes() == b"uno"
    assert await almacen.leer("uploads/a.pdf", db=db) == b"uno"
    avisos = [r for r in caplog.records if "archivo_almacenado no existe" in r.getMessage()]
    assert len(avisos) == 1
    # Se recuerda que no hay tabla: no se vuelve a preguntar en cada archivo.
    assert SinTabla.consultas == 1

    _en(monkeypatch, b)
    assert await almacen.leer("uploads/a.pdf", db=db) is None
    assert await almacen.ruta_local("uploads/a.pdf", db=db) is None


async def test_un_error_de_la_base_nunca_rompe_la_subida(computadores, monkeypatch):
    a, _ = computadores

    class BaseCaida(BaseSimulada):
        async def escribir(self, _s, _f):
            raise RuntimeError("conexión perdida")

        async def obtener(self, _s, _c):
            raise RuntimeError("conexión perdida")

    monkeypatch.setattr(almacen, "backend", BaseCaida())
    _en(monkeypatch, a)
    db = SesionSimulada()

    await almacen.guardar("uploads/c.pdf", b"x", db=db)
    assert (a / "uploads" / "c.pdf").read_bytes() == b"x"
    assert await almacen.leer("uploads/otro.pdf", db=db) is None


@pytest.mark.parametrize(
    "entrada, esperada",
    [
        ("/uploads/auditores/x.pdf", "uploads/auditores/x.pdf"),
        ("uploads/auditores/x.pdf", "uploads/auditores/x.pdf"),
        ("storage\\apelaciones\\1\\y.png", "storage/apelaciones/1/y.png"),
        ("/uploads/auditores/con%20espacio.pdf", "uploads/auditores/con espacio.pdf"),
        ("/uploads/auditores/x.pdf?v=3", "uploads/auditores/x.pdf"),
        ("/archivos/1700000000/" + "a" * 64 + "/auditores/x.pdf", "uploads/auditores/x.pdf"),
        ("uploads/./auditores//x.pdf", "uploads/auditores/x.pdf"),
        ("../uploads/x.pdf", None),
        ("uploads/../core/config.py", None),
        ("/uploads/%2e%2e/main.py", None),
        ("storage/..\\..\\secreto.txt", None),
        ("C:\\Windows\\win.ini", None),
        ("static/logo.png", None),
        ("main.py", None),
        ("uploads", None),
        ("", None),
        (None, None),
    ],
)
def test_normalizacion_y_path_traversal(entrada, esperada):
    assert almacen.normalizar(entrada) == esperada


async def test_rutas_peligrosas_no_se_guardan_ni_se_leen(base, computadores, monkeypatch):
    a, _ = computadores
    _en(monkeypatch, a)
    with pytest.raises(almacen.RutaNoValida):
        await almacen.guardar("uploads/../../fuera.txt", b"x", db=SesionSimulada())
    assert not (a.parent / "fuera.txt").exists()
    assert await almacen.leer("../main.py", db=SesionSimulada()) is None
    assert base.filas == {}


async def test_archivo_que_supera_el_limite_queda_solo_en_disco(base, computadores, monkeypatch):
    a, _ = computadores
    _en(monkeypatch, a)
    monkeypatch.setattr(almacen, "LIMITE_BYTES", 10)

    await almacen.guardar("uploads/grande.pdf", b"x" * 11, db=SesionSimulada())
    await almacen.guardar("uploads/justo.pdf", b"x" * 10, db=SesionSimulada())

    assert (a / "uploads" / "grande.pdf").stat().st_size == 11
    assert "uploads/grande.pdf" not in base.filas
    assert "uploads/justo.pdf" in base.filas


def test_el_limite_coincide_con_el_sql():
    sql = (almacen.RAIZ_PROYECTO / "documentacion" / "sql_archivos_compartidos.sql").read_text(encoding="utf-8")
    assert f"tamano_bytes <= {almacen.LIMITE_BYTES}" in sql


async def test_doble_de_prueba_no_toca_la_base_real(computadores, monkeypatch):
    """Con un AsyncMock u otro doble (no AsyncSession) el almacén real solo usa el disco."""
    a, _ = computadores
    _en(monkeypatch, a)
    monkeypatch.setattr(almacen, "backend", almacen._AlmacenBD())

    class Doble:
        def __getattr__(self, nombre):
            raise AssertionError(f"no debía usar la sesión ({nombre})")

    await almacen.guardar("uploads/d.pdf", b"d", db=Doble())
    assert await almacen.leer("uploads/d.pdf", db=Doble()) == b"d"


# ----------------------------------------------------------------------
# Cada módulo descarga desde la base lo que subió otro computador
# ----------------------------------------------------------------------

CONTENIDO = b"%PDF-1.4 subido en el computador A"
HUELLA = hashlib.sha256(CONTENIDO).hexdigest()


def _sembrar(base, clave):
    base.filas[clave] = {
        "ruta": clave, "contenido": CONTENIDO, "tamano_bytes": len(CONTENIDO), "sha256": HUELLA,
    }


async def _archivos(b, monkeypatch, base):
    from modules.archivos import archivos_router

    monkeypatch.setattr(af, "RAIZ_UPLOADS", b / "uploads")
    _sembrar(base, "uploads/auditores/hoja.pdf")
    url = af.firmar_url("/uploads/auditores/hoja.pdf")
    _, _, exp, firma, ruta = url.split("/", 4)
    respuesta = await archivos_router.descargar_archivo(int(exp), firma, ruta, db=SesionSimulada())
    return respuesta.path


async def _auditores_registrados(b, monkeypatch, base):
    from modules.auditores_registrados import auditores_registrados_service as svc

    monkeypatch.setattr(svc, "RAIZ_UPLOADS", b / "uploads")
    _sembrar(base, "uploads/auditores/certificaciones/c.pdf")
    return await svc._resolver_archivo_compartido("/uploads/auditores/certificaciones/c.pdf", SesionSimulada())


async def _apelaciones(b, monkeypatch, base):
    from modules.apelaciones import apelaciones_service as svc

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    monkeypatch.setattr(svc, "CARPETA_EVIDENCIAS", b / "storage" / "apelaciones")
    _sembrar(base, "storage/apelaciones/ap1/e.pdf")
    db = SesionSimulada([{"nombre_archivo": "e.pdf", "url_archivo": "storage\\apelaciones\\ap1\\e.pdf"}])
    servicio = svc.ApelacionesService(db)

    async def _visible(*_a, **_k):
        return {"id_apelacion": "ap1"}

    monkeypatch.setattr(servicio, "get_apelacion_by_id", _visible)
    ruta, _ = await servicio.obtener_archivo_evidencia(uuid4(), uuid4(), {})
    return ruta


async def _evidencias_auditoria(b, monkeypatch, base):
    from modules.auditorias import evidencia_service as svc

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    _sembrar(base, "storage/auditorias/au1/e.pdf")
    servicio = svc.EvidenciaService(SesionSimulada())

    async def _evidencia(*_a):
        return {"id_evidencia": 1, "ruta_archivo": "storage/auditorias/au1/e.pdf",
                "nombre_archivo": "e.pdf", "hash_archivo": HUELLA}

    monkeypatch.setattr(servicio, "_evidencia", _evidencia)
    assert (await servicio.verificar_integridad(uuid4(), uuid4()))["integra"] is True
    ruta, _ = await servicio.archivo(uuid4(), uuid4())
    return ruta


async def _documentos_empresa(b, monkeypatch, base):
    from modules.empresas import documento_empresa_service as svc

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    _sembrar(base, "storage/empresas/em1/rut.pdf")
    return await svc.DocumentoEmpresaService(SesionSimulada()).ruta_disponible("storage/empresas/em1/rut.pdf")


async def _documentos_solicitud(b, monkeypatch, base):
    from modules.solicitudes import documento_service as svc

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    _sembrar(base, "storage/solicitudes/s1/d.pdf")
    servicio = svc.DocumentoService(SesionSimulada())

    async def _documento(*_a):
        return {"url_archivo": "storage\\solicitudes\\s1\\d.pdf", "nombre_archivo": "d.pdf"}

    monkeypatch.setattr(servicio, "_obtener_documento", _documento)
    ruta, _ = await servicio.obtener_archivo(uuid4(), uuid4(), {})
    return ruta


async def _pqrs(b, monkeypatch, base):
    from modules.pqrs import pqrs_service as svc

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    monkeypatch.setattr(svc, "CARPETA_ADJUNTOS", b / "storage" / "pqrs")
    _sembrar(base, "storage/pqrs/p1/a.pdf")
    servicio = svc.PqrsService(SesionSimulada(), repo=object())
    return await servicio._ruta_segura({"ruta_archivo": "storage/pqrs/p1/a.pdf"})


async def _certificados(b, monkeypatch, base):
    from modules.certificados import certificados_service as svc

    monkeypatch.setattr(settings, "CERTIFICADOS_STORAGE_DIR", str(b / "certificados"))
    id_certificado = uuid4()
    _sembrar(base, svc.clave_pdf_firmado(id_certificado))
    return await svc.CertificadosService(SesionSimulada())._leer_pdf_firmado(id_certificado, HUELLA)


async def _actas_comite(b, monkeypatch, base):
    from modules.comite import comite_acta_service as svc

    monkeypatch.setattr(settings, "COMITE_ACTAS_STORAGE_DIR", str(b / "actas"))
    id_acta = uuid4()
    _sembrar(base, svc.ComiteActaService._clave(id_acta, firmada=True))
    return await svc.ComiteActaService(SesionSimulada())._leer_pdf(id_acta, HUELLA, firmada=True)


@pytest.mark.parametrize(
    "descargar",
    [
        _archivos, _auditores_registrados, _apelaciones, _evidencias_auditoria,
        _documentos_empresa, _documentos_solicitud, _pqrs, _certificados, _actas_comite,
    ],
    ids=lambda f: f.__name__.strip("_"),
)
async def test_cada_modulo_sirve_el_archivo_subido_en_otro_computador(
    descargar, base, computadores, monkeypatch
):
    _, b = computadores
    _en(monkeypatch, b)

    resultado = await descargar(b, monkeypatch, base)

    contenido = resultado if isinstance(resultado, bytes) else open(resultado, "rb").read()
    assert contenido == CONTENIDO
    assert base.lecturas == 1


async def test_sin_el_archivo_en_ningun_lado_la_descarga_es_404(base, computadores, monkeypatch):
    from modules.archivos import archivos_router

    _, b = computadores
    _en(monkeypatch, b)
    monkeypatch.setattr(af, "RAIZ_UPLOADS", b / "uploads")
    url = af.firmar_url("/uploads/auditores/no-existe.pdf")
    _, _, exp, firma, ruta = url.split("/", 4)
    with pytest.raises(HTTPException) as error:
        await archivos_router.descargar_archivo(int(exp), firma, ruta, db=SesionSimulada())
    assert error.value.status_code == 404


async def test_la_firma_se_sigue_exigiendo_aunque_el_archivo_este_en_la_base(base, computadores, monkeypatch):
    from modules.archivos import archivos_router

    _, b = computadores
    monkeypatch.setattr(af, "RAIZ_UPLOADS", b / "uploads")
    _sembrar(base, "uploads/auditores/hoja.pdf")
    with pytest.raises(HTTPException) as error:
        await archivos_router.descargar_archivo(9999999999, "0" * 64, "auditores/hoja.pdf", db=SesionSimulada())
    assert error.value.status_code == 403
    assert base.lecturas == 0


# ----------------------------------------------------------------------
# Subidas de los módulos: quedan en la base (A) y se leen en B
# ----------------------------------------------------------------------

class _Subida:
    def __init__(self, nombre, contenido):
        self.filename = nombre
        self.file = io.BytesIO(contenido)


async def test_documento_de_empresa_subido_en_a_se_descarga_en_b(base, computadores, monkeypatch):
    from modules.empresas import documento_empresa_service as svc

    a, b = computadores
    monkeypatch.setattr(svc, "RAIZ_PROYECTO", a)
    monkeypatch.setattr(svc, "CARPETA_ARCHIVOS", a / "storage" / "empresas")
    _en(monkeypatch, a)
    servicio = svc.DocumentoEmpresaService(SesionSimulada())
    _, ruta = await servicio._guardar_archivo(uuid4(), _Subida("RUT.pdf", b""), b"rut", {"id_usuario": str(uuid4())})
    assert ruta.startswith("storage/empresas/")
    assert base.filas[ruta]["nombre_original"] == "RUT.pdf"

    monkeypatch.setattr(svc, "RAIZ_PROYECTO", b)
    _en(monkeypatch, b)
    descargado = await svc.DocumentoEmpresaService(SesionSimulada()).ruta_disponible(ruta)
    assert descargado.read_bytes() == b"rut"
    assert str(descargado).startswith(str(b))


async def test_documento_de_solicitud_y_evidencia_quedan_en_la_base(base, computadores, monkeypatch):
    from modules.auditorias import evidencia_service as ev
    from modules.solicitudes import documento_service as sol

    a, _ = computadores
    _en(monkeypatch, a)
    monkeypatch.setattr(sol, "RAIZ_PROYECTO", a)
    monkeypatch.setattr(sol, "CARPETA_ARCHIVOS", a / "storage" / "solicitudes")
    monkeypatch.setattr(ev, "RAIZ_PROYECTO", a)
    monkeypatch.setattr(ev, "CARPETA_ARCHIVOS", a / "storage" / "auditorias")

    url = await sol.DocumentoService(SesionSimulada())._guardar_archivo(_Subida("camara.pdf", b"camara"), "s1", "d1")
    assert base.filas[almacen.normalizar(url)]["contenido"] == b"camara"

    _, ruta, huella = await ev.EvidenciaService(SesionSimulada())._guardar("au1", _Subida("foto.jpg", b""), b"jpg")
    assert base.filas[ruta]["contenido"] == b"jpg"
    assert base.filas[ruta]["sha256"] == huella


async def test_carpeta_fuera_del_proyecto_sigue_funcionando_solo_con_disco(base, tmp_path, monkeypatch):
    from modules.apelaciones import apelaciones_service as svc

    # Las pruebas antiguas (y quien configure otra carpeta) guardan fuera de storage/.
    destino = tmp_path / "otra" / "x.pdf"
    assert await almacen.guardar("apelaciones/x.pdf", b"x", db=SesionSimulada(), disco=destino) is None
    assert destino.read_bytes() == b"x"
    assert base.filas == {}
    assert svc  # el módulo importa sin errores


# ----------------------------------------------------------------------
# Script de migración
# ----------------------------------------------------------------------

def _arbol_local(raiz):
    (raiz / "uploads" / "auditores").mkdir(parents=True)
    (raiz / "storage" / "pqrs" / "p1").mkdir(parents=True)
    (raiz / "uploads" / "auditores" / "hoja.pdf").write_bytes(b"hoja")
    (raiz / "uploads" / "auditores" / "ya.pdf").write_bytes(b"igual")
    (raiz / "storage" / "pqrs" / "p1" / "a.png").write_bytes(b"png")
    (raiz / "storage" / "arranque.json").write_text("{}")
    (raiz / "storage" / "llave.p12").write_bytes(b"secreto")
    (raiz / "storage" / "pqrs" / "p1" / ".tmp-123.pdf").write_bytes(b"temporal")
    return [(raiz / "uploads", "uploads"), (raiz / "storage", "storage")]


async def test_script_dry_run_solo_cuenta(base, tmp_path):
    from modules.scripts import subir_archivos_locales as script

    carpetas = _arbol_local(tmp_path)
    base.filas["uploads/auditores/ya.pdf"] = {"sha256": hashlib.sha256(b"igual").hexdigest()}

    resumen = await script.migrar(True, carpetas=carpetas, sesion_factory=SesionSimulada, salida=lambda *_: None)

    assert resumen.encontrados == 3  # sin arranque.json, la llave .p12 ni el temporal
    assert resumen.ya_estaban == 1
    assert resumen.nuevos == 2
    assert base.escrituras == 0
    lineas = []
    script.imprimir_resumen(resumen, True, salida=lineas.append)
    assert any("dry-run" in linea for linea in lineas)


async def test_script_sube_lo_que_falta_y_actualiza_lo_distinto(base, tmp_path):
    from modules.scripts import subir_archivos_locales as script

    carpetas = _arbol_local(tmp_path)
    base.filas["uploads/auditores/ya.pdf"] = {"sha256": hashlib.sha256(b"igual").hexdigest()}
    base.filas["uploads/auditores/hoja.pdf"] = {"sha256": "0" * 64}

    resumen = await script.migrar(False, carpetas=carpetas, sesion_factory=SesionSimulada, salida=lambda *_: None)

    assert (resumen.nuevos, resumen.actualizados, resumen.ya_estaban) == (1, 1, 1)
    assert base.filas["uploads/auditores/hoja.pdf"]["contenido"] == b"hoja"
    assert base.filas["storage/pqrs/p1/a.png"]["contenido"] == b"png"
    assert "storage/llave.p12" not in base.filas


async def test_script_sin_tabla_no_escribe(tmp_path, monkeypatch):
    from modules.scripts import subir_archivos_locales as script

    base = BaseSimulada(hay_tabla=False)
    monkeypatch.setattr(almacen, "backend", base)
    carpetas = _arbol_local(tmp_path)
    mensajes = []

    resumen = await script.migrar(False, carpetas=carpetas, sesion_factory=SesionSimulada, salida=mensajes.append)

    assert resumen.errores and base.escrituras == 0
    assert any("sql_archivos_compartidos.sql" in m for m in mensajes)
