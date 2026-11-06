"""Formulario de registro del auditor: títulos y experiencias.

Regresiones del documento de pruebas (módulo auditor):

  · "En experiencia en auditoría no me deja agregar experiencia como auditor":
    el formulario envía `descripcion: null` cuando el campo opcional va vacío y
    el esquema lo rechazaba con 422.
  · Editar un título o una experiencia debe actualizar la misma fila (PUT al
    id existente), no crear otra; y un registro aprobado no se modifica.
"""

import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from modules.auditores.auditor_schema import (
    ExperienciaAuditoriaCrear,
    ExperienciaLaboralCrear,
    TituloAcademicoCrear,
)
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ------------------------------------------------------------------
# Esquemas: campos opcionales enviados como null
# ------------------------------------------------------------------

def test_experiencia_auditoria_acepta_descripcion_y_tipo_nulos():
    data = ExperienciaAuditoriaCrear(
        organizacion="ACME S.A.S.",
        rol_auditoria="Auditor líder",
        tipo_auditoria=None,
        fecha_inicio="2024-01-01",
        fecha_fin=None,
        descripcion=None,
    )
    assert data.descripcion == ""
    assert data.tipo_auditoria == ""


def test_experiencia_laboral_acepta_descripcion_nula():
    data = ExperienciaLaboralCrear(
        empresa="ACME", cargo="Analista", fecha_inicio="2024-01-01", descripcion=None
    )
    assert data.descripcion == ""


def test_experiencia_auditoria_sigue_validando_fechas():
    with pytest.raises(ValueError):
        ExperienciaAuditoriaCrear(
            organizacion="ACME",
            rol_auditoria="Auditor",
            fecha_inicio="2024-05-01",
            fecha_fin="2024-01-01",
        )


# ------------------------------------------------------------------
# Servicio: editar actualiza la misma fila
# ------------------------------------------------------------------

class SesionRegistros:
    """Doble de las tablas titulo_academico / experiencia_* en memoria."""

    def __init__(self, tabla: str, filas: list[dict], clave: str):
        self.tabla = tabla
        self.filas = filas
        self.clave = clave
        self.inserts = 0
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        if "FROM usuario" in sql:            # _verificar_usuario_borrador
            return ResultadoFalso([{
                "id_usuario": ID_USUARIO, "nombre": "Auditor", "correo": "a@a.co",
                "estado": "Activo", "estado_auditor": "BORRADOR",
                "tipo_doc": "CC", "num_doc": "1",
            }])
        if sql.startswith("INSERT"):
            self.inserts += 1
            return ResultadoFalso([])
        if sql.startswith(f"UPDATE {self.tabla}"):
            for fila in self.filas:
                if (
                    str(fila[self.clave]) == str(params[self.clave])
                    and str(fila["id_usuario"]) == str(params["id_usuario"])
                    and fila["estado_validacion"] != "Aprobado"
                ):
                    for campo, valor in params.items():
                        if campo in fila and campo not in (self.clave, "id_usuario"):
                            fila[campo] = valor
                    fila["estado_validacion"] = "Pendiente"
                    fila["observacion_validacion"] = ""
                    return ResultadoFalso([dict(fila)])
            return ResultadoFalso([])
        raise AssertionError(f"Consulta no esperada: {sql[:80]}")

    async def commit(self):
        self.commits += 1


def _experiencia_auditoria(estado="Rechazado"):
    return {
        "id_experiencia": uuid.uuid4(),
        "id_usuario": ID_USUARIO,
        "organizacion": "Vieja",
        "rol_auditoria": "Auditor",
        "tipo_auditoria": "",
        "fecha_inicio": date(2023, 1, 1),
        "fecha_fin": None,
        "descripcion": "",
        "estado_validacion": estado,
        "observacion_validacion": "Falta soporte",
    }


@pytest.mark.asyncio
async def test_editar_experiencia_auditoria_actualiza_la_misma_fila():
    fila = _experiencia_auditoria()
    sesion = SesionRegistros("experiencia_auditoria", [fila], "id_experiencia")
    data = ExperienciaAuditoriaCrear(
        organizacion="Nueva entidad", rol_auditoria="Auditor líder",
        tipo_auditoria="Interna ISO 9001", fecha_inicio="2024-02-01", descripcion=None,
    )

    respuesta = await AuditorService(sesion).actualizar_experiencia_auditoria(
        ID_USUARIO, fila["id_experiencia"], data
    )

    assert sesion.inserts == 0
    assert len(sesion.filas) == 1
    assert respuesta["id_experiencia"] == fila["id_experiencia"]
    assert fila["organizacion"] == "Nueva entidad"
    assert fila["estado_validacion"] == "Pendiente"
    assert sesion.commits == 1


@pytest.mark.asyncio
async def test_editar_experiencia_aprobada_responde_409():
    fila = _experiencia_auditoria(estado="Aprobado")
    sesion = SesionRegistros("experiencia_auditoria", [fila], "id_experiencia")
    data = ExperienciaAuditoriaCrear(
        organizacion="Otra", rol_auditoria="Auditor", fecha_inicio="2024-02-01"
    )
    with pytest.raises(HTTPException) as error:
        await AuditorService(sesion).actualizar_experiencia_auditoria(
            ID_USUARIO, fila["id_experiencia"], data
        )
    assert error.value.status_code == 409
    assert fila["organizacion"] == "Vieja"
    assert sesion.commits == 0


@pytest.mark.asyncio
async def test_editar_experiencia_laboral_actualiza_la_misma_fila():
    fila = {
        "id_experiencia": uuid.uuid4(), "id_usuario": ID_USUARIO, "empresa": "Vieja",
        "cargo": "Analista", "fecha_inicio": date(2022, 1, 1), "fecha_fin": None,
        "descripcion": "", "estado_validacion": "Pendiente", "observacion_validacion": "",
    }
    sesion = SesionRegistros("experiencia_laboral", [fila], "id_experiencia")
    data = ExperienciaLaboralCrear(
        empresa="Nueva", cargo="Coordinador", fecha_inicio="2022-01-01", descripcion=None
    )
    await AuditorService(sesion).actualizar_experiencia_laboral(
        ID_USUARIO, fila["id_experiencia"], data
    )
    assert sesion.inserts == 0
    assert fila["empresa"] == "Nueva" and fila["cargo"] == "Coordinador"


@pytest.mark.asyncio
async def test_editar_titulo_actualiza_la_misma_fila():
    fila = {
        "id_titulo": uuid.uuid4(), "id_usuario": ID_USUARIO, "nivel": "Profesional",
        "titulo": "Ingeniería", "institucion": "Universidad X", "fecha_grado": None,
        "estado_validacion": "Rechazado", "observacion_validacion": "Ilegible",
    }
    sesion = SesionRegistros("titulo_academico", [fila], "id_titulo")
    data = TituloAcademicoCrear(
        nivel="Maestría", titulo="Maestría en Calidad", institucion="Universidad Y",
        fecha_grado="2021-06-30",
    )
    respuesta = await AuditorService(sesion).actualizar_titulo_academico(
        ID_USUARIO, fila["id_titulo"], data
    )
    assert sesion.inserts == 0
    assert respuesta["id_titulo"] == fila["id_titulo"]
    assert fila["nivel"] == "Maestría"
    assert fila["fecha_grado"] == date(2021, 6, 30)
    assert fila["estado_validacion"] == "Pendiente"


def test_rutas_put_registradas():
    from main import app

    paths = app.openapi()["paths"]
    for path in (
        "/auditores/registro/{id_usuario}/titulos/{id_titulo}",
        "/auditores/registro/{id_usuario}/experiencias-laborales/{id_experiencia}",
        "/auditores/registro/{id_usuario}/experiencias-auditoria/{id_experiencia}",
    ):
        assert "put" in paths.get(path, {}), path
