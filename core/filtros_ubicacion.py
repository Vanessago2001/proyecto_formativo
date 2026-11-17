"""Filtros de ubicación (ciudad, departamento, país) para las consultas SQL.

La base no tiene la extensión `unaccent`, así que se compara con
LOWER(TRANSLATE(...)) igual que el resto del proyecto. El texto buscado se
normaliza en Python de la misma forma (minúsculas y sin tildes) y la
coincidencia es parcial: "bogo" encuentra "Bogotá".
"""

import unicodedata

_CON_TILDE = "ÁÉÍÓÚÜÑÀÈÌÒÙáéíóúüñàèìòù"
_SIN_TILDE = "AEIOUUNAEIOUaeiouunaeiou"


def texto_comparable(valor) -> str:
    """Minúsculas, sin tildes y con los espacios internos colapsados."""
    texto = unicodedata.normalize("NFD", str(valor or "").strip().lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.split())


def sql_comparable(expresion: str) -> str:
    """Expresión SQL equivalente a `texto_comparable` sobre una columna."""
    return f"LOWER(TRANSLATE(COALESCE({expresion}, ''), '{_CON_TILDE}', '{_SIN_TILDE}'))"


def patron_contiene(valor) -> str | None:
    """Patrón LIKE (con % y _ escapados) o None si el filtro está vacío."""
    texto = texto_comparable(valor)
    if not texto:
        return None
    texto = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{texto}%"


def condicion_contiene(expresion: str, parametro: str) -> str:
    """`<expresión normalizada> LIKE :parametro` (usar con `patron_contiene`)."""
    return f"{sql_comparable(expresion)} LIKE :{parametro} ESCAPE '\\'"


def condiciones_ubicacion_solicitud(
    ciudad: str | None = None,
    departamento: str | None = None,
    pais: str | None = None,
    alias_solicitud: str = "s",
    alias_empresa: str = "e",
) -> tuple[list[str], dict]:
    """Filtros de ubicación para listados de solicitudes.

    La ciudad puede ser la de la empresa o la de alguna sede incluida en la
    solicitud; departamento y país solo existen en las sedes ("alguna sede
    en ..."). Las sedes excluidas de la solicitud no cuentan.
    """
    sede_incluida = (
        "EXISTS (SELECT 1 FROM solicitud_sede ss_u JOIN sede_empresa se_u ON se_u.id_sede = ss_u.id_sede"
        f" WHERE ss_u.id_solicitud = {alias_solicitud}.id_solicitud AND ss_u.estado <> 'Excluida' AND {{condicion}})"
    )
    condiciones: list[str] = []
    params: dict = {}
    if patron_contiene(ciudad):
        condiciones.append(
            "(" + condicion_contiene(f"{alias_empresa}.ciudad", "ubic_ciudad") + " OR "
            + sede_incluida.format(condicion=condicion_contiene("se_u.ciudad", "ubic_ciudad")) + ")"
        )
        params["ubic_ciudad"] = patron_contiene(ciudad)
    if patron_contiene(departamento):
        condiciones.append(sede_incluida.format(condicion=condicion_contiene("se_u.departamento", "ubic_departamento")))
        params["ubic_departamento"] = patron_contiene(departamento)
    if patron_contiene(pais):
        condiciones.append(sede_incluida.format(condicion=condicion_contiene("se_u.pais", "ubic_pais")))
        params["ubic_pais"] = patron_contiene(pais)
    return condiciones, params
