from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from modules.comite.comite_service import ComiteService


def resultado_falso(fila=None):
    resultado = MagicMock()
    resultado.mappings.return_value.first.return_value = fila
    return resultado


@pytest.mark.asyncio
async def test_aprobar_guarda_accion_y_actualiza_estado_en_una_transaccion():
    id_solicitud = uuid4()
    id_accion = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        resultado_falso({"id_solicitud": id_solicitud, "estado": "Radicada"}),
        resultado_falso({"estado": "APROBADO"}),
        resultado_falso(),
        resultado_falso({
            "id_accion": id_accion,
            "id_solicitud": id_solicitud,
            "accion": "aprobar",
            "fecha": datetime.now(timezone.utc),
        }),
    ]

    respuesta = await ComiteService(db).registrar_accion(
        "aprobar",
        {"expediente_id": str(id_solicitud), "comentario": "Cumple los requisitos"},
        {"id_usuario": str(uuid4()), "nombre": "Administración"},
    )

    assert respuesta["id_accion"] == str(id_accion)
    assert respuesta["estado"] == "APROBADO"
    assert db.execute.await_count == 4
    assert db.commit.await_count == 1
    assert "UPDATE solicitud" in str(db.execute.await_args_list[1].args[0])
    assert "INSERT INTO historial_estado" in str(db.execute.await_args_list[2].args[0])
    assert "INSERT INTO comite_accion" in str(db.execute.await_args_list[3].args[0])


@pytest.mark.asyncio
async def test_firma_se_persiste_sin_pretender_que_se_genero_un_pdf():
    id_solicitud = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        resultado_falso({"id_solicitud": id_solicitud, "estado": "Aprobada"}),
        resultado_falso({
            "id_accion": uuid4(),
            "id_solicitud": id_solicitud,
            "accion": "firmar-acta",
            "fecha": datetime.now(timezone.utc),
        }),
    ]

    respuesta = await ComiteService(db).registrar_accion(
        "firmar-acta",
        {"expediente_id": str(id_solicitud), "comentario": "Firmo el acta"},
        {"id_usuario": str(uuid4())},
    )

    assert respuesta["estado"] == "Aprobada"
    assert "aún no se genera firma electrónica ni PDF" in respuesta["mensaje"]
    assert "INSERT INTO comite_accion" in str(db.execute.await_args_list[1].args[0])
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_no_registra_una_decision_sobre_expediente_ya_finalizado():
    db = AsyncMock()
    db.execute.return_value = resultado_falso({"id_solicitud": uuid4(), "estado": "APROBADO"})

    with pytest.raises(HTTPException) as error:
        await ComiteService(db).registrar_accion(
            "rechazar",
            {"expediente_id": str(uuid4()), "comentario": "No cumple"},
            {"id_usuario": str(uuid4())},
        )

    assert error.value.status_code == 409
    assert db.execute.await_count == 1
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_permite_firmar_un_acta_antes_de_un_dictamen():
    db = AsyncMock()
    db.execute.return_value = resultado_falso({"id_solicitud": uuid4(), "estado": "Radicada"})

    with pytest.raises(HTTPException) as error:
        await ComiteService(db).registrar_accion(
            "firmar-acta",
            {"expediente_id": str(uuid4()), "comentario": "Firmo"},
            {"id_usuario": str(uuid4())},
        )

    assert error.value.status_code == 409
    assert db.execute.await_count == 1
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("accion", "estado_anterior", "estado_esperado"),
    [
        ("cerrar-expediente", "APROBADO", "CERRADO"),
        ("reabrir-dictamen", "CERRADO", "En revision"),
    ],
)
async def test_cerrar_y_reabrir_actualizan_el_estado_y_el_historial(
    accion,
    estado_anterior,
    estado_esperado,
):
    id_solicitud = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        resultado_falso({"id_solicitud": id_solicitud, "estado": estado_anterior}),
        resultado_falso({"estado": estado_esperado}),
        resultado_falso(),
        resultado_falso({
            "id_accion": uuid4(),
            "id_solicitud": id_solicitud,
            "accion": accion,
            "fecha": datetime.now(timezone.utc),
        }),
    ]

    respuesta = await ComiteService(db).registrar_accion(
        accion,
        {"expediente_id": str(id_solicitud), "comentario": "Cambio de estado autorizado"},
        {"id_usuario": str(uuid4())},
    )

    assert respuesta["estado"] == estado_esperado
    assert db.execute.await_count == 4
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_no_guarda_si_falta_comentario():
    db = AsyncMock()

    with pytest.raises(HTTPException) as error:
        await ComiteService(db).registrar_accion(
            "aprobar",
            {"expediente_id": str(uuid4()), "comentario": " "},
            {"id_usuario": str(uuid4())},
        )

    assert error.value.status_code == 422
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
