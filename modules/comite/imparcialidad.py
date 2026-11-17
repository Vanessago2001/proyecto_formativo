"""
Imparcialidad del Comité de certificación.

Un miembro del Comité no puede ver ni decidir un expediente si ya participó
antes en esa solicitud o en su apelación: la evaluación la hace siempre una
persona externa a quienes ya la evaluaron. El Coordinador (y el Auxiliar)
no están sujetos a esta regla; solo aplica al rol Comité.

"Participó" se determina con lo que ya registra el sistema:

  · Evaluación anterior de la solicitud: una acción en `comite_accion`
    (`id_usuario`) de una ronda ANTERIOR. Una ronda termina cuando el
    Coordinador reabre el dictamen (acción 'reabrir-dictamen'): quien actuó
    antes de la última reapertura ya no puede volver a evaluarla. Dentro de
    la ronda vigente los miembros siguen trabajando sobre su expediente
    (borrador, debate, decisión). La firma del acta ('firmar-acta') no
    cuenta: firmar no es evaluar.
  · Apelación de la solicitud (`apelacion.id_solicitud`): estar asignado a
    su comité (`apelacion_comite.id_usuario`), haberla decidido
    (`apelacion.id_usuario_revisa`), ser su evaluador
    (`apelacion.id_auditor_evaluador`) o haberle pedido información
    (`requerimiento_apelacion.id_usuario_solicita`).

La firma del certificado (líder del Comité, `asignacion_lider_comite`) y la
del acta no se bloquean con esta regla.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name

MOTIVO_SOLICITUD = "solicitud"
MOTIVO_APELACION = "apelacion"

MENSAJES = {
    MOTIVO_SOLICITUD: "No puede evaluarlo: ya participó en una evaluación anterior de esta solicitud.",
    MOTIVO_APELACION: "No puede evaluarlo: ya participó en la apelación de esta solicitud.",
}

# Acciones que no son "evaluar": la firma del acta (la hace el líder) y la
# reapertura (la hace el Coordinador).
ACCIONES_QUE_NO_SON_EVALUACION = ("firmar-acta", "reabrir-dictamen")


def aplica_a(usuario: dict | None) -> bool:
    """La regla solo restringe al rol Comité."""
    return _normalize_role_name((usuario or {}).get("role_name")) == "comite"


def id_de(usuario: dict | None) -> str:
    return str((usuario or {}).get("id_usuario") or (usuario or {}).get("id") or "")


def sql_impedimento(columna_solicitud: str, parametro_usuario: str = "imp_usuario") -> str:
    """
    Expresión SQL con el motivo ('apelacion' o 'solicitud') por el que el
    usuario `:parametro_usuario` no puede evaluar la solicitud de
    `columna_solicitud`, o NULL si puede.
    """
    u = f":{parametro_usuario}"
    s = columna_solicitud
    no_evaluacion = ", ".join(f"'{a}'" for a in ACCIONES_QUE_NO_SON_EVALUACION)
    return f"""CASE
            WHEN EXISTS (
                SELECT 1 FROM apelacion ap
                WHERE ap.id_solicitud = {s}
                  AND (
                      ap.id_usuario_revisa::TEXT = {u}
                      OR ap.id_auditor_evaluador::TEXT = {u}
                      OR EXISTS (SELECT 1 FROM apelacion_comite ac
                                 WHERE ac.id_apelacion = ap.id AND ac.id_usuario::TEXT = {u})
                      OR EXISTS (SELECT 1 FROM requerimiento_apelacion ra
                                 WHERE ra.id_apelacion = ap.id AND ra.id_usuario_solicita::TEXT = {u})
                  )
            ) THEN '{MOTIVO_APELACION}'
            WHEN EXISTS (
                SELECT 1 FROM comite_accion ca
                WHERE ca.id_solicitud = {s}
                  AND ca.id_usuario = {u}
                  AND ca.accion NOT IN ({no_evaluacion})
                  AND ca.fecha < (SELECT MAX(r.fecha) FROM comite_accion r
                                  WHERE r.id_solicitud = {s} AND r.accion = 'reabrir-dictamen')
            ) THEN '{MOTIVO_SOLICITUD}'
        END"""


async def motivo_impedimento(db: AsyncSession, id_solicitud, usuario: dict | None) -> str | None:
    """Motivo por el que este miembro del Comité no puede evaluar, o None."""
    if not aplica_a(usuario):
        return None
    resultado = await db.execute(
        text(f"SELECT {sql_impedimento('CAST(:imp_solicitud AS UUID)')} AS impedimento;"),
        {"imp_solicitud": str(id_solicitud), "imp_usuario": id_de(usuario)},
    )
    fila = resultado.mappings().first()
    motivo = fila.get("impedimento") if fila else None
    return motivo if motivo in MENSAJES else None


async def exigir_imparcialidad(db: AsyncSession, id_solicitud: UUID | str, usuario: dict | None) -> None:
    """403 si el miembro del Comité ya participó en la solicitud o su apelación."""
    motivo = await motivo_impedimento(db, id_solicitud, usuario)
    if motivo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJES[motivo])
