"""Regresión: corregir una competencia devuelta no debe crear una segunda fila.

El administrador rechaza la competencia en "banco de auditores → ver solicitud" y
deja la fila en 'Rechazado' con su observación. Cuando el auditor vuelve a guardar
la sección desde el formulario de registro, esa misma fila debe sustituirse; si se
inserta una nueva, la postulación queda con dos competencias y la devuelta sigue
marcando la sección del auditor.
"""

import uuid
from datetime import date

from modules.auditores.auditor_schema import CompetenciaAuditorCrear
from modules.auditores.auditor_service import AuditorService
from tests.fake_db import ResultadoFalso

ID_USUARIO = uuid.UUID("11111111-1111-1111-1111-111111111111")
ID_POSTULACION = uuid.UUID("22222222-2222-2222-2222-222222222222")
ID_OTRA_POSTULACION = uuid.UUID("33333333-3333-3333-3333-333333333333")

ISO = "Norma ISO"
CURSO = "Curso"


def competencia(
    tipo_competencia: str = ISO,
    estado_validacion: str = "Pendiente",
    id_postulacion: uuid.UUID = ID_POSTULACION,
    titulo_institucion: str = "Versión antigua",
) -> dict:
    return {
        "id_competencia": uuid.uuid4(),
        "id_usuario": ID_USUARIO,
        "id_postulacion": id_postulacion,
        "tipo_competencia": tipo_competencia,
        "id_norma": uuid.uuid4(),
        "codigo_sector_iaf": "01",
        "titulo_institucion": titulo_institucion,
        "descripcion": "descripcion antigua",
        "fecha_inicio": date(2024, 1, 1),
        "fecha_fin": date(2024, 12, 31),
        "es_vigente": False,
        "estado_validacion": estado_validacion,
        "observacion_validacion": (
            "Falta el soporte de la norma" if estado_validacion == "Rechazado" else None
        ),
    }


class SesionCompetencias:
    """Doble de `competencia_auditor` en memoria, con las consultas que usa el servicio."""

    def __init__(self, competencias: list[dict]):
        self.competencias = competencias
        self.commitido = False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = params or {}

        if "FROM postulacion_auditor" in sql:
            return ResultadoFalso(escalar=ID_POSTULACION)

        if "FROM usuario" in sql and "estado_auditor" in sql:
            return ResultadoFalso([
                {
                    "id_usuario": ID_USUARIO,
                    "nombre": "Ana Auditora",
                    "correo": "ana@example.com",
                    "estado": "Activo",
                    "estado_auditor": "Postulante",
                    "tipo_doc": "Cédula de Ciudadanía",
                    "num_doc": "1010101010",
                }
            ])

        if "FROM competencia_auditor" in sql and "estado_validacion = 'Rechazado'" in sql:
            filas = [
                fila
                for fila in self.competencias
                if fila["estado_validacion"] == "Rechazado"
                and str(fila["id_postulacion"]) == str(params["id_postulacion"])
            ]
            # Equivale a ORDER BY (tipo = :tipo) DESC, id_competencia.
            filas.sort(
                key=lambda fila: (
                    fila["tipo_competencia"] != params["tipo_competencia"],
                    str(fila["id_competencia"]),
                )
            )
            return ResultadoFalso(filas)

        if sql.startswith("UPDATE competencia_auditor"):
            objetivo = next(
                (
                    fila
                    for fila in self.competencias
                    if str(fila["id_competencia"]) == str(params["id_competencia"])
                    and str(fila["id_usuario"]) == str(params["id_usuario"])
                ),
                None,
            )
            if objetivo is None:
                return ResultadoFalso([])
            objetivo.update(
                {
                    "id_norma": params["id_norma"],
                    "tipo_competencia": params["tipo_competencia"],
                    "codigo_sector_iaf": params["codigo_sector_iaf"],
                    "titulo_institucion": params["titulo_institucion"],
                    "descripcion": params["descripcion"],
                    "fecha_inicio": params["fecha_inicio"],
                    "fecha_fin": params["fecha_fin"],
                    "es_vigente": params["es_vigente"],
                    "estado_validacion": "Pendiente",
                    "observacion_validacion": None,
                }
            )
            return ResultadoFalso([dict(objetivo)])

        if sql.startswith("DELETE FROM competencia_auditor"):
            self.competencias = [
                fila
                for fila in self.competencias
                if str(fila["id_competencia"]) != str(params["id_competencia"])
            ]
            return ResultadoFalso([])

        if sql.startswith("INSERT INTO competencia_auditor"):
            nueva = {
                "id_competencia": uuid.uuid4(),
                "id_usuario": ID_USUARIO,
                "id_postulacion": params["id_postulacion"],
                "tipo_competencia": params["tipo_competencia"],
                "id_norma": params["id_norma"],
                "codigo_sector_iaf": params["codigo_sector_iaf"],
                "titulo_institucion": params["titulo_institucion"],
                "descripcion": params["descripcion"],
                "fecha_inicio": params["fecha_inicio"],
                "fecha_fin": params["fecha_fin"],
                "es_vigente": params["es_vigente"],
                "estado_validacion": "Pendiente",
                "observacion_validacion": None,
            }
            self.competencias.append(nueva)
            return ResultadoFalso([dict(nueva)])

        raise AssertionError(f"Consulta no contemplada por el doble: {sql[:120]}")

    async def commit(self):
        self.commitido = True

    async def rollback(self):
        raise AssertionError(
            "El reemplazo de la competencia no deberia llegar al rollback."
        )


def edicion(tipo_competencia: str = ISO, titulo: str = "Versión corregida"):
    return CompetenciaAuditorCrear(
        id_norma=uuid.uuid4(),
        tipo_competencia=tipo_competencia,
        codigo_sector_iaf="12",
        titulo_institucion=titulo,
        descripcion="descripcion corregida",
        fecha_inicio=date(2025, 1, 1),
        fecha_fin=date(2025, 12, 31),
        es_vigente=True,
    )


async def guardar(sesion, data=None):
    return await AuditorService(sesion).crear_competencia(
        id_usuario=ID_USUARIO,
        data=data or edicion(),
    )


async def test_la_competencia_devuelta_se_sustituye_en_su_propia_fila():
    rechazada = competencia(estado_validacion="Rechazado")
    id_rechazada = rechazada["id_competencia"]

    sesion = SesionCompetencias([rechazada])
    respuesta = await guardar(sesion)

    assert len(sesion.competencias) == 1
    actual = sesion.competencias[0]

    # Es la misma fila: no nace una segunda competencia.
    assert actual["id_competencia"] == id_rechazada
    assert respuesta["id_competencia"] == id_rechazada

    # La edicion nueva reemplaza los datos rechazados.
    assert actual["titulo_institucion"] == "Versión corregida"
    assert actual["descripcion"] == "descripcion corregida"
    assert actual["codigo_sector_iaf"] == "12"
    assert actual["fecha_inicio"] == date(2025, 1, 1)
    assert actual["es_vigente"] is True

    # Sin el rastro del rechazo, que es lo que quita el punto rojo del formulario.
    assert actual["estado_validacion"] == "Pendiente"
    assert actual["observacion_validacion"] is None
    assert sesion.commitido is True


async def test_deja_una_sola_cuando_ya_habia_duplicadas_del_mismo_tipo():
    """El propio error dejo antes dos filas rechazadas del mismo tipo."""
    primera = competencia(estado_validacion="Rechazado", titulo_institucion="duplicada a")
    segunda = competencia(estado_validacion="Rechazado", titulo_institucion="duplicada b")
    ids = {str(primera["id_competencia"]), str(segunda["id_competencia"])}

    sesion = SesionCompetencias([primera, segunda])
    await guardar(sesion)

    assert len(sesion.competencias) == 1
    assert str(sesion.competencias[0]["id_competencia"]) in ids
    assert sesion.competencias[0]["estado_validacion"] == "Pendiente"


async def test_sin_competencia_devuelta_se_inserta_una():
    sesion = SesionCompetencias([])
    respuesta = await guardar(sesion)

    assert len(sesion.competencias) == 1
    assert sesion.competencias[0]["id_competencia"] == respuesta["id_competencia"]
    assert sesion.competencias[0]["estado_validacion"] == "Pendiente"


async def test_no_toca_las_outras_competencias_de_la_postulacion():
    """La devuelta no puede borrar los cursos pendientes ni los ya validados."""
    rechazada = competencia(estado_validacion="Rechazado")
    curso = competencia(tipo_competencia=CURSO, estado_validacion="Pendiente")
    validada = competencia(tipo_competencia=CURSO, estado_validacion="Validado")

    sesion = SesionCompetencias([rechazada, curso, validada])
    await guardar(sesion)

    guardadas = {str(fila["id_competencia"]): fila for fila in sesion.competencias}
    assert set(guardadas) == {
        str(rechazada["id_competencia"]),
        str(curso["id_competencia"]),
        str(validada["id_competencia"]),
    }
    assert guardadas[str(rechazada["id_competencia"])]["titulo_institucion"] == "Versión corregida"
    assert guardadas[str(curso["id_competencia"])]["titulo_institucion"] == "Versión antigua"
    assert guardadas[str(validada["id_competencia"])]["estado_validacion"] == "Validado"


async def test_con_varias_devueltas_elige_la_del_mismo_tipo():
    """Un curso devuelto no se pisa cuando se corrige la competencia ISO."""
    rechazada_iso = competencia(estado_validacion="Rechazado")
    rechazada_curso = competencia(
        tipo_competencia=CURSO,
        estado_validacion="Rechazado",
        titulo_institucion="curso devuelto",
    )

    sesion = SesionCompetencias([rechazada_iso, rechazada_curso])
    respuesta = await guardar(sesion, edicion(tipo_competencia=CURSO))

    assert respuesta["id_competencia"] == rechazada_curso["id_competencia"]
    assert rechazada_curso["estado_validacion"] == "Pendiente"
    assert rechazada_iso["estado_validacion"] == "Rechazado"
    assert len(sesion.competencias) == 2


async def test_la_devuelta_de_otra_postulacion_no_se_reemplaza():
    rechazada_ajena = competencia(
        estado_validacion="Rechazado",
        id_postulacion=ID_OTRA_POSTULACION,
    )

    sesion = SesionCompetencias([rechazada_ajena])
    await guardar(sesion)

    assert rechazada_ajena["estado_validacion"] == "Rechazado"
    assert len(sesion.competencias) == 2
