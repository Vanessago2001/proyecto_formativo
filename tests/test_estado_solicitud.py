"""
El estado de una solicitud se escribe de una sola forma.

En la base convivían 'Radicada' y 'RADICADO', 'APROBADO' y 'Aprobada'. Para
una consulta no son lo mismo: `s.estado = 'APROBADO'` dejaba fuera a las
solicitudes guardadas como 'Aprobada', y la lista salía vacía sin que nada
avisara.

Aquí se comprueban las tres piezas que lo evitan:

  1. el catálogo reconoce cualquier grafía anterior;
  2. nadie escribe un estado fuera del catálogo;
  3. nadie compara contra una grafía suelta.
"""

import pathlib
import re

import pytest

from modules.apelaciones.apelaciones_service import estado_es_rechazada
from modules.comite.comite_service import CAMBIOS_ESTADO, ESTADOS_DICTAMEN, ESTADOS_FINALES
from modules.solicitudes import estado_solicitud as estados
from modules.solicitudes.solicitud_schema import EstadoSolicitud
from modules.solicitudes.trazabilidad_service import ESTADOS_ADMINISTRACION

PROYECTO = pathlib.Path(__file__).resolve().parent.parent
MODULOS = PROYECTO / "modules"


# ============================================================
# 1. EL CATÁLOGO
# ============================================================

@pytest.mark.parametrize(
    "escrito,canonico",
    [
        ("Radicada", estados.RADICADA),
        ("RADICADO", estados.RADICADA),
        ("radicado", estados.RADICADA),
        ("  RADICADA  ", estados.RADICADA),
        ("APROBADO", estados.APROBADA),
        ("Aprobada", estados.APROBADA),
        ("RECHAZADO", estados.RECHAZADA),
        ("Rechazada", estados.RECHAZADA),
        ("EN_REVISION", estados.EN_REVISION),
        ("En revision", estados.EN_REVISION),
        ("En revisión", estados.EN_REVISION),
        ("CANCELADO", estados.CANCELADA),
        ("CERRADO", estados.CERRADA),
        ("Borrador", estados.BORRADOR),
    ],
)
def test_cada_grafia_llega_al_mismo_estado(escrito, canonico):
    assert estados.normalizar(escrito) == canonico


@pytest.mark.parametrize("valor", ["", "   ", None, "Pendiente", "ACTIVO", "lo que sea"])
def test_un_estado_que_no_existe_no_se_inventa(valor):
    assert estados.normalizar(valor) is None


def test_exigir_avisa_con_el_valor_recibido():
    with pytest.raises(ValueError) as error:
        estados.exigir("ENTREGADO")
    assert "ENTREGADO" in str(error.value)
    assert "Radicada" in str(error.value)


def test_el_canonico_de_un_canonico_es_el_mismo():
    """Normalizar dos veces no cambia nada."""
    for estado in estados.ESTADOS:
        assert estados.normalizar(estado) == estado


def test_comparar_por_estado_no_depende_de_la_grafia():
    assert estados.es("APROBADO", estados.APROBADA)
    assert estados.es("Aprobada", estados.APROBADA)
    assert not estados.es("Rechazada", estados.APROBADA)


# ============================================================
# 2. NADIE ESCRIBE FUERA DEL CATÁLOGO
# ============================================================

def test_el_enum_de_m5_son_los_estados_del_catalogo():
    assert [e.value for e in EstadoSolicitud] == list(estados.ESTADOS)


def test_el_comite_escribe_estados_del_catalogo():
    """Guardaba 'APROBADO' mientras M5 guardaba 'Aprobada'."""
    for accion, estado in CAMBIOS_ESTADO.items():
        assert estado in estados.ESTADOS, f"{accion} escribe '{estado}', que no esta en el catalogo"


def test_los_conjuntos_del_comite_son_del_catalogo():
    for estado in ESTADOS_DICTAMEN | ESTADOS_FINALES:
        assert estado in estados.ESTADOS


def test_la_administracion_puede_fijar_todo_menos_borrador():
    """Un borrador lo crea la empresa; la administración no lo impone."""
    assert set(ESTADOS_ADMINISTRACION) == set(estados.ESTADOS) - {estados.BORRADOR}


# ============================================================
# 3. NADIE COMPARA CONTRA UNA GRAFÍA SUELTA
# ============================================================

# Las grafías que ya no deben aparecer escritas a mano en una consulta sobre
# `solicitud.estado`. Se buscan en el SQL de los módulos.
GRAFIAS_VIEJAS = ("RADICADO", "APROBADO", "RECHAZADO", "EN_REVISION", "CANCELADO", "CERRADO")

# El estado de un auditor, de una asignación o de una evidencia es otra cosa
# y sí usa esas palabras; solo interesan las comparaciones contra el estado
# de la solicitud.
PATRON_SOLICITUD = re.compile(
    r"(?:^|[^_\w])s\.estado\b[^\n]{0,80}|(?:^|[^_\w])solicitud\.estado\b[^\n]{0,80}",
    re.I,
)


def _fragmentos_sobre_solicitud() -> list[tuple[pathlib.Path, str]]:
    encontrados = []
    for archivo in MODULOS.rglob("*.py"):
        if "__pycache__" in archivo.parts:
            continue
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        for fragmento in PATRON_SOLICITUD.findall(texto):
            encontrados.append((archivo, fragmento))
    return encontrados


@pytest.mark.parametrize("grafia", GRAFIAS_VIEJAS)
def test_ninguna_consulta_compara_el_estado_con_una_grafia_vieja(grafia):
    culpables = [
        f"{archivo.relative_to(PROYECTO)}: {fragmento.strip()}"
        for archivo, fragmento in _fragmentos_sobre_solicitud()
        if f"'{grafia}'" in fragmento
    ]
    assert not culpables, (
        "Comparan el estado de la solicitud contra una grafia suelta; "
        "use modules/solicitudes/estado_solicitud.py:\n  " + "\n  ".join(culpables)
    )


def test_apelaciones_reconoce_el_rechazo_venga_como_venga():
    for escrito in ("Rechazada", "RECHAZADO", "rechazado", " RECHAZADA "):
        assert estado_es_rechazada(escrito) is True
    for escrito in ("Radicada", "APROBADO", "", None):
        assert estado_es_rechazada(escrito) is False
