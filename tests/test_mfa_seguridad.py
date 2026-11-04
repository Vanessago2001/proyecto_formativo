"""Regresión: el segundo factor no filtra datos ni permite intentos ilimitados."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.auth.auth_service import AuthService, MAX_INTENTOS_MFA
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("55555555-5555-5555-5555-555555555555")


class SesionMFA:
    def __init__(self, usuario: dict | None):
        self.usuario = usuario
        self.consultas: list[tuple[str, dict | None]] = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.consultas.append((sql, params))
        if "FROM usuario u" in sql:
            return ResultadoFalso([self.usuario] if self.usuario else [])
        return ResultadoFalso([])

    async def commit(self):
        self.commits += 1

    @property
    def actualizaciones(self) -> list[str]:
        return [sql for sql, _ in self.consultas if "UPDATE usuario" in sql]


def usuario_mfa(codigo: str = "123456", expira=None, intentos: int = 0) -> dict:
    return {
        "id_usuario": ID_USUARIO,
        "nombre": "tester",
        "correo": "tester@example.com",
        "rol_id": 2,
        "mfa_codigo": codigo,
        "mfa_expira": expira or datetime.now(timezone.utc) + timedelta(minutes=5),
        "intentos_codigo": intentos,
        "rol_nombre": "Auditor",
    }


async def test_correo_inexistente_devuelve_400_generico():
    servicio = AuthService(SesionMFA(None))

    with pytest.raises(HTTPException) as excinfo:
        await servicio.login_mfa("nadie@example.com", "123456")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Código MFA incorrecto o expirado."


async def test_codigo_incorrecto_incrementa_intentos_y_mismo_mensaje():
    sesion = SesionMFA(usuario_mfa(intentos=2))
    servicio = AuthService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.login_mfa("tester@example.com", "000000")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Código MFA incorrecto o expirado."
    assert sesion.commits == 1
    assert any(
        params and params.get("intentos") == 3
        for sql, params in sesion.consultas
        if "UPDATE usuario" in sql
    )


async def test_codigo_expirado_devuelve_400():
    expirado = datetime.now(timezone.utc) - timedelta(minutes=1)
    sesion = SesionMFA(usuario_mfa(expira=expirado))
    servicio = AuthService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.login_mfa("tester@example.com", "123456")

    assert excinfo.value.status_code == 400
    assert sesion.actualizaciones == []


async def test_intentos_agotados_devuelve_429_y_anula_codigo():
    sesion = SesionMFA(usuario_mfa(intentos=MAX_INTENTOS_MFA - 1))
    servicio = AuthService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.login_mfa("tester@example.com", "000000")

    assert excinfo.value.status_code == 429
    assert sesion.commits == 1
    actualizacion = sesion.actualizaciones[0]
    assert "mfa_codigo = NULL" in actualizacion
    assert "intentos_codigo = 0" in actualizacion


async def test_codigo_correcto_entrega_token_y_lo_invalida():
    sesion = SesionMFA(usuario_mfa(codigo="123456"))
    servicio = AuthService(sesion)

    respuesta = await servicio.login_mfa("tester@example.com", "123456")

    assert respuesta["token_type"] == "bearer"
    assert respuesta["access_token"]
    assert sesion.commits == 1
    actualizacion = sesion.actualizaciones[0]
    assert "mfa_codigo = NULL" in actualizacion
    assert "mfa_verificado = TRUE" in actualizacion
