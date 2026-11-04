"""
M5 — GESTIÓN DE SOLICITUDES
Bloque 6: trazabilidad, bitácora y cierre (SOL-051 a SOL-060).

Dos registros distintos conviven a propósito:

  · `historial_estado` es lo que ve la empresa: por qué estados pasó su
    solicitud. Lo escriben también los bloques 1 a 4.
  · `bitacora_solicitud` (SOL-055) es la evidencia interna: qué permiso se
    ejecutó, quién, cuándo y con qué datos. Solo recibe INSERT.

El cierre (SOL-060) es definitivo: a partir de ahí la solicitud queda
bloqueada para cambios, que es lo que comprueba SOL-070 del Bloque 7.
"""

import unicodedata
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes import bitacora
from modules.solicitudes import estado_solicitud as estados
from modules.solicitudes.solicitud_service import SolicitudService

# Estados que la administración puede fijar con SOL-054. Se incluyen los que
# escriben otros módulos (el Comité guarda 'APROBADO' / 'RECHAZADO') para que
# el historial pueda reflejar lo que de verdad hay en la base.
ESTADOS_ADMINISTRACION = tuple(e for e in estados.ESTADOS if e != estados.BORRADOR)

ESTADO_CERRADA = estados.CERRADA

TIPOS_OBSERVACION = ("Control", "Tecnica", "Administrativa")


def _normalizar(texto) -> str:
    """Sin tildes y en mayúsculas, para comparar estados escritos de varias formas."""
    sin_tilde = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in sin_tilde if unicodedata.category(c) != "Mn").upper().strip()


def esta_cerrada(estado) -> bool:
    return _normalizar(estado).startswith("CERRAD")


def esta_aprobada(estado) -> bool:
    return _normalizar(estado).startswith("APROBAD")


class TrazabilidadService:
    """Historial, observaciones, bitácora y cierre de la solicitud."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    async def _solicitud(self, id_solicitud: UUID, usuario: dict) -> dict:
        return await self.solicitudes.consultar(id_solicitud, usuario)

    # ========================================================
    # SOL-051 · HISTORIAL DE LA SOLICITUD
    # ========================================================

    async def historial(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        await self._solicitud(id_solicitud, usuario)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.estado, h.fecha, h.observacion,
                       COALESCE(u.nombre, u.correo) AS usuario
                FROM historial_estado h
                LEFT JOIN usuario u ON u.id_usuario = h.id_usuario_actor
                WHERE h.id_solicitud = :id_solicitud
                ORDER BY h.fecha, h.id_historial;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-052 / SOL-053 · OBSERVACIONES DE CONTROL
    # ========================================================

    async def registrar_observacion(
        self, id_solicitud: UUID, texto_observacion: str, tipo: str, usuario: dict
    ) -> dict:
        await self._solicitud(id_solicitud, usuario)
        if tipo not in TIPOS_OBSERVACION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de observación no válido. Se aceptan: {', '.join(TIPOS_OBSERVACION)}.",
            )

        resultado = await self.db.execute(
            text("""
                INSERT INTO observacion_solicitud (id_solicitud, texto, tipo, id_usuario)
                VALUES (:id_solicitud, :texto, :tipo, :id_usuario)
                RETURNING id_observacion, id_solicitud, texto, tipo, id_usuario, fecha;
            """),
            {
                "id_solicitud": str(id_solicitud),
                "texto": texto_observacion,
                "tipo": tipo,
                "id_usuario": str(usuario["id_usuario"]),
            },
        )
        observacion = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud, "Observación de control registrada", usuario,
            {"tipo": tipo, "texto": texto_observacion},
        )
        await self.db.commit()
        return observacion

    async def listar_observaciones(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        await self._solicitud(id_solicitud, usuario)
        resultado = await self.db.execute(
            text("""
                SELECT o.id_observacion, o.texto, o.tipo, o.fecha,
                       COALESCE(u.nombre, u.correo) AS usuario
                FROM observacion_solicitud o
                LEFT JOIN usuario u ON u.id_usuario = o.id_usuario
                WHERE o.id_solicitud = :id_solicitud
                ORDER BY o.fecha DESC;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-054 · CAMBIAR EL ESTADO
    # ========================================================

    async def exigir_no_cerrada(self, solicitud: dict) -> None:
        """SOL-070: una vez cerrada, la solicitud no admite más cambios."""
        if esta_cerrada(solicitud.get("estado")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La solicitud está cerrada definitivamente y no admite cambios.",
            )

    async def cambiar_estado(
        self, id_solicitud: UUID, nuevo_estado: str, motivo: str | None, usuario: dict
    ) -> dict:
        solicitud = await self._solicitud(id_solicitud, usuario)
        await self.exigir_no_cerrada(solicitud)

        if nuevo_estado not in ESTADOS_ADMINISTRACION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Estado no válido. Se aceptan: {', '.join(ESTADOS_ADMINISTRACION)}.",
            )
        if _normalizar(solicitud.get("estado")) == _normalizar(nuevo_estado):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La solicitud ya está en estado '{solicitud.get('estado')}'.",
            )

        anterior = solicitud.get("estado")
        resultado = await self.db.execute(
            text("""
                UPDATE solicitud
                SET estado = :estado
                WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL
                RETURNING id_solicitud, numero_radicado, estado, fecha_cierre;
            """),
            {"estado": nuevo_estado, "id_solicitud": str(id_solicitud)},
        )
        actualizada = dict(resultado.mappings().first())

        await self._historial(id_solicitud, nuevo_estado, usuario, motivo)
        await bitacora.registrar(
            self.db, id_solicitud, "Cambio de estado", usuario,
            {"anterior": anterior, "nuevo": nuevo_estado, "motivo": motivo},
        )
        await self.db.commit()
        return actualizada

    async def _historial(
        self, id_solicitud: UUID, estado: str, usuario: dict, detalle: str | None
    ) -> None:
        """Escribe en `historial_estado` dejando también quién lo hizo."""
        partes = [f"[{usuario.get('permiso_codigo', 'M5')}]"]
        if detalle:
            partes.append(detalle)
        await self.db.execute(
            text("""
                INSERT INTO historial_estado (
                    id_solicitud, estado, fecha, observacion, id_usuario_actor
                )
                VALUES (:id_solicitud, :estado, CURRENT_DATE, :observacion, :id_usuario);
            """),
            {
                "id_solicitud": str(id_solicitud),
                "estado": estado,
                "observacion": " ".join(partes),
                "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )

    # ========================================================
    # SOL-055 · BITÁCORA INMUTABLE
    # ========================================================

    async def leer_bitacora(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        await self._solicitud(id_solicitud, usuario)
        return await bitacora.leer(self.db, id_solicitud)

    # ========================================================
    # SOL-056 / SOL-059 · HISTORIAL Y REPORTE DEL MÓDULO
    # ========================================================

    async def historial_general(
        self, usuario: dict, estado: str | None = None, id_empresa: UUID | None = None
    ) -> list[dict]:
        """Las solicitudes con su último movimiento, para exportar (SOL-056)."""
        resultado = await self.db.execute(
            text("""
                SELECT s.id_solicitud, s.numero_radicado, s.estado,
                       e.nombre AS empresa, e.nit,
                       n.codigo AS norma, s.fecha_creacion, s.fecha_radicacion,
                       s.fecha_cierre,
                       (SELECT MAX(h.fecha) FROM historial_estado h
                         WHERE h.id_solicitud = s.id_solicitud) AS ultimo_movimiento,
                       (SELECT COUNT(*) FROM observacion_solicitud o
                         WHERE o.id_solicitud = s.id_solicitud) AS observaciones
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.deleted_at IS NULL
                  AND (CAST(:estado AS VARCHAR) IS NULL OR s.estado = CAST(:estado AS VARCHAR))
                  AND (CAST(:id_empresa AS UUID) IS NULL OR s.id_empresa = CAST(:id_empresa AS UUID))
                ORDER BY s.fecha_creacion DESC;
            """),
            {"estado": estado, "id_empresa": str(id_empresa) if id_empresa else None},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def reporte(self, usuario: dict) -> dict:
        """SOL-059: los números del módulo, para la pantalla y para el informe."""
        por_estado = await self.db.execute(
            text("""
                SELECT estado, COUNT(*) AS total
                FROM solicitud WHERE deleted_at IS NULL
                GROUP BY estado ORDER BY total DESC;
            """)
        )
        por_norma = await self.db.execute(
            text("""
                SELECT COALESCE(n.codigo, 'Sin norma') AS norma, COUNT(*) AS total
                FROM solicitud s
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.deleted_at IS NULL
                GROUP BY n.codigo ORDER BY total DESC;
            """)
        )
        totales = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS solicitudes,
                    COUNT(*) FILTER (WHERE fecha_radicacion IS NOT NULL) AS radicadas,
                    COUNT(*) FILTER (WHERE fecha_cierre IS NOT NULL) AS cerradas,
                    COUNT(*) FILTER (WHERE fecha_envio_comite IS NOT NULL) AS enviadas_al_comite
                FROM solicitud WHERE deleted_at IS NULL;
            """)
        )
        return {
            "totales": dict(totales.mappings().first()),
            "por_estado": [dict(f) for f in por_estado.mappings().all()],
            "por_norma": [dict(f) for f in por_norma.mappings().all()],
        }

    # ========================================================
    # SOL-058 · COMPARTIR EL EXPEDIENTE CON EL COMITÉ
    # ========================================================

    async def compartir_con_comite(self, id_solicitud: UUID, usuario: dict) -> dict:
        solicitud = await self._solicitud(id_solicitud, usuario)
        await self.exigir_no_cerrada(solicitud)

        faltantes = []
        documentos = await self.db.execute(
            text("""
                SELECT COUNT(*) FILTER (WHERE estado = 'Aprobado') AS aprobados,
                       COUNT(*) AS total
                FROM documento_solicitud WHERE id_solicitud = :id_solicitud;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        conteo = documentos.mappings().first()
        if not solicitud.get("fecha_radicacion"):
            faltantes.append("La solicitud todavía no está radicada.")
        if (conteo["total"] or 0) == 0:
            faltantes.append("No hay documentos adjuntos.")

        if faltantes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede compartir con el Comité: " + " ".join(faltantes),
            )

        resultado = await self.db.execute(
            text("""
                UPDATE solicitud
                SET fecha_envio_comite = CURRENT_TIMESTAMP
                WHERE id_solicitud = :id_solicitud
                RETURNING id_solicitud, numero_radicado, estado, fecha_envio_comite;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        enviada = dict(resultado.mappings().first())

        await bitacora.registrar(
            self.db, id_solicitud, "Expediente compartido con el Comité", usuario,
            {"documentos": conteo["total"], "aprobados": conteo["aprobados"]},
        )
        await self.db.commit()
        return enviada

    # ========================================================
    # SOL-060 · CERRAR LA SOLICITUD
    # ========================================================

    async def cerrar(self, id_solicitud: UUID, motivo: str, usuario: dict) -> dict:
        solicitud = await self._solicitud(id_solicitud, usuario)
        await self.exigir_no_cerrada(solicitud)

        resultado = await self.db.execute(
            text("""
                UPDATE solicitud
                SET estado = :estado,
                    fecha_cierre = CURRENT_TIMESTAMP
                WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL
                RETURNING id_solicitud, numero_radicado, estado, fecha_cierre;
            """),
            {"estado": ESTADO_CERRADA, "id_solicitud": str(id_solicitud)},
        )
        cerrada = dict(resultado.mappings().first())

        await self._historial(id_solicitud, ESTADO_CERRADA, usuario, motivo)
        await bitacora.registrar(
            self.db, id_solicitud, "Solicitud cerrada definitivamente", usuario,
            {"estado_anterior": solicitud.get("estado"), "motivo": motivo},
        )
        await self.db.commit()
        return cerrada
