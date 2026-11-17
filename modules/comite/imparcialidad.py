"""
Imparcialidad del Comité de certificación (17/11/2026).

Decisión de la usuaria: "Solo se debe impedir a quien participó en la
evaluación de la solicitud, aceptación o rechazo de la misma, así como
también el que apruebe o rechace la apelación." y "No puede aparecerle
dicha decisión, expediente o solicitud si está impedido de ella."

Un miembro del Comité está IMPEDIDO para una solicitud si:

  (a) registró una DECISIÓN de aceptación o rechazo de esa solicitud en una
      ronda ANTERIOR: una fila de `comite_accion` suya con `accion` en
      ACCIONES_DE_DECISION ('aprobar', 'rechazar', 'decisiones',
      'decision-definitiva') y fecha anterior a la última 'reabrir-dictamen'
      de la solicitud. Una ronda termina cuando el Coordinador reabre el
      dictamen; dentro de la ronda vigente quien decidió sigue con su
      expediente. Borradores ('decision-borrador'), debate
      ('comentarios-debate'), observaciones al acta, restricciones de
      alcance, solicitudes de información, generar/firmar el acta y cerrar
      el expediente NO impiden.
      (En la base del 17/11/2026 solo existen 'aprobar', 'rechazar' y
      'cerrar-expediente'; 'decisiones' y 'decision-definitiva' son las
      otras rutas que fijan la decisión, COM-011 y COM-018.)
  (b) aprobó o rechazó una apelación de esa solicitud:
      `apelacion.id_usuario_revisa` es él y la apelación está decidida
      (estado APROBADA, RECHAZADA, NOTIFICADA o CERRADA). Pedir información
      (INFORMACION_SOLICITADA también llena id_usuario_revisa) no impide.
      Estar asignado al comité de la apelación (`apelacion_comite`), ser su
      auditor evaluador o haber pedido documentos ya NO impiden.

Al impedido no le aparece el expediente en ningún listado (se filtra en SQL)
y cualquier lectura o acción responde 404, como si no existiera.

Excepciones:
  · El Coordinador (y el Auxiliar) no están sujetos: solo aplica al rol Comité.
  · El líder del comité del expediente (modules/comite/lider_expediente.py)
    puede siempre ver el estado del acta, generarla, firmarla, descargarla y
    firmar el certificado de ESE expediente (`permitir_lider=True`).
  · En la apelación que el miembro decidió, sigue entrando a ESA apelación
    (para notificarla o cerrarla); las demás apelaciones de la solicitud no
    le aparecen (`columna_apelacion_propia`).
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name

MOTIVO_SOLICITUD = "solicitud"
MOTIVO_APELACION = "apelacion"

MENSAJES = {
    MOTIVO_SOLICITUD: "No puede evaluarlo: ya registró la decisión de esta solicitud en una evaluación anterior.",
    MOTIVO_APELACION: "No puede evaluarlo: ya aprobó o rechazó la apelación de esta solicitud.",
}

MENSAJE_NO_ENCONTRADO = "El expediente no existe o fue eliminado."

# Acciones de comite_accion que fijan la aceptación o el rechazo.
ACCIONES_DE_DECISION = ("aprobar", "rechazar", "decisiones", "decision-definitiva")
# Estados de una apelación ya decidida (aprobada o rechazada y lo que sigue).
ESTADOS_APELACION_DECIDIDA = ("APROBADA", "RECHAZADA", "NOTIFICADA", "CERRADA")


def aplica_a(usuario: dict | None) -> bool:
    """La regla solo restringe al rol Comité."""
    return _normalize_role_name((usuario or {}).get("role_name")) == "comite"


def id_de(usuario: dict | None) -> str:
    return str((usuario or {}).get("id_usuario") or (usuario or {}).get("id") or "")


def sql_impedimento(
    columna_solicitud: str,
    parametro_usuario: str = "imp_usuario",
    columna_apelacion_propia: str | None = None,
) -> str:
    """
    Expresión SQL con el motivo ('apelacion' o 'solicitud') por el que el
    usuario `:parametro_usuario` está impedido para la solicitud de
    `columna_solicitud`, o NULL si no lo está.

    `columna_apelacion_propia`: al listar apelaciones, la apelación de la
    fila no impide a quien la decidió (sí las demás de la misma solicitud).
    """
    u = f":{parametro_usuario}"
    s = columna_solicitud
    decisiones = ", ".join(f"'{a}'" for a in ACCIONES_DE_DECISION)
    decididas = ", ".join(f"'{e}'" for e in ESTADOS_APELACION_DECIDIDA)
    otra_apelacion = f" AND ap.id <> {columna_apelacion_propia}" if columna_apelacion_propia else ""
    return f"""CASE
            WHEN EXISTS (
                SELECT 1 FROM apelacion ap
                WHERE ap.id_solicitud = {s}
                  AND ap.id_usuario_revisa::TEXT = {u}
                  AND UPPER(TRIM(COALESCE(ap.estado, ''))) IN ({decididas}){otra_apelacion}
            ) THEN '{MOTIVO_APELACION}'
            WHEN EXISTS (
                SELECT 1 FROM comite_accion ca
                WHERE ca.id_solicitud = {s}
                  AND ca.id_usuario = {u}
                  AND ca.accion IN ({decisiones})
                  AND ca.fecha < (SELECT MAX(r.fecha) FROM comite_accion r
                                  WHERE r.id_solicitud = {s} AND r.accion = 'reabrir-dictamen')
            ) THEN '{MOTIVO_SOLICITUD}'
        END"""


def filtro_visible(
    usuario: dict | None,
    columna_solicitud: str,
    params: dict,
    columna_apelacion_propia: str | None = None,
    permitir_lider: bool = False,
) -> str:
    """
    Condición SQL (" AND ...") que oculta al miembro del Comité lo que tiene
    impedido; "" para los demás roles. Agrega el parámetro a `params`.
    Con `permitir_lider` el líder del expediente lo sigue viendo.
    """
    if not aplica_a(usuario):
        return ""
    params["imp_usuario"] = id_de(usuario)
    condicion = f"({sql_impedimento(columna_solicitud, 'imp_usuario', columna_apelacion_propia)}) IS NULL"
    if permitir_lider:
        from modules.comite.lider_expediente import sql_id_lider_expediente

        condicion = f"({condicion} OR {sql_id_lider_expediente(columna_solicitud)} = :imp_usuario)"
    return f"\n          AND {condicion}"


async def motivo_impedimento(db: AsyncSession, id_solicitud, usuario: dict | None) -> str | None:
    """Motivo por el que este miembro del Comité está impedido, o None."""
    if not aplica_a(usuario):
        return None
    resultado = await db.execute(
        text(f"SELECT {sql_impedimento('CAST(:imp_solicitud AS UUID)')} AS impedimento;"),
        {"imp_solicitud": str(id_solicitud), "imp_usuario": id_de(usuario)},
    )
    fila = resultado.mappings().first()
    motivo = fila.get("impedimento") if fila else None
    return motivo if motivo in MENSAJES else None


async def exigir_imparcialidad(
    db: AsyncSession,
    id_solicitud: UUID | str,
    usuario: dict | None,
    permitir_lider: bool = False,
) -> None:
    """
    404 si el miembro del Comité está impedido (no se revela que existe).
    Con `permitir_lider`, el líder del comité de ese expediente pasa (firmas).
    """
    motivo = await motivo_impedimento(db, id_solicitud, usuario)
    if not motivo:
        return
    if permitir_lider:
        from modules.comite.lider_expediente import es_lider_del_expediente

        if await es_lider_del_expediente(db, id_solicitud, usuario):
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MENSAJE_NO_ENCONTRADO)
