"""
M5 — GESTIÓN DE SOLICITUDES
Bitácora inmutable de la solicitud (SOL-055).

Cada acción con efecto sobre una solicitud deja aquí una línea con el código
de permiso que la autorizó, quién la hizo y con qué datos. La tabla solo
recibe INSERT: ni la aplicación ni los servicios la actualizan o la borran,
de modo que el rastro sirva como evidencia.

Se usa desde los Bloques 5, 6 y 7; los bloques 1 a 4 siguen escribiendo
además en `historial_estado`, que es lo que ve la empresa.
"""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def registrar(
    db: AsyncSession,
    id_solicitud: UUID | str,
    accion: str,
    usuario: dict,
    detalle: dict | None = None,
    codigo: str | None = None,
) -> None:
    """Añade una línea a la bitácora. No hace commit: lo hace quien llama."""
    await db.execute(
        text("""
            INSERT INTO bitacora_solicitud (
                id_solicitud, permiso_codigo, accion, detalle, id_usuario, rol_usuario
            )
            VALUES (
                :id_solicitud, :codigo, :accion,
                CAST(CAST(:detalle AS TEXT) AS JSONB),
                :id_usuario, :rol
            );
        """),
        {
            "id_solicitud": str(id_solicitud),
            "codigo": codigo or usuario.get("permiso_codigo") or "M5",
            "accion": accion,
            "detalle": json.dumps(detalle or {}, ensure_ascii=False, default=str),
            "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            "rol": usuario.get("role_name"),
        },
    )


async def leer(db: AsyncSession, id_solicitud: UUID | str) -> list[dict]:
    """La bitácora de una solicitud, de la línea más antigua a la más nueva."""
    resultado = await db.execute(
        text("""
            SELECT b.id_bitacora, b.permiso_codigo, b.accion, b.detalle,
                   b.id_usuario, b.rol_usuario, b.fecha,
                   COALESCE(u.nombre, u.correo) AS usuario
            FROM bitacora_solicitud b
            LEFT JOIN usuario u ON u.id_usuario = b.id_usuario
            WHERE b.id_solicitud = :id_solicitud
            ORDER BY b.id_bitacora;
        """),
        {"id_solicitud": str(id_solicitud)},
    )
    return [dict(fila) for fila in resultado.mappings().all()]
