"""
El control de la asignación reconoce la aprobación venga escrita como venga.

`solicitudes/{id}/auditores` comparaba `solicitud["estado"]` contra el literal
'APROBADO', pero la base guarda el canon 'Aprobada' del catálogo de M5. El
listado sí mostraba las solicitudes aprobadas y al seleccionar una la pantalla
respondía "Solo se pueden asignar auditores a solicitudes en estado APROBADO",
sin excepción.
"""

import uuid

import pytest
from fastapi import HTTPException

from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService
from tests.fake_db import ResultadoFalso


class SesionFalsa:
    """Devuelve la única fila que consulta `obtener_solicitud`."""

    def __init__(self, estado):
        self._fila = {
            "id_solicitud": uuid.uuid4(),
            "numero_radicado": "SOL-2026-0001",
            "estado": estado,
            "id_empresa": uuid.uuid4(),
            "empresa_nombre": "Empresa de prueba",
            "id_norma": uuid.uuid4(),
            "norma_codigo": "ISO-9001",
            "norma_nombre": "Sistemas de gestion de la calidad",
            "norma_version": "2015",
            "fecha": None,
        }

    async def execute(self, sentencia, parametros=None):
        return ResultadoFalso([self._fila])


@pytest.mark.parametrize("estado", ["Aprobada", "APROBADA", "APROBADO", "  aprobada  "])
async def test_la_solicitud_aprobada_pasa_el_control(estado):
    solicitud = await AsignacionAuditorService(SesionFalsa(estado)).obtener_solicitud(uuid.uuid4())
    assert solicitud["estado"] == estado


@pytest.mark.parametrize("estado", ["Radicada", "En revision", "Rechazada", "Cancelada", "Cerrada"])
async def test_sin_aprobacion_no_se_pueden_asignar_auditores(estado):
    with pytest.raises(HTTPException) as error:
        await AsignacionAuditorService(SesionFalsa(estado)).obtener_solicitud(uuid.uuid4())
    assert error.value.status_code == 409
    assert "Aprobada" in error.value.detail
