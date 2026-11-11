"""Regresión de los hallazgos de "Testing_Software_CertiSENA_Marlon_2.0"."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

from modules.consultas_p import consultas_service
from modules.consultas_p.consultas_service import CERTIFICADO_PUBLICADO_Y_FIRMADO
from modules.users import gestion_cuenta_service


def test_restablecer_password_envia_una_fecha_y_no_un_texto():
    # asyncpg rechazaba el texto en el parámetro TIMESTAMP y el Coordinador
    # veía "No fue posible completar la acción".
    assert isinstance(gestion_cuenta_service.FECHA_PASSWORD_VENCIDA, datetime)


def test_el_portal_publico_solo_muestra_certificados_firmados():
    for requisito in ("publico_certificado IS TRUE", "id_firmante IS NOT NULL",
                      "huella_firmante IS NOT NULL", "codigo_hash IS NOT NULL", "huella_pdf IS NOT NULL"):
        assert requisito in CERTIFICADO_PUBLICADO_Y_FIRMADO


class _Db:
    """Devuelve vacío en todo y guarda el SQL ejecutado."""

    def __init__(self):
        self.sql = []

    async def execute(self, sentencia, params=None):
        self.sql.append(str(sentencia))
        resultado = MagicMock()
        resultado.mappings.return_value.all.return_value = []
        resultado.mappings.return_value.first.return_value = None
        return resultado


def test_radicado_inexistente_con_nit_valido_no_muestra_la_empresa():
    db = _Db()
    filas = asyncio.run(
        consultas_service.ConsultasPublicasService(db).consulta_publica(codigo="RAD-9999-999", nit="900123456-7")
    )
    assert filas == []
    # Solo la búsqueda de trámites: no se consulta la empresa como respaldo.
    assert len(db.sql) == 1


def test_solo_nit_si_muestra_la_empresa_como_respaldo():
    db = _Db()
    asyncio.run(consultas_service.ConsultasPublicasService(db).consulta_publica(nit="900123456-7"))
    assert len(db.sql) == 2
    assert all(CERTIFICADO_PUBLICADO_Y_FIRMADO in sql for sql in db.sql[:1])


def test_filtro_de_norma_es_parcial_y_sin_guiones():
    from modules.asignacion_auditores.asignacion_service import AsignacionAuditorService

    capturado = {}

    class Db:
        async def execute(self, sentencia, params=None):
            capturado.setdefault("sql", str(sentencia))
            capturado.setdefault("params", params or {})
            resultado = MagicMock()
            resultado.mappings.return_value.all.return_value = []
            resultado.scalar.return_value = 0
            resultado.mappings.return_value.first.return_value = {"total": 0}
            return resultado

    asyncio.run(AsignacionAuditorService(Db()).listar_solicitudes_aprobadas(page=1, page_size=12, norma="ISO-9001"))
    assert capturado["params"]["norma"] == "iso9001"
    assert "LIKE '%' || :norma || '%'" in capturado["sql"]
