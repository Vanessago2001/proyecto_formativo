"""Regresión: el registro público no debe responder 500 ante datos duplicados."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from modules.users.user_schema import UserCreate
from modules.users.user_service import UserService
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("66666666-6666-6666-6666-666666666666")
ID_ROL = uuid.UUID("77777777-7777-7777-7777-777777777777")
ID_EMPRESA = uuid.UUID("88888888-8888-8888-8888-888888888888")


class SesionRegistro:
    def __init__(
        self,
        duplicado_nombre_correo: bool = False,
        duplicado_num_doc: bool = False,
        error_insert: Exception | None = None,
        rol_nombre: str = "Auditor",
        empresa_nit_duplicado: bool = False,
        empresa_correo_duplicado: bool = False,
    ):
        self.duplicado_nombre_correo = duplicado_nombre_correo
        self.duplicado_num_doc = duplicado_num_doc
        self.error_insert = error_insert
        self.rol_nombre = rol_nombre
        self.empresa_nit_duplicado = empresa_nit_duplicado
        self.empresa_correo_duplicado = empresa_correo_duplicado
        self.consultas: list[str] = []
        self.vinculos: list[dict] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.consultas.append(sql)
        if "FROM usuario" in sql and "LOWER(correo)" in sql:
            fila = [{"id_usuario": ID_USUARIO}] if self.duplicado_nombre_correo else []
            return ResultadoFalso(fila)
        if "WHERE num_doc" in sql:
            fila = [{"id_usuario": ID_USUARIO}] if self.duplicado_num_doc else []
            return ResultadoFalso(fila)
        if "FROM rol" in sql:
            return ResultadoFalso([{"id_rol": ID_ROL, "nombre": self.rol_nombre}])
        if "FROM empresa" in sql and "WHERE nit" in sql:
            fila = [{"id_empresa": ID_EMPRESA}] if self.empresa_nit_duplicado else []
            return ResultadoFalso(fila)
        if "FROM empresa" in sql and "LOWER(correo)" in sql:
            fila = [{"id_empresa": ID_EMPRESA}] if self.empresa_correo_duplicado else []
            return ResultadoFalso(fila)
        if "INSERT INTO empresa" in sql:
            return ResultadoFalso([{"id_empresa": ID_EMPRESA}])
        if "INSERT INTO user_empresa" in sql:
            self.vinculos.append(params or {})
            return ResultadoFalso([])
        if "INSERT INTO usuario" in sql:
            if self.error_insert is not None:
                raise self.error_insert
            return ResultadoFalso(
                [
                    {
                        "id_usuario": ID_USUARIO,
                        "nombre": params["nombre"],
                        "correo": params["correo"],
                        "estado": "Activo",
                        "rol_id": params["rol"],
                        "tipo_doc": params["tipo_doc"],
                        "num_doc": params["num_doc"],
                    }
                ]
            )
        return ResultadoFalso([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def datos_registro(contrasena: str = "Password1!", num_doc: str = "123456") -> UserCreate:
    return UserCreate(
        nombre="Usuario Prueba",
        correo="usuario@example.com",
        tipo_doc="CC",
        num_doc=num_doc,
        contrasena=contrasena,
        rol=ID_ROL,
    )


def error_unico(restriccion: str) -> IntegrityError:
    origen = Exception(
        f'duplicate key value violates unique constraint "{restriccion}"'
    )
    return IntegrityError("INSERT INTO usuario ...", {}, origen)


async def test_num_doc_duplicado_devuelve_400():
    sesion = SesionRegistro(duplicado_num_doc=True)
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El número de documento ya está registrado."
    assert sesion.commits == 0


async def test_correo_duplicado_devuelve_400():
    sesion = SesionRegistro(duplicado_nombre_correo=True)
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El usuario o correo ya existen."


async def test_carrera_de_num_doc_se_traduce_a_400():
    sesion = SesionRegistro(error_insert=error_unico("uq_usuario_num_doc"))
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El número de documento ya está registrado."
    assert sesion.rollbacks == 1


async def test_carrera_de_correo_se_traduce_a_400():
    sesion = SesionRegistro(error_insert=error_unico("usuario_correo_key"))
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El correo ya está registrado."


async def test_registro_valido_crea_usuario():
    sesion = SesionRegistro()
    servicio = UserService(sesion)

    usuario = await servicio.create_user(datos_registro())

    assert usuario["id_usuario"] == ID_USUARIO
    assert usuario["correo"] == "usuario@example.com"
    assert sesion.commits == 1
    assert not any("INSERT INTO empresa" in sql for sql in sesion.consultas)
    assert sesion.vinculos == []


async def test_registro_empresa_crea_y_vincula_empresa():
    sesion = SesionRegistro(rol_nombre="Empresa")
    servicio = UserService(sesion)

    usuario = await servicio.create_user(datos_registro())

    assert usuario["id_usuario"] == ID_USUARIO
    assert any("INSERT INTO empresa" in sql for sql in sesion.consultas)
    assert sesion.vinculos == [
        {"id_usuario": ID_USUARIO, "id_empresa": ID_EMPRESA}
    ]
    assert sesion.commits == 1


async def test_registro_empresa_con_nit_existente_no_crea_cuenta():
    sesion = SesionRegistro(rol_nombre="Empresa", empresa_nit_duplicado=True)
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El NIT ya está registrado como empresa."
    assert not any("INSERT INTO usuario" in sql for sql in sesion.consultas)
    assert sesion.commits == 0


async def test_registro_empresa_con_correo_existente_no_crea_cuenta():
    sesion = SesionRegistro(rol_nombre="Empresa", empresa_correo_duplicado=True)
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro())

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "El correo ya está registrado como empresa."
    assert not any("INSERT INTO usuario" in sql for sql in sesion.consultas)


async def test_password_de_mas_de_72_bytes_devuelve_400():
    sesion = SesionRegistro()
    servicio = UserService(sesion)

    with pytest.raises(HTTPException) as excinfo:
        await servicio.create_user(datos_registro(contrasena="Aa1!" + "x" * 70))

    assert excinfo.value.status_code == 400
    assert "demasiado larga" in excinfo.value.detail
    assert not any("INSERT INTO usuario" in sql for sql in sesion.consultas)
