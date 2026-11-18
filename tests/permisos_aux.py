"""
Ayudas de prueba para la regla del Auxiliar
(modules/permisos_auxiliar/regla_auxiliar.py).

El Auxiliar no tiene permisos propios: en producción `get_current_user`
carga sus códigos delegados vigentes en `usuario["permisos_delegados"]`. Las
pruebas que sustituyen al usuario simulan aquí la delegación del Coordinador.
"""

from modules.permisos_auxiliar.permisos_auxiliar_service import permisos_delegables
from modules.permisos_auxiliar.regla_auxiliar import CLAVE_DELEGADOS, MENSAJE_SIN_PERMISO, es_auxiliar

__all__ = ["MENSAJE_SIN_PERMISO", "con_permisos", "todos_los_permisos", "es_aux"]


def todos_los_permisos() -> tuple[str, ...]:
    """Todo el catálogo delegable (un auxiliar al que se le otorgó todo)."""
    return tuple(p["codigo"] for p in permisos_delegables())


def es_aux(rol: str | None) -> bool:
    return es_auxiliar({"role_name": rol})


def con_permisos(usuario: dict, *codigos: str) -> dict:
    """
    Simula que el Coordinador otorgó `codigos` (o todo el catálogo si no se
    indican) al usuario, solo si es Auxiliar. Devuelve el mismo dict.
    """
    if es_aux(usuario.get("role_name")):
        usuario[CLAVE_DELEGADOS] = tuple(codigos) if codigos else todos_los_permisos()
    return usuario
