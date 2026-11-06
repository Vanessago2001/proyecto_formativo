"""Regresiones del módulo auditor (documento de pruebas del equipo).

· Conflictos registrados: un auditor ya aprobado (estado_auditor 'Activo') no
  podía declarar un conflicto: el servicio exigía que el registro siguiera
  abierto y respondía "El registro ya no se encuentra disponible para edición".
  Un conflicto de interés se puede declarar en cualquier momento, y declararlo
  (o editarlo) no debe borrar los demás conflictos del auditor.
· Disponibilidad: un doble clic registraba dos disponibilidades extraordinarias
  idénticas; al editar una, la copia seguía en el historial y parecía que la
  edición había creado un registro nuevo.
"""

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from modules.agenda_auditor.agenda_schema import DisponibilidadExtraordinariaCrear
from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_EMPRESA = uuid.UUID("44444444-4444-4444-4444-444444444444")
ID_OTRA_EMPRESA = uuid.UUID("55555555-5555-5555-5555-555555555555")


def correr(coro):
    return asyncio.run(coro)


class SesionConflictos:
    """Doble de `usuario` + `conflicto_interes` con las consultas del servicio."""

    def __init__(self, estado_auditor="Activo", estado="Activo", conflictos=None):
        self.usuario = {
            "id_usuario": ID_USUARIO,
            "nombre": "Auditor",
            "correo": "a@x.co",
            "estado": estado,
            "estado_auditor": estado_auditor,
            "tipo_doc": "CC",
            "num_doc": "1",
        }
        self.conflictos = list(conflictos or [])
        self.sql = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.sql.append(sql)
        if sql.startswith("SELECT") and "FROM usuario" in sql:
            return ResultadoFalso([self.usuario])
        if sql.startswith("SELECT id_postulacion FROM postulacion_auditor"):
            return ResultadoFalso([], escalar=None)
        if sql.startswith("SELECT id_conflicto FROM conflicto_interes"):
            existe = next(
                (
                    c["id_conflicto"]
                    for c in self.conflictos
                    if c["id_empresa"] == params["id_empresa"] and c["estado"] == "Activo"
                ),
                None,
            )
            return ResultadoFalso([], escalar=existe)
        if sql.startswith("DELETE FROM conflicto_interes WHERE id_usuario = :id_usuario"):
            if "id_conflicto <>" in sql:
                self.conflictos = [c for c in self.conflictos if c["id_conflicto"] == params["id_conflicto"]]
            else:
                self.conflictos = []
            return ResultadoFalso([])
        if sql.startswith("INSERT INTO conflicto_interes"):
            fila = {
                "id_conflicto": uuid.uuid4(),
                "id_empresa": params["id_empresa"],
                "tipo_conflicto": params["tipo_conflicto"],
                "descripcion": params["descripcion"],
                "estado": "Activo",
            }
            self.conflictos.append(fila)
            return ResultadoFalso([{"id_conflicto": fila["id_conflicto"]}])
        if sql.startswith("UPDATE conflicto_interes"):
            for c in self.conflictos:
                if c["id_conflicto"] == params["id_conflicto"]:
                    c["descripcion"] = params["descripcion"]
                    return ResultadoFalso([{"id_conflicto": c["id_conflicto"]}])
            return ResultadoFalso([])
        raise AssertionError(f"Consulta no esperada: {sql}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def conflicto(id_empresa=ID_EMPRESA):
    return {
        "id_conflicto": uuid.uuid4(),
        "id_empresa": id_empresa,
        "tipo_conflicto": "Exempleado",
        "descripcion": "previo",
        "estado": "Activo",
    }


def datos(id_empresa=ID_EMPRESA):
    return ConflictoInteresCrear(
        id_empresa=id_empresa,
        tipo_conflicto="Parentesco",
        descripcion="Mi hermano trabaja en la empresa",
    )


def test_auditor_aprobado_puede_declarar_conflicto_sin_borrar_los_demas():
    previo = conflicto(ID_OTRA_EMPRESA)
    sesion = SesionConflictos(estado_auditor="Activo", conflictos=[previo])

    respuesta = correr(AuditorService(sesion).declarar_conflicto(ID_USUARIO, datos()))

    assert respuesta["mensaje"] == "Conflicto de interés registrado correctamente."
    assert len(sesion.conflictos) == 2
    assert previo in sesion.conflictos
    assert not any(q.startswith("DELETE") for q in sesion.sql)
    assert sesion.commits == 1


def test_crear_conflicto_desde_registro_con_auditor_aprobado_ya_no_responde_409():
    previo = conflicto(ID_OTRA_EMPRESA)
    sesion = SesionConflictos(estado_auditor="Activo", conflictos=[previo])

    correr(AuditorService(sesion).crear_conflicto(ID_USUARIO, datos()))

    # Fuera del registro se agrega, no reemplaza.
    assert len(sesion.conflictos) == 2
    assert not any(q.startswith("DELETE") for q in sesion.sql)


def test_crear_conflicto_en_borrador_conserva_el_reemplazo_del_formulario():
    sesion = SesionConflictos(estado_auditor="Postulante", conflictos=[conflicto(ID_OTRA_EMPRESA)])

    correr(AuditorService(sesion).crear_conflicto(ID_USUARIO, datos()))

    assert len(sesion.conflictos) == 1
    assert sesion.conflictos[0]["id_empresa"] == ID_EMPRESA


def test_declarar_conflicto_repetido_con_la_misma_empresa_explica_que_hacer():
    sesion = SesionConflictos(conflictos=[conflicto(ID_EMPRESA)])

    with pytest.raises(HTTPException) as error:
        correr(AuditorService(sesion).declarar_conflicto(ID_USUARIO, datos(ID_EMPRESA)))

    assert error.value.status_code == 409
    assert "Actualizar conflicto" in error.value.detail
    assert len(sesion.conflictos) == 1


def test_cuenta_inactiva_no_declara_conflictos_y_el_mensaje_lo_explica():
    sesion = SesionConflictos(estado="Inactivo")

    with pytest.raises(HTTPException) as error:
        correr(AuditorService(sesion).declarar_conflicto(ID_USUARIO, datos()))

    assert error.value.status_code == 409
    assert "no está activa" in error.value.detail
    assert sesion.conflictos == []


def test_editar_un_conflicto_no_elimina_los_otros():
    editado = conflicto(ID_EMPRESA)
    otro = conflicto(ID_OTRA_EMPRESA)
    sesion = SesionConflictos(conflictos=[editado, otro])

    correr(AuditorService(sesion).actualizar_conflicto(ID_USUARIO, editado["id_conflicto"], datos()))

    assert len(sesion.conflictos) == 2
    assert editado["descripcion"] == "Mi hermano trabaja en la empresa"
    assert not any(q.startswith("DELETE") for q in sesion.sql)


def test_registro_bloqueado_explica_el_estado_y_que_hacer():
    sesion = SesionConflictos(estado_auditor="Activo")

    with pytest.raises(HTTPException) as error:
        correr(AuditorService(sesion)._verificar_usuario_borrador(ID_USUARIO))

    assert error.value.status_code == 409
    assert "'Activo'" in error.value.detail
    assert "nueva postulación" in error.value.detail


def test_ruta_para_declarar_conflicto_desde_la_pantalla_del_auditor():
    from main import app

    rutas = app.openapi()["paths"]
    assert "post" in rutas["/conflictos-auditor/usuario/{id_usuario}"]


# ------------------------------------------------------------------
# Disponibilidad extraordinaria repetida
# ------------------------------------------------------------------


class SesionDisponibilidad:
    def __init__(self, existe=False):
        self.existe = existe
        self.insertados = 0
        self.sql = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}
        self.sql.append(sql)
        if "FROM usuario" in sql:
            return ResultadoFalso([{"id_usuario": ID_USUARIO, "estado": "Activo", "estado_auditor": "Activo"}])
        if sql.startswith("SELECT id_disponibilidad FROM disponibilidad_auditor"):
            return ResultadoFalso([{"id_disponibilidad": uuid.uuid4()}] if self.existe else [])
        if sql.startswith("INSERT INTO disponibilidad_auditor"):
            self.insertados += 1
            return ResultadoFalso([{
                "id_disponibilidad": params["id_disponibilidad"],
                "id_usuario": params["id_usuario"],
                "tipo_registro": "Disponibilidad Extra",
                "dia_semana": params["dia_semana"],
                "fecha_inicio": params["fecha_inicio"],
                "fecha_fin": params["fecha_fin"],
                "hora_inicio": None,
                "hora_fin": None,
                "motivo": params["motivo"],
                "estado": "Activo",
            }])
        if sql.startswith("INSERT INTO historial_disponibilidad_auditor"):
            return ResultadoFalso([])
        raise AssertionError(f"Consulta no esperada: {sql}")

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _extra():
    inicio = date.today() + timedelta(days=7)
    return DisponibilidadExtraordinariaCrear(
        fecha_inicio=inicio, fecha_fin=inicio + timedelta(days=1), motivo="prueba"
    )


def test_disponibilidad_extraordinaria_repetida_no_crea_otra_fila():
    sesion = SesionDisponibilidad(existe=True)

    with pytest.raises(HTTPException) as error:
        correr(AgendaAuditorService(sesion).registrar_disponibilidad_extraordinaria(ID_USUARIO, _extra()))

    assert error.value.status_code == 409
    assert "Editar" in error.value.detail
    assert sesion.insertados == 0


def test_disponibilidad_extraordinaria_nueva_se_registra():
    sesion = SesionDisponibilidad(existe=False)

    respuesta = correr(AgendaAuditorService(sesion).registrar_disponibilidad_extraordinaria(ID_USUARIO, _extra()))

    assert respuesta["mensaje"] == "Disponibilidad extraordinaria registrada."
    assert sesion.insertados == 1
