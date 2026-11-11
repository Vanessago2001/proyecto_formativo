"""El rol "Administrador" pasa a llamarse "Coordinador" y el Super
Administrador (rol del desarrollador) se retira del sistema."""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from core.security import (
    ROL_RETIRADO,
    _normalize_role_name,
    create_access_token,
    es_coordinador,
    es_rol_retirado,
    get_current_user,
)


@pytest.mark.parametrize("nombre", ["Coordinador", "coordinador", "COORDINADOR", "Administrador"])
def test_coordinador_y_el_nombre_antiguo_son_el_mismo_rol(nombre):
    assert _normalize_role_name(nombre) == "admin"
    assert es_coordinador({"role_name": nombre})


@pytest.mark.parametrize("nombre", ["Super Administrador", "superadmin", "SUPERADM", "Superadministrador"])
def test_el_super_administrador_queda_retirado(nombre):
    assert _normalize_role_name(nombre) == ROL_RETIRADO
    assert es_rol_retirado(nombre)
    assert not es_coordinador({"role_name": nombre})


def test_coordinador_en_las_matrices_de_permisos():
    from modules.solicitudes.solicitud_permissions import ROL_ADM, nivel_permiso, normalizar_rol

    assert normalizar_rol("Coordinador") == ROL_ADM == "Coordinador"
    assert normalizar_rol("Super Administrador") is None
    # Lo que era exclusivo del Super Administrador lo hace el Coordinador.
    for codigo in ("SOL-049", "SOL-065", "SOL-066"):
        assert nivel_permiso(codigo, "Coordinador").value == "V"
        assert nivel_permiso(codigo, "Super Administrador").value == "F"
    # Lo que el Super Administrador hacía como empresa (pruebas) no se hereda.
    assert nivel_permiso("SOL-001", "Coordinador").value == "F"


def test_coordinador_entra_a_la_agenda_y_a_los_registros():
    from modules.agenda_auditor.agenda_router import _es_administrador
    from modules.auth.dependencies import es_rol_administrativo

    assert _es_administrador({"role_name": "Coordinador"})
    assert es_rol_administrativo({"role_name": "Coordinador"})
    assert not _es_administrador({"role_name": "Super Administrador"})
    assert not es_rol_administrativo({"role_name": "Super Administrador"})


def test_coordinador_en_pqrs():
    from modules.pqrs import pqrs_reglas as reglas

    assert reglas.rol_pqrs({"role_name": "Coordinador"}) == reglas.ROL_ADMIN
    assert reglas.rol_pqrs({"role_name": "Super Administrador"}) == reglas.ROL_SIN_ACCESO


def _db_con_rol(rol: str):
    fila = {
        "id_usuario": "u-1", "nombre": "x", "correo": "x@x.co",
        "estado": "Activo", "rol_id": "r-1", "role_name": rol,
    }
    resultado = MagicMock()
    resultado.mappings.return_value.first.return_value = fila

    class Db:
        async def execute(self, *a, **k):
            return resultado

    return Db()


def test_una_cuenta_con_el_rol_retirado_no_entra():
    token = create_access_token({"sub": "x", "user_id": "u-1"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(token=token, db=_db_con_rol("Super Administrador")))
    assert error.value.status_code == 403
    assert "rol retirado" in error.value.detail


def test_el_coordinador_si_entra():
    token = create_access_token({"sub": "x", "user_id": "u-1"})
    usuario = asyncio.run(get_current_user(token=token, db=_db_con_rol("Coordinador")))
    assert usuario["role_name"] == "Coordinador"
