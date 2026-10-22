"""
M7 — AUDITORÍAS
Seguimiento y cierre (AUT-051 a AUT-060).

Después del informe queda lo que la empresa tiene que corregir: las acciones
de seguimiento y las acciones correctivas de cada no conformidad, que viven
en `seguimiento_auditoria`.

Una auditoría se cierra cuando no quedan no conformidades abiertas, y solo se
reabre con una justificación escrita, que queda en el propio registro.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.auditorias.auditoria_service import (
    ESTADO_CERRADA,
    ESTADO_REABIERTA,
    AuditoriaService,
)
from modules.auditorias.hallazgo_service import ESTADO_CERRADO, TIPO_NO_CONFORMIDAD

TIPO_SEGUIMIENTO = "Seguimiento"
TIPO_CORRECTIVA = "Accion correctiva"
TIPOS = (TIPO_SEGUIMIENTO, TIPO_CORRECTIVA)

ESTADO_ABIERTA = "Abierta"
ESTADO_EN_PROCESO = "En proceso"
ESTADO_COMPLETADA = "Completada"
ESTADOS = (ESTADO_ABIERTA, ESTADO_EN_PROCESO, ESTADO_COMPLETADA)

COLUMNAS = """
    id_seguimiento, id_auditoria, id_hallazgo, descripcion,
    fecha, usuario, estado, observaciones
"""


class SeguimientoService:
    """Acciones de seguimiento, acciones correctivas y cierre de la auditoría."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.auditorias = AuditoriaService(db)

    async def _registro(self, id_auditoria: UUID, id_seguimiento: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS} FROM seguimiento_auditoria
                WHERE id_seguimiento = :id AND id_auditoria = :id_auditoria;
            """),
            {"id": str(id_seguimiento), "id_auditoria": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El registro de seguimiento no existe para esta auditoría.",
            )
        return dict(fila)

    # ========================================================
    # AUT-051 / AUT-052 · HISTORIAL DE AUDITORÍAS
    # ========================================================

    async def historial_de_auditorias(
        self, id_empresa: UUID | None = None, id_solicitud: UUID | None = None
    ) -> list[dict]:
        """AUT-051: las auditorías hechas, con su resultado resumido."""
        resultado = await self.db.execute(
            text("""
                SELECT a.id_auditoria, a.estado, a.fecha_inicio, a.fecha_fin,
                       a.fecha_cierre, a.bloqueada,
                       s.numero_radicado, e.nombre AS empresa, n.codigo AS norma,
                       (SELECT COUNT(*) FROM hallazgo h
                         WHERE h.id_auditoria = a.id_auditoria) AS hallazgos,
                       (SELECT COUNT(*) FROM hallazgo h
                         WHERE h.id_auditoria = a.id_auditoria
                           AND h.tipo = 'NO_CONFORMIDAD') AS no_conformidades,
                       (SELECT i.estado FROM informe_auditoria i
                         WHERE i.id_auditoria = a.id_auditoria
                         ORDER BY i.version DESC LIMIT 1) AS estado_informe
                FROM auditoria a
                LEFT JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE (CAST(:id_empresa AS UUID) IS NULL
                       OR s.id_empresa = CAST(:id_empresa AS UUID))
                  AND (CAST(:id_solicitud AS UUID) IS NULL
                       OR a.id_solicitud = CAST(:id_solicitud AS UUID))
                ORDER BY a.fecha_creacion DESC;
            """),
            {
                "id_empresa": str(id_empresa) if id_empresa else None,
                "id_solicitud": str(id_solicitud) if id_solicitud else None,
            },
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def historial_inmutable(self, id_auditoria: UUID) -> dict:
        """
        AUT-052: lo que quedó registrado y ya no cambia — las versiones del
        informe, los cambios de cada hallazgo y el rastro de las evidencias.
        """
        await self.auditorias.obtener(id_auditoria)

        informe = await self.db.execute(
            text("""
                SELECT h.version, h.estado, h.observacion_cambio, h.fecha,
                       COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_informe_auditoria h
                JOIN informe_auditoria i ON i.id_informe = h.id_informe
                LEFT JOIN usuario u ON u.id_usuario = h.id_usuario
                WHERE i.id_auditoria = :id ORDER BY h.fecha;
            """),
            {"id": str(id_auditoria)},
        )
        hallazgos = await self.db.execute(
            text("""
                SELECT hh.accion, hh.estado_anterior, hh.estado_nuevo,
                       hh.clasificacion_anterior, hh.clasificacion_nueva,
                       hh.fecha, h.titulo,
                       COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_hallazgo hh
                JOIN hallazgo h ON h.id_hallazgo = hh.id_hallazgo
                LEFT JOIN usuario u ON u.id_usuario = hh.id_usuario
                WHERE h.id_auditoria = :id ORDER BY hh.fecha;
            """),
            {"id": str(id_auditoria)},
        )
        evidencias = await self.db.execute(
            text("""
                SELECT he.accion, he.version, he.observacion, he.fecha,
                       e.nombre_archivo, COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_evidencia he
                JOIN evidencia e ON e.id_evidencia = he.id_evidencia
                LEFT JOIN usuario u ON u.id_usuario = he.id_usuario
                WHERE e.id_auditoria = :id ORDER BY he.fecha;
            """),
            {"id": str(id_auditoria)},
        )

        return {
            "informe": [dict(f) for f in informe.mappings().all()],
            "hallazgos": [dict(f) for f in hallazgos.mappings().all()],
            "evidencias": [dict(f) for f in evidencias.mappings().all()],
        }

    # ========================================================
    # AUT-053 a AUT-056 · ACCIONES
    # ========================================================

    async def registrar_accion(
        self,
        id_auditoria: UUID,
        descripcion: str,
        usuario: dict,
        tipo: str = TIPO_SEGUIMIENTO,
        id_hallazgo: UUID | None = None,
        observaciones: str | None = None,
    ) -> dict:
        """AUT-053 (seguimiento) y AUT-055 (acción correctiva)."""
        await self.auditorias.obtener(id_auditoria)
        if tipo not in TIPOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo no válido. Se aceptan: {', '.join(TIPOS)}.",
            )
        if tipo == TIPO_CORRECTIVA and id_hallazgo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Una acción correctiva siempre responde a un hallazgo.",
            )

        if id_hallazgo is not None:
            existe = await self.db.execute(
                text("SELECT 1 FROM hallazgo WHERE id_hallazgo = :id AND id_auditoria = :auditoria;"),
                {"id": str(id_hallazgo), "auditoria": str(id_auditoria)},
            )
            if existe.scalar() is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El hallazgo no existe para esta auditoría.",
                )

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO seguimiento_auditoria (
                    id_auditoria, id_hallazgo, descripcion, fecha,
                    usuario, estado, observaciones
                )
                VALUES (
                    :id_auditoria, :id_hallazgo, :descripcion, CURRENT_TIMESTAMP,
                    :usuario, :estado, :observaciones
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_auditoria": str(id_auditoria),
                "id_hallazgo": str(id_hallazgo) if id_hallazgo else None,
                "descripcion": f"[{tipo}] {descripcion}",
                "usuario": str(usuario["id_usuario"]),
                "estado": ESTADO_ABIERTA,
                "observaciones": observaciones,
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def listar_acciones(
        self, id_auditoria: UUID, id_hallazgo: UUID | None = None
    ) -> list[dict]:
        """AUT-054 y AUT-056."""
        await self.auditorias.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT s.id_seguimiento, s.id_hallazgo, s.descripcion, s.fecha,
                       s.estado, s.observaciones, h.titulo AS hallazgo,
                       h.tipo AS tipo_hallazgo, h.clasificacion,
                       COALESCE(u.nombre, u.correo) AS registrado_por
                FROM seguimiento_auditoria s
                LEFT JOIN hallazgo h ON h.id_hallazgo = s.id_hallazgo
                LEFT JOIN usuario u ON u.id_usuario = CAST(NULLIF(s.usuario, '') AS UUID)
                WHERE s.id_auditoria = :id_auditoria
                  AND (CAST(:id_hallazgo AS UUID) IS NULL
                       OR s.id_hallazgo = CAST(:id_hallazgo AS UUID))
                ORDER BY s.fecha;
            """),
            {
                "id_auditoria": str(id_auditoria),
                "id_hallazgo": str(id_hallazgo) if id_hallazgo else None,
            },
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def actualizar_accion(
        self, id_auditoria: UUID, id_seguimiento: UUID, estado: str, observaciones: str | None,
        usuario: dict,
    ) -> dict:
        await self._registro(id_auditoria, id_seguimiento)
        if estado not in ESTADOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estado no válido. Se aceptan: {', '.join(ESTADOS)}.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE seguimiento_auditoria
                SET estado = :estado,
                    observaciones = COALESCE(:observaciones, observaciones)
                WHERE id_seguimiento = :id
                RETURNING {COLUMNAS};
            """),
            {"estado": estado, "observaciones": observaciones, "id": str(id_seguimiento)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-057 / AUT-058 · CERRAR Y REABRIR
    # ========================================================

    async def cerrar(self, id_auditoria: UUID, observaciones: str, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        if auditoria["estado"] == ESTADO_CERRADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La auditoría ya estaba cerrada.",
            )

        abiertas = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM hallazgo
                WHERE id_auditoria = :id AND tipo = :tipo AND estado <> :cerrado;
            """),
            {"id": str(id_auditoria), "tipo": TIPO_NO_CONFORMIDAD, "cerrado": ESTADO_CERRADO},
        )
        pendientes = abiertas.scalar() or 0
        if pendientes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Quedan {pendientes} no conformidades sin cerrar.",
            )

        resultado = await self.db.execute(
            text("""
                UPDATE auditoria
                SET estado = :estado,
                    observaciones_cierre = :observaciones,
                    fecha_fin = COALESCE(fecha_fin, CURRENT_DATE),
                    fecha_cierre = CURRENT_TIMESTAMP
                WHERE id_auditoria = :id
                RETURNING id_auditoria, estado, fecha_fin, fecha_cierre, observaciones_cierre;
            """),
            {"estado": ESTADO_CERRADA, "observaciones": observaciones, "id": str(id_auditoria)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def reabrir(self, id_auditoria: UUID, justificacion: str, usuario: dict) -> dict:
        auditoria = await self.auditorias.obtener(id_auditoria)
        if auditoria["estado"] != ESTADO_CERRADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se reabre una auditoría cerrada.",
            )

        resultado = await self.db.execute(
            text("""
                UPDATE auditoria
                SET estado = :estado,
                    bloqueada = FALSE,
                    fecha_cierre = NULL,
                    incidencias = COALESCE(incidencias || E'\\n', '') || :motivo
                WHERE id_auditoria = :id
                RETURNING id_auditoria, estado, bloqueada, incidencias;
            """),
            {
                "estado": ESTADO_REABIERTA,
                "motivo": f"[Reapertura] {justificacion}",
                "id": str(id_auditoria),
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def cerrar_hallazgo(
        self, id_auditoria: UUID, id_hallazgo: UUID, observacion: str, usuario: dict
    ) -> dict:
        """Cierra un hallazgo cuando su acción correctiva quedó verificada."""
        resultado = await self.db.execute(
            text("""
                UPDATE hallazgo
                SET estado = :estado, fecha_cierre = CURRENT_TIMESTAMP
                WHERE id_hallazgo = :id AND id_auditoria = :id_auditoria
                RETURNING id_hallazgo, titulo, tipo, clasificacion, estado, fecha_cierre;
            """),
            {"estado": ESTADO_CERRADO, "id": str(id_hallazgo), "id_auditoria": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El hallazgo no existe para esta auditoría.",
            )
        await self.db.execute(
            text("""
                INSERT INTO historial_hallazgo (
                    id_hallazgo, accion, estado_nuevo, observacion, id_usuario, fecha
                )
                VALUES (:id, 'Hallazgo cerrado', :estado, :observacion, :usuario, CURRENT_TIMESTAMP);
            """),
            {
                "id": str(id_hallazgo),
                "estado": ESTADO_CERRADO,
                "observacion": observacion,
                "usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )
        await self.db.commit()
        return dict(fila)

    # ========================================================
    # AUT-059 / AUT-060 · ESTADÍSTICAS
    # ========================================================

    async def estadisticas(self, id_empresa: UUID | None = None) -> dict:
        """AUT-059: los números de los hallazgos, para la pantalla y el informe."""
        por_tipo = await self.db.execute(
            text("""
                SELECT h.tipo, h.clasificacion, COUNT(*) AS total
                FROM hallazgo h
                JOIN auditoria a ON a.id_auditoria = h.id_auditoria
                JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                WHERE (CAST(:id_empresa AS UUID) IS NULL
                       OR s.id_empresa = CAST(:id_empresa AS UUID))
                GROUP BY h.tipo, h.clasificacion
                ORDER BY total DESC;
            """),
            {"id_empresa": str(id_empresa) if id_empresa else None},
        )
        por_auditoria = await self.db.execute(
            text("""
                SELECT a.id_auditoria, s.numero_radicado, e.nombre AS empresa,
                       a.estado, COUNT(h.id_hallazgo) AS hallazgos
                FROM auditoria a
                LEFT JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN hallazgo h ON h.id_auditoria = a.id_auditoria
                WHERE (CAST(:id_empresa AS UUID) IS NULL
                       OR s.id_empresa = CAST(:id_empresa AS UUID))
                GROUP BY a.id_auditoria, s.numero_radicado, e.nombre, a.estado
                ORDER BY hallazgos DESC;
            """),
            {"id_empresa": str(id_empresa) if id_empresa else None},
        )
        totales = await self.db.execute(
            text("""
                SELECT COUNT(*) AS auditorias,
                       COUNT(*) FILTER (WHERE estado = 'Cerrada') AS cerradas,
                       COUNT(*) FILTER (WHERE estado = 'Suspendida') AS suspendidas,
                       COUNT(*) FILTER (WHERE bloqueada) AS con_informe_final
                FROM auditoria;
            """)
        )
        return {
            "totales": dict(totales.mappings().first()),
            "por_tipo": [dict(f) for f in por_tipo.mappings().all()],
            "por_auditoria": [dict(f) for f in por_auditoria.mappings().all()],
        }
