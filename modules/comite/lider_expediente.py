"""
Líder del Comité por expediente.

Cada solicitud que evalúa el Comité es "un comité": el Coordinador elige su
líder entre los miembros del Comité que PARTICIPARON en la evaluación de ese
expediente en la ronda vigente. Ese líder firma el acta y el certificado de
ese expediente (y nadie más). Puede ser distinto en cada expediente.

"Participar" = haber registrado en `comite_accion` de esa solicitud, después
de la última reapertura del dictamen ('reabrir-dictamen'), alguna de las
acciones de evaluación de `ACCIONES_DE_PARTICIPACION` (decisión, borrador,
debate, observaciones al acta, restricciones de alcance o solicitud de
información). Generar o firmar el acta, cerrar el expediente o reabrirlo no
cuentan: no son evaluar. Además debe seguir siendo un usuario activo con rol
Comité.

Dónde se guarda: `asignacion_lider_comite` con la columna `id_solicitud`
(documentacion/sql_lider_por_expediente.sql). La fila con id_solicitud NULL
es el líder global de antes. Mientras la columna no exista el sistema sigue
con el líder global (compatibilidad) y al Coordinador se le avisa "Falta
aplicar el SQL de líder por expediente".

Para no depender de si la columna existe, las consultas leen la columna con
`to_jsonb(a)->>'id_solicitud'` (NULL si no existe) y el modo se detecta en
el mismo SQL con information_schema.
"""

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MENSAJE_FALTA_SQL = "Falta aplicar el SQL de líder por expediente"

# Acciones de comite_accion que cuentan como participar en la evaluación.
ACCIONES_DE_PARTICIPACION = (
    "aprobar",
    "rechazar",
    "decisiones",
    "decision-definitiva",
    "decision-borrador",
    "comentarios-debate",
    "observaciones-acta",
    "restricciones-alcance",
    "solicitar-info-adicional",
)

SQL_MODO_POR_EXPEDIENTE = """EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'asignacion_lider_comite'
      AND column_name = 'id_solicitud'
)"""

SQL_ROL_COMITE = (
    "LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou')) IN ('comite', 'comite de certificacion')"
)


def sql_solicitud_de(alias: str = "a") -> str:
    """id_solicitud de la asignación como texto (NULL si es la global o si la columna no existe)."""
    return f"(to_jsonb({alias})->>'id_solicitud')"


def sql_es_global(alias: str = "a") -> str:
    return f"{sql_solicitud_de(alias)} IS NULL"


def sql_asignacion_del_expediente(columna_solicitud: str, alias: str = "a") -> str:
    """
    Condición: la asignación `alias` es la que firma el expediente: la suya
    (modo por expediente) o la global (si la columna aún no existe).
    """
    return (
        f"({sql_solicitud_de(alias)} = CAST({columna_solicitud} AS TEXT)"
        f" OR (NOT {SQL_MODO_POR_EXPEDIENTE} AND {sql_es_global(alias)}))"
    )


def sql_id_lider_expediente(columna_solicitud: str) -> str:
    """Subconsulta con el id_usuario (texto) del líder vigente del expediente, o NULL."""
    return f"""(
        SELECT la.id_usuario::TEXT
        FROM asignacion_lider_comite la
        JOIN usuario lu ON lu.id_usuario = la.id_usuario
        JOIN rol r ON r.id_rol = lu.rol_id
        WHERE la.fecha_fin IS NULL
          AND lu.estado = 'Activo'
          AND {SQL_ROL_COMITE}
          AND {sql_asignacion_del_expediente(columna_solicitud, 'la')}
        ORDER BY la.fecha_inicio DESC
        LIMIT 1
    )"""


def sql_lateral_lider(columna_solicitud: str) -> str:
    """Subconsulta para LEFT JOIN LATERAL: lider_id, lider_nombre, lider_por_expediente."""
    return f"""(
        SELECT la.id_usuario AS lider_id, lu.nombre AS lider_nombre,
               {sql_solicitud_de('la')} IS NOT NULL AS lider_por_expediente
        FROM asignacion_lider_comite la
        JOIN usuario lu ON lu.id_usuario = la.id_usuario
        JOIN rol r ON r.id_rol = lu.rol_id
        WHERE la.fecha_fin IS NULL
          AND lu.estado = 'Activo'
          AND {SQL_ROL_COMITE}
          AND {sql_asignacion_del_expediente(columna_solicitud, 'la')}
        ORDER BY la.fecha_inicio DESC
        LIMIT 1
    )"""


def sql_participacion(columna_solicitud: str, columna_usuario: str) -> str:
    """EXISTS: el usuario registró una acción de evaluación en la ronda vigente."""
    acciones = ", ".join(f"'{a}'" for a in ACCIONES_DE_PARTICIPACION)
    return f"""EXISTS (
        SELECT 1 FROM comite_accion pa
        WHERE pa.id_solicitud = {columna_solicitud}
          AND pa.id_usuario = CAST({columna_usuario} AS TEXT)
          AND pa.accion IN ({acciones})
          AND pa.fecha > COALESCE(
              (SELECT MAX(pr.fecha) FROM comite_accion pr
               WHERE pr.id_solicitud = {columna_solicitud} AND pr.accion = 'reabrir-dictamen'),
              '-infinity'::timestamptz)
    )"""


async def modo_por_expediente(db: AsyncSession) -> bool:
    """True si ya se aplicó el SQL (existe asignacion_lider_comite.id_solicitud)."""
    resultado = await db.execute(text(f"SELECT {SQL_MODO_POR_EXPEDIENTE} AS disponible;"))
    fila = resultado.mappings().first()
    return bool(fila and fila.get("disponible"))


async def lider_de_expediente(db: AsyncSession, id_solicitud, bloquear: bool = False) -> dict | None:
    """
    Líder vigente que firma el expediente: el asignado a esa solicitud o,
    sin el SQL aplicado, el líder global. None si no hay.
    """
    resultado = await db.execute(text(f"""
        SELECT a.id_asignacion, a.id_usuario, a.fecha_inicio, u.nombre, u.correo,
               {sql_solicitud_de('a')} IS NOT NULL AS por_expediente
        FROM asignacion_lider_comite a
        JOIN usuario u ON u.id_usuario = a.id_usuario
        JOIN rol r ON r.id_rol = u.rol_id
        WHERE a.fecha_fin IS NULL
          AND u.estado = 'Activo'
          AND {SQL_ROL_COMITE}
          AND {sql_asignacion_del_expediente(':lider_solicitud', 'a')}
        ORDER BY a.fecha_inicio DESC
        LIMIT 1{' FOR UPDATE OF a' if bloquear else ''};
    """), {"lider_solicitud": str(id_solicitud)})
    fila = resultado.mappings().first()
    return dict(fila) if fila else None


async def es_lider_del_expediente(db: AsyncSession, id_solicitud, usuario: dict | None) -> bool:
    id_usuario = str((usuario or {}).get("id_usuario") or (usuario or {}).get("id") or "")
    if not id_usuario:
        return False
    lider = await lider_de_expediente(db, id_solicitud)
    return bool(lider) and str(lider["id_usuario"]) == id_usuario


async def participantes(db: AsyncSession, id_solicitud) -> list[dict]:
    """Miembros activos del Comité que participaron en la ronda vigente del expediente."""
    resultado = await db.execute(text(f"""
        SELECT u.id_usuario, u.nombre, u.correo
        FROM usuario u
        JOIN rol r ON r.id_rol = u.rol_id
        WHERE u.estado = 'Activo'
          AND {SQL_ROL_COMITE}
          AND {sql_participacion('CAST(:id_solicitud AS UUID)', 'u.id_usuario')}
        ORDER BY u.nombre;
    """), {"id_solicitud": str(id_solicitud)})
    return [dict(fila) for fila in resultado.mappings().all()]


async def consultar(db: AsyncSession, id_solicitud) -> dict:
    """Lo que necesita la pantalla del Coordinador: modo, líder actual y candidatos."""
    disponible = await modo_por_expediente(db)
    lider = await lider_de_expediente(db, id_solicitud)
    candidatos = await participantes(db, id_solicitud) if disponible else []
    return {
        "expediente_id": str(id_solicitud),
        "disponible": disponible,
        "aviso": None if disponible else MENSAJE_FALTA_SQL,
        "lider": lider if (lider and (lider.get("por_expediente") or not disponible)) else None,
        "candidatos": candidatos,
    }


async def asignar(db: AsyncSession, id_solicitud: UUID, id_usuario: UUID, actor: dict) -> dict:
    """El Coordinador elige el líder del expediente entre quienes participaron."""
    if not await modo_por_expediente(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MENSAJE_FALTA_SQL)
    await db.execute(text("SELECT pg_advisory_xact_lock(76139521, 11);"))
    solicitud = await db.execute(text("""
        SELECT id_solicitud FROM solicitud
        WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL;
    """), {"id_solicitud": str(id_solicitud)})
    if not solicitud.mappings().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")

    candidatos = await participantes(db, id_solicitud)
    elegido = next((c for c in candidatos if str(c["id_usuario"]) == str(id_usuario)), None)
    if not elegido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "El líder debe ser un miembro activo del Comité que haya participado "
                "en la evaluación de este expediente."
            ),
        )

    actual = await db.execute(text(f"""
        SELECT a.id_asignacion, a.id_usuario
        FROM asignacion_lider_comite a
        WHERE a.fecha_fin IS NULL AND {sql_solicitud_de('a')} = :id_solicitud
        FOR UPDATE;
    """), {"id_solicitud": str(id_solicitud)})
    anterior = actual.mappings().first()
    if anterior and str(anterior["id_usuario"]) == str(id_usuario):
        await db.commit()
        return {"mensaje": f"{elegido['nombre']} ya es el líder de este expediente.", "lider": elegido}
    if anterior:
        await db.execute(text("""
            UPDATE asignacion_lider_comite SET fecha_fin = CURRENT_TIMESTAMP
            WHERE id_asignacion = :id_asignacion;
        """), {"id_asignacion": str(anterior["id_asignacion"])})

    nueva = uuid4()
    # Esta sentencia solo funciona con el SQL aplicado (columna id_solicitud).
    await db.execute(text("""
        INSERT INTO asignacion_lider_comite (id_asignacion, id_usuario, asignado_por, fecha_inicio, id_solicitud)
        VALUES (:id_asignacion, :id_usuario, :asignado_por, CURRENT_TIMESTAMP, :id_solicitud);
    """), {
        "id_asignacion": str(nueva),
        "id_usuario": str(id_usuario),
        "asignado_por": str(actor.get("id_usuario") or "") or None,
        "id_solicitud": str(id_solicitud),
    })
    # Los certificados del expediente pendientes de firma pasan al nuevo líder.
    pendientes = await db.execute(text("""
        UPDATE certificado SET id_asignacion_lider = :id_asignacion
        WHERE id_solicitud = :id_solicitud
          AND TRIM(UPPER(estado_certificado)) = 'PENDIENTE_FIRMA'
        RETURNING id_certificado;
    """), {"id_asignacion": str(nueva), "id_solicitud": str(id_solicitud)})
    certificados = [str(f["id_certificado"]) for f in pendientes.mappings().all()]
    await db.commit()
    return {
        "mensaje": f"{elegido['nombre']} es ahora el líder del comité de este expediente.",
        "lider": {**elegido, "id_asignacion": str(nueva)},
        "certificados_reasignados": certificados,
    }


async def terminar_por_reapertura(db: AsyncSession, id_solicitud) -> None:
    """
    Al reabrir el dictamen empieza una ronda nueva: el líder del expediente
    se libera y el Coordinador elige de nuevo entre quienes participen ahora.
    Sin el SQL aplicado no hay filas por expediente y no cambia nada.
    """
    await db.execute(text(f"""
        UPDATE asignacion_lider_comite a SET fecha_fin = CURRENT_TIMESTAMP
        WHERE a.fecha_fin IS NULL AND {sql_solicitud_de('a')} = :id_solicitud;
    """), {"id_solicitud": str(id_solicitud)})
