"""Configuración común de las pruebas.

`require_auditor_aprobado` (modules/auth/dependencies.py) consulta en la base si
el auditor de la sesión ya está aprobado. Las pruebas existentes usan bases
simuladas que no conocen esa consulta, así que por defecto se da al auditor por
aprobado; las pruebas de esa regla (test_auditor_no_aprobado.py) reemplazan
este doble con el estado que necesitan.
"""

import pytest

from modules.auth import dependencies


@pytest.fixture(autouse=True)
def _auditor_aprobado_por_defecto(monkeypatch):
    async def _aprobado(_db, _id_usuario):
        return {"aprobado": True, "estado_postulacion": "Aprobado", "estado_auditor": "Activo"}

    monkeypatch.setattr(dependencies, "consultar_acceso_auditor", _aprobado)


class _AlmacenSoloDisco:
    """Almacén compartido apagado: ninguna prueba toca la base real por él."""

    def acepta(self, _db):
        return False

    def sin_tabla_reciente(self):
        return True


@pytest.fixture(autouse=True)
def _almacen_archivos_solo_disco(monkeypatch):
    # core/almacen_archivos.py guarda también en la base compartida. En las
    # pruebas queda solo en disco; test_almacen_archivos.py pone su base simulada.
    from core import almacen_archivos

    monkeypatch.setattr(almacen_archivos, "backend", _AlmacenSoloDisco())
