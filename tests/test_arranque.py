"""
Arranque de la aplicación · `core/arranque.py`.

Preparar la base tarda cerca de medio minuto y es idempotente, así que solo
debe repetirse cuando hace falta. Lo que aquí se comprueba es justo eso: que
se salte cuando todo está al día y que vuelva a hacerlo en cuanto algo
cambia, porque un arranque rápido que deje la base a medias sería peor que
uno lento.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core import arranque


class Resultado:
    def __init__(self, todas=None, escalar=None):
        self._todas, self._escalar = todas or [], escalar

    def scalars(self):
        return self

    def all(self):
        return self._todas

    def scalar(self):
        return self._escalar


def sesion(tablas=None, columnas_presentes=True):
    """Doble de sesión: responde qué tablas y columnas existen."""
    presentes = tablas if tablas is not None else [
        nombre for tipo, nombre in arranque.PIEZAS_CLAVE if tipo == "tabla"
    ]

    async def execute(sentencia, parametros=None):
        parametros = parametros or {}
        filas = [("tabla", t, "") for t in parametros.get("tablas", []) if t in presentes]
        if columnas_presentes:
            pares = zip(parametros.get("tablas_de_columnas", []), parametros.get("columnas", []))
            filas += [("columna", tabla, columna) for tabla, columna in pares]
        return Resultado(todas=filas)

    doble = AsyncMock()
    doble.execute = execute
    contexto = MagicMock()
    contexto.__aenter__ = AsyncMock(return_value=doble)
    contexto.__aexit__ = AsyncMock(return_value=False)
    return contexto


# ============================================================
# LA HUELLA
# ============================================================

def test_la_huella_es_estable_si_nada_cambia():
    assert arranque.huella() == arranque.huella()


def test_la_huella_cambia_si_cambia_un_archivo_de_preparacion(tmp_path, monkeypatch):
    antes = arranque.huella()

    # Se simula que uno de los archivos de preparación ahora es otro.
    falso = tmp_path / "bootstrap.py"
    falso.write_text("# contenido distinto", encoding="utf-8")
    monkeypatch.setattr(arranque, "ARCHIVOS_DE_PREPARACION", ("main.py", str(falso)))

    assert arranque.huella() != antes


def test_la_huella_cambia_si_se_apunta_a_otra_base(monkeypatch):
    antes = arranque.huella()
    monkeypatch.setattr(arranque.settings, "DATABASE_URL", "postgresql+asyncpg://otra/base")
    assert arranque.huella() != antes


def test_un_archivo_que_no_existe_no_rompe_la_huella(monkeypatch):
    monkeypatch.setattr(arranque, "ARCHIVOS_DE_PREPARACION", ("no_existe.py",))
    assert isinstance(arranque.huella(), str)


# ============================================================
# EL MODO
# ============================================================

@pytest.mark.parametrize("valor", ["siempre", "1", "true", "si", "sí"])
async def test_se_puede_forzar_la_preparacion(valor, monkeypatch):
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", valor)

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is True
    assert "siempre" in motivo


@pytest.mark.parametrize("valor", ["nunca", "0", "false", "no"])
async def test_se_puede_apagar_la_preparacion(valor, monkeypatch):
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", valor)

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is False
    assert "nunca" in motivo


# ============================================================
# EL MODO AUTOMÁTICO
# ============================================================

async def test_sin_marca_previa_se_prepara(monkeypatch):
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", "auto")
    monkeypatch.setattr(arranque, "_huella_guardada", lambda: None)

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is True
    assert "cambió" in motivo


async def test_con_la_marca_al_dia_y_la_base_completa_no_se_prepara(monkeypatch):
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", "auto")
    monkeypatch.setattr(arranque, "_huella_guardada", arranque.huella)
    monkeypatch.setattr(arranque, "AsyncSessionLocal", lambda: sesion())

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is False
    assert "ya estaba preparada" in motivo


async def test_si_falta_una_tabla_se_prepara_aunque_la_marca_coincida(monkeypatch):
    """Protege el caso de restaurar una copia vieja de la base."""
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", "auto")
    monkeypatch.setattr(arranque, "_huella_guardada", arranque.huella)
    monkeypatch.setattr(arranque, "AsyncSessionLocal", lambda: sesion(tablas=["contacto_sede"]))

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is True
    assert "faltan piezas" in motivo


async def test_si_falta_una_columna_se_prepara(monkeypatch):
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", "auto")
    monkeypatch.setattr(arranque, "_huella_guardada", arranque.huella)
    monkeypatch.setattr(arranque, "AsyncSessionLocal", lambda: sesion(columnas_presentes=False))

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is True


async def test_si_no_se_puede_comprobar_el_esquema_se_prepara(monkeypatch):
    """Ante la duda, lento pero seguro."""
    monkeypatch.setattr(arranque.settings, "PREPARAR_BASE", "auto")
    monkeypatch.setattr(arranque, "_huella_guardada", arranque.huella)

    def explota():
        raise OSError("sin conexión")

    monkeypatch.setattr(arranque, "AsyncSessionLocal", lambda: explota())

    preparar, motivo = await arranque.debe_preparar_la_base()

    assert preparar is True
    assert "no se pudo comprobar" in motivo


# ============================================================
# LA MARCA
# ============================================================

def test_guardar_la_huella_no_rompe_el_arranque_si_no_se_puede_escribir(monkeypatch, tmp_path):
    imposible = tmp_path / "no" / "existe" / "arranque.json"
    monkeypatch.setattr(arranque, "MARCA", imposible)
    monkeypatch.setattr(arranque.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("sin permiso")))

    arranque.guardar_huella("abc")  # no debe lanzar


def test_la_marca_vive_en_storage_que_no_va_al_repositorio():
    assert arranque.MARCA.parent.name == "storage"
