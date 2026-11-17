"""
Rol único "Auditor" (17/11/2026): cualquier auditor asignado a la visita la
finaliza (antes solo el auditor líder; si su rol no llegaba recibía 403).
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modules.agenda_auditor.agenda_service import AgendaAuditorService


async def test_la_consulta_del_equipo_lee_todos_como_auditor():
    db = AsyncMock()
    resultado = MagicMock()
    resultado.mappings.return_value.all.return_value = [
        {"id_usuario": uuid4(), "nombre": "Leonel", "correo": "l@x.co", "rol_auditor": "Auditor"}
    ]
    db.execute.return_value = resultado

    auditores = await AgendaAuditorService(db)._auditores_de_programacion(uuid4())

    sql = str(db.execute.call_args.args[0])
    assert "'Auditor' AS rol_auditor" in sql
    assert auditores[0]["rol_auditor"] == "Auditor"


def _servicio(auditores, estado="Programada"):
    db = AsyncMock()
    programacion = MagicMock()
    programacion.mappings.return_value.first.return_value = {"id_programacion": uuid4(), "estado": estado}
    db.execute.return_value = programacion
    servicio = AgendaAuditorService(db)
    servicio._auditores_de_programacion = AsyncMock(return_value=auditores)
    return servicio, db


@pytest.mark.parametrize("rol_guardado", ["Observador", "Auditor Técnico", "Auditor Líder", None])
async def test_cualquier_auditor_asignado_finaliza(rol_guardado):
    yo = uuid4()
    servicio, db = _servicio([
        {"id_usuario": uuid4(), "rol_auditor": "Auditor Líder"},
        {"id_usuario": yo, "rol_auditor": rol_guardado},
    ])
    try:
        await servicio.finalizar_programacion(uuid4(), yo, "Visita terminada sin novedades.")
    except HTTPException as error:  # pasos posteriores no son el objeto de la prueba
        assert error.status_code != 403, error.detail
    sentencias = [str(c.args[0]) for c in db.execute.call_args_list]
    assert any("SET estado = 'Finalizada'" in sql for sql in sentencias)


async def test_quien_no_esta_asignado_no_finaliza():
    servicio, _db = _servicio([{"id_usuario": uuid4(), "rol_auditor": "Auditor"}])
    with pytest.raises(HTTPException) as error:
        await servicio.finalizar_programacion(uuid4(), uuid4(), "Intento ajeno.")
    assert error.value.status_code == 403
    assert "asignado a esta visita" in error.value.detail


@pytest.mark.parametrize("rol", ["Auditor líder", "Observador", "Experto técnicos", None, ""])
def test_la_agenda_guarda_siempre_el_mismo_rol_en_el_detalle(rol):
    """El rol pedido se ignora; se guarda el valor que admite chk_rol_auditor."""
    from modules.asignacion_auditores.rol_auditor import ROL_DETALLE_BD

    assert AgendaAuditorService(AsyncMock())._normalizar_rol_agenda(rol) == ROL_DETALLE_BD
