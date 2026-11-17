"""
El auditor líder debe poder finalizar su auditoría.

`finalizar_programacion` reconoce al líder por `rol_auditor`; la consulta
`_auditores_de_programacion` no traía esa columna y el líder recibía siempre
403 "Solo el auditor lider puede finalizar esta auditoria".
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from modules.agenda_auditor.agenda_service import AgendaAuditorService


async def test_la_consulta_del_equipo_trae_el_rol_de_cada_auditor():
    db = AsyncMock()
    resultado = MagicMock()
    resultado.mappings.return_value.all.return_value = [
        {"id_usuario": uuid4(), "nombre": "Leonel", "correo": "l@x.co", "rol_auditor": "Auditor Líder"}
    ]
    db.execute.return_value = resultado

    auditores = await AgendaAuditorService(db)._auditores_de_programacion(uuid4())

    sql = str(db.execute.call_args.args[0])
    assert "rol_auditor" in sql
    assert auditores[0]["rol_auditor"] == "Auditor Líder"
