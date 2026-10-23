"""
M5 — El estado de una solicitud se escribe de una sola forma.

En la base convivían 'Radicada' y 'RADICADO', 'APROBADO' y 'Aprobada',
'EN_REVISION' y 'En revision'. No son lo mismo para una consulta: cada
comparación con un literal exacto dejaba fuera las filas escritas con la
otra grafía, y el resultado parecía correcto aunque faltaran solicitudes.

Aquí viven los siete estados del ciclo y la forma de reconocer cualquier
grafía anterior:

  · lo que se **guarda** es siempre el valor canónico de este módulo;
  · lo que **llega de fuera** (otro módulo, una pantalla, un dato viejo)
    pasa por `normalizar` antes de compararlo;
  · la base tiene una restricción que solo admite estos siete valores, así
    que una grafía nueva falla al escribirse en vez de ensuciar en silencio.

El canon es en femenino y capitalizado, concordando con "la solicitud",
como el resto de estados del proyecto ('Activo', 'Pendiente', 'Aprobado').
"""

import unicodedata

BORRADOR = "Borrador"
RADICADA = "Radicada"
EN_REVISION = "En revision"
APROBADA = "Aprobada"
RECHAZADA = "Rechazada"
CANCELADA = "Cancelada"
CERRADA = "Cerrada"

ESTADOS = (BORRADOR, RADICADA, EN_REVISION, APROBADA, RECHAZADA, CANCELADA, CERRADA)

# Grafías que han existido en la base o en algún módulo, ya normalizadas
# (sin tildes, en mayúsculas y con los separadores como espacio).
ALIAS = {
    "BORRADOR": BORRADOR,
    "RADICADA": RADICADA,
    "RADICADO": RADICADA,
    "EN REVISION": EN_REVISION,
    "ENREVISION": EN_REVISION,
    "REVISION": EN_REVISION,
    "APROBADA": APROBADA,
    "APROBADO": APROBADA,
    "RECHAZADA": RECHAZADA,
    "RECHAZADO": RECHAZADA,
    "CANCELADA": CANCELADA,
    "CANCELADO": CANCELADA,
    "CERRADA": CERRADA,
    "CERRADO": CERRADA,
}


def _forma_comun(valor) -> str:
    """Sin tildes, en mayúsculas y con guiones bajos como espacios."""
    sin_tilde = unicodedata.normalize("NFD", str(valor or ""))
    limpio = "".join(c for c in sin_tilde if unicodedata.category(c) != "Mn")
    return " ".join(limpio.replace("_", " ").upper().split())


def normalizar(valor) -> str | None:
    """
    Devuelve el estado canónico, venga escrito como venga.

    Devuelve None si no se reconoce, para que quien llama decida: rechazar
    la entrada o dejar el dato como está.
    """
    return ALIAS.get(_forma_comun(valor))


def es(valor, canonico: str) -> bool:
    """True si `valor` es ese estado, sin importar cómo esté escrito."""
    return normalizar(valor) == canonico


def exigir(valor) -> str:
    """El estado canónico, o un error si no está en el catálogo."""
    estado = normalizar(valor)
    if estado is None:
        raise ValueError(
            f"Estado de solicitud desconocido: {valor!r}. "
            f"Los admitidos son: {', '.join(ESTADOS)}."
        )
    return estado


# Expresión SQL que lleva una columna de estado a su valor canónico. Se usa
# en las consultas que todavía pueden encontrarse con datos de antes.
def sql_canonico(columna: str) -> str:
    casos = "\n".join(
        f"                WHEN '{alias}' THEN '{canonico}'"
        for alias, canonico in ALIAS.items()
    )
    return (
        "CASE UPPER(TRANSLATE(TRIM(COALESCE(" + columna + ", '')), "
        "'ÁÉÍÓÚÜÑáéíóúüñ_', 'AEIOUUNaeiouun '))\n"
        f"{casos}\n"
        f"                ELSE TRIM(COALESCE({columna}, ''))\n"
        "            END"
    )
