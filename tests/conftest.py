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


@pytest.fixture(autouse=True)
def _sede_de_la_visita_por_defecto(request, monkeypatch):
    """
    Flujo 18/11/2026: crear_programacion exige una sede incluida en la
    solicitud (modules/empresas/requisitos_empresa.exigir_sede_de_la_solicitud).
    Las pruebas de Agenda anteriores usan bases simuladas estrictas que no
    conocen esa consulta, así que por defecto se da la sede por válida; las
    pruebas de esa regla se marcan con @pytest.mark.sede_real.
    """
    if request.node.get_closest_marker("sede_real"):
        return
    from modules.agenda_auditor import agenda_service

    async def _sede_valida(_db, _id_solicitud, _id_sede):
        return None

    monkeypatch.setattr(agenda_service, "exigir_sede_de_la_solicitud", _sede_valida)


def pytest_configure(config):
    config.addinivalue_line("markers", "sede_real: usa la regla real de la sede de la visita")
