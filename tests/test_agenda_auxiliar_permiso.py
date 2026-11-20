"""
Agenda (20/11/2026): el Auxiliar programa visitas solo si el Coordinador le
delegó el permiso (AGE-021 programar, AGE-024 cancelar, AGE-022/023
editar o reprogramar). Sin el permiso responde 403.
"""

import pytest
from fastapi import HTTPException

from modules.agenda_auditor import agenda_router as r

COORDINADOR = {"id_usuario": "c1", "role_name": "Coordinador"}


def _auxiliar(*codigos):
    return {"id_usuario": "a1", "role_name": "Auxiliar", "permisos_delegados": list(codigos)}


async def test_coordinador_programa_sin_permisos_delegados():
    assert await r._validar_administrador(usuario=COORDINADOR) is COORDINADOR


async def test_auxiliar_sin_permiso_no_programa():
    with pytest.raises(HTTPException) as error:
        await r._validar_administrador(usuario=_auxiliar())
    assert error.value.status_code == 403


async def test_auxiliar_con_age021_programa():
    usuario = _auxiliar("AGE-021")
    assert await r._validar_administrador(usuario=usuario) is usuario


async def test_cancelar_exige_age024_al_auxiliar():
    with pytest.raises(HTTPException):
        await r._validar_cancelar(usuario=_auxiliar("AGE-021"))
    usuario = _auxiliar("AGE-024")
    assert await r._validar_cancelar(usuario=usuario) is usuario


async def test_otros_roles_siguen_sin_acceso():
    with pytest.raises(HTTPException) as error:
        await r._validar_administrador(usuario={"id_usuario": "x", "role_name": "Auditor"})
    assert error.value.status_code == 403
