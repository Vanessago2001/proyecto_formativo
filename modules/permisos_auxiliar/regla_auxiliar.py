"""
Regla única del Auxiliar.

Decisión del equipo: "Los permisos del auxiliar deben ser puestos
exclusivamente por el Coordinador."

El Auxiliar no tiene ningún permiso propio. Todo lo que la columna AUX de la
matriz le concede depende de un permiso delegado vigente que el Coordinador
otorga en "Permisos de auxiliares" (catálogo en permisos_auxiliar_catalogo.py):

    V / Cond.  sin permiso delegado -> 403 (MENSAJE_SIN_PERMISO)
               con permiso delegado -> permitido
    REQ        sin cambio: con permiso delegado se ejecuta directo y, sin él,
               queda como solicitud de aprobación (modules/aprobaciones)
    F / SA     denegado (no delegable)

Los demás roles no cambian.

De dónde salen los permisos: `core.security.get_current_user` carga una sola
vez por petición los códigos vigentes del auxiliar en
`usuario["permisos_delegados"]` (permisos_auxiliar_service.codigos_vigentes).
Así todas las comprobaciones de aquí son síncronas. Si la clave no está (un
usuario armado a mano), el auxiliar no tiene ningún permiso: el valor seguro.

Puntos de uso:
  · Matrices de M5, M7 y M9 (`requiere_permiso`, `exigir_permisos`) llaman a
    `nivel_efectivo`, así sus endpoints no necesitan nada más.
  · Endpoints con chequeo de rol directo (Empresas, Comité, Apelaciones,
    Reportes, Banco de auditores...) llaman a `exigir_permiso_auxiliar` o usan
    `require_role(..., auxiliar=delegable("EMP-003"))`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

ROL_AUXILIAR = "auxiliar"
CLAVE_DELEGADOS = "permisos_delegados"
MENSAJE_SIN_PERMISO = (
    "No tienes este permiso. El Coordinador puede otorgártelo en Permisos de auxiliares."
)

V = "V"
F = "F"
REQ = "REQ"
SA = "SA"
COND = "Cond."


def _rol(usuario: dict | None) -> str:
    # Import diferido: core.security importa este módulo dentro de funciones.
    from core.security import _normalize_role_name

    return _normalize_role_name((usuario or {}).get("role_name") or (usuario or {}).get("rol"))


def es_auxiliar(usuario: dict | None) -> bool:
    return bool(usuario) and _rol(usuario) == ROL_AUXILIAR


def delegados(usuario: dict | None) -> frozenset[str]:
    """Códigos delegados vigentes que trae la sesión (vacío si no hay)."""
    valores = (usuario or {}).get(CLAVE_DELEGADOS) or ()
    return frozenset(str(c).strip().upper() for c in valores if c)


def tiene_delegado(usuario: dict | None, *codigos: str) -> bool:
    """True si el auxiliar tiene al menos uno de esos códigos delegados."""
    propios = delegados(usuario)
    return any((c or "").strip().upper() in propios for c in codigos)


def error_sin_permiso(*codigos: str) -> HTTPException:
    detalle = MENSAJE_SIN_PERMISO
    if codigos:
        detalle += " (Permiso: " + ", ".join(codigos) + ")"
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detalle)


def exigir_permiso_auxiliar(usuario: dict | None, *codigos: str) -> None:
    """
    Para endpoints con chequeo de rol directo: si quien llama es Auxiliar,
    necesita al menos uno de `codigos` delegado; si no, 403. Los demás roles
    pasan sin cambios (su chequeo de rol ya se hizo).
    """
    if not es_auxiliar(usuario):
        return
    if codigos and tiene_delegado(usuario, *codigos):
        return
    raise error_sin_permiso(*codigos)


def _valor(nivel) -> str:
    return str(getattr(nivel, "value", nivel) or "")


def nivel_efectivo(usuario: dict | None, codigo: str, nivel):
    """
    LA regla central. Recibe el nivel que la matriz asigna al rol y devuelve
    el que vale para esta sesión:

      · otro rol            -> el mismo nivel
      · Auxiliar, F o SA    -> el mismo nivel (denegado; no delegable)
      · Auxiliar, REQ       -> REQ (el flujo de aprobación ya contempla el
                               permiso delegado: se ejecuta directo con él)
      · Auxiliar, V o Cond. -> V si tiene `codigo` delegado; si no, 403
    """
    if not es_auxiliar(usuario):
        return nivel
    valor = _valor(nivel)
    if valor in (F, SA, REQ):
        return nivel
    if tiene_delegado(usuario, codigo):
        return nivel
    raise error_sin_permiso(codigo)


# ------------------------------------------------------------------
# Para require_role(..., auxiliar=...)
# ------------------------------------------------------------------


@dataclass(frozen=True)
class PermisoAuxiliar:
    """Qué necesita el Auxiliar para pasar un chequeo de rol directo."""

    codigos: tuple[str, ...]
    # REQ: sin permiso delegado el auxiliar pasa igual, porque la acción queda
    # como solicitud de aprobación (con él se ejecuta directo).
    req: bool = False
    # Acceso propio del auxiliar que no es un permiso de la matriz (p. ej. ver
    # el estado de las aprobaciones que él mismo pidió).
    propio: bool = False

    def exigir(self, usuario: dict | None) -> None:
        if self.req or self.propio:
            return
        exigir_permiso_auxiliar(usuario, *self.codigos)


def delegable(*codigos: str) -> PermisoAuxiliar:
    """V / Cond.: el Auxiliar necesita al menos uno de estos códigos delegado."""
    return PermisoAuxiliar(tuple(codigos))


def con_aprobacion(*codigos: str) -> PermisoAuxiliar:
    """REQ: el Auxiliar pasa; la acción va a aprobación salvo permiso delegado."""
    return PermisoAuxiliar(tuple(codigos), req=True)


# Acceso propio (no es un permiso de la matriz): solo lo suyo.
PROPIO = PermisoAuxiliar((), propio=True)
