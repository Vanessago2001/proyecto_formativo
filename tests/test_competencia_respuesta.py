from datetime import date
from uuid import uuid4

from modules.auditores.auditor_schema import CompetenciaAuditorRespuesta


def test_respuesta_de_competencia_conserva_postulacion_y_observacion():
    id_postulacion = uuid4()
    competencia = CompetenciaAuditorRespuesta.model_validate({
        "id_competencia": uuid4(),
        "id_postulacion": id_postulacion,
        "id_norma": uuid4(),
        "tipo_competencia": "Norma ISO",
        "codigo_sector_iaf": "01",
        "titulo_institucion": "Institución",
        "descripcion": "Experiencia",
        "fecha_inicio": date(2024, 1, 1),
        "fecha_fin": date(2025, 1, 1),
        "es_vigente": True,
        "estado_validacion": "Rechazado",
        "observacion_validacion": "Adjunte el soporte correspondiente.",
    })

    respuesta = competencia.model_dump()

    assert respuesta["id_postulacion"] == id_postulacion
    assert respuesta["estado_validacion"] == "Rechazado"
    assert respuesta["observacion_validacion"] == "Adjunte el soporte correspondiente."
