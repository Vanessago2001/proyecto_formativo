"""
Finalizar la visita = evaluarla + adjuntar el Excel (pedido del 18/11/2026).

"Al querer finalizar la auditoría, en esa misma ventana debe aparecer el
resultado de la evaluación de la visita, junto con un campo para adjuntar el
documento Excel en donde se hizo toda la calificación de la misma, siendo
estos dos obligatorios para permitir finalizar la auditoría y así pasarla a
comité."

En UNA transacción:
  1. la visita (FOR UPDATE): existe (404), no está cancelada ni ya
     finalizada (409) y quien finaliza es un auditor asignado (403) →
     AgendaAuditorService.finalizar_programacion(confirmar=False);
  2. la calificación (1–100 %, al menos un comentario) y el Excel (.xlsx/.xls
     real, máx. 10 MB) son obligatorios (422);
  3. guarda o actualiza la calificación (calificacion_visita) — la visita
     debe haber empezado (409) y el Comité no debe haber decidido (409);
  4. guarda el Excel (evaluacion_excel.py, ruta derivada de la visita y el
     auditor);
  5. si era la última visita pendiente de la solicitud y el Comité aún no
     decidió, la solicitud pasa de 'Aprobada' (aprobada por el Coordinador
     para programar la auditoría) a 'En revision': así entra en la bandeja
     "Expedientes" del Comité (pendientes = Radicada o En revision);
  6. commit. Si algo falla: rollback y se borra del disco lo escrito.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.agenda_auditor.agenda_service import AgendaAuditorService
from modules.calificacion_visitas import evaluacion_excel
from modules.calificacion_visitas.calificacion_service import (
    SQL_COMITE_DECIDIO,
    CalificacionVisitaService,
    _es_tabla_inexistente,
    _falta_sql,
    _id_usuario,
    _rol,
    validar_calificacion,
)
from modules.solicitudes import bitacora
from modules.solicitudes import estado_solicitud as estados

MENSAJE_SOLO_AUDITOR = "Solo el auditor asignado a esta visita puede finalizarla."
ESTADOS_VISITA_CERRADA = ("CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO", "EJECUTADA", "EJECUTADO")


class FinalizacionVisitaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def finalizar(
        self,
        id_programacion: UUID,
        usuario: dict,
        observaciones: str | None,
        evaluacion: dict | None,
        archivo_nombre: str | None,
        archivo_contenido: bytes | None,
    ) -> dict:
        if _rol(usuario) != "auditor":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJE_SOLO_AUDITOR)
        try:
            id_usuario = UUID(_id_usuario(usuario))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJE_SOLO_AUDITOR)

        observaciones = (observaciones or "").strip() or None
        if observaciones and len(observaciones) > 4000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Las observaciones de finalización admiten máximo 4000 caracteres.",
            )

        escritas: list[str] = []
        try:
            # 1. Visita: 404 / 409 (cancelada o ya finalizada) / 403 (no asignado).
            await AgendaAuditorService(self.db).finalizar_programacion(
                id_programacion, id_usuario, observaciones, es_admin=False, confirmar=False
            )
            # 2. Obligatorios (422): primero la evaluación, luego el Excel.
            valores = validar_calificacion(evaluacion)
            excel = evaluacion_excel.validar_excel(archivo_nombre, archivo_contenido)
            # 3. Calificación (sin commit).
            calificacion = await CalificacionVisitaService(self.db).registrar(
                id_programacion, valores, usuario, exigir_inicio=True
            )
            id_solicitud = calificacion.pop("id_solicitud_visita", None) or calificacion.get("id_solicitud")
            creada = bool(calificacion.pop("creada", True))
            # 4. Excel (disco + base compartida si existe, en un SAVEPOINT).
            escritas = [
                evaluacion_excel.ruta_excel(id_programacion, id_usuario, excel.extension),
                evaluacion_excel.ruta_metadatos(id_programacion, id_usuario),
            ]
            guardado = await evaluacion_excel.guardar_excel(
                self.db, id_programacion, id_usuario, excel, usuario
            )
            # 5. ¿Pasa al Comité?
            transicion = await self._pasar_a_comite(id_solicitud, usuario)
            await self.db.commit()
        except HTTPException:
            await self.db.rollback()
            evaluacion_excel.borrar_del_disco(escritas)
            raise
        except DBAPIError as exc:
            await self.db.rollback()
            evaluacion_excel.borrar_del_disco(escritas)
            if _es_tabla_inexistente(exc):
                raise _falta_sql() from exc
            raise
        except Exception:
            await self.db.rollback()
            evaluacion_excel.borrar_del_disco(escritas)
            raise

        meta = guardado["metadatos"]
        if transicion["paso_a_comite"]:
            mensaje = (
                "Auditoría finalizada. La evaluación y el Excel quedaron registrados y el "
                "expediente pasó al Comité (En revisión)."
            )
        elif transicion["visitas_pendientes"]:
            n = transicion["visitas_pendientes"]
            mensaje = (
                "Auditoría finalizada con su evaluación y el Excel. "
                f"El expediente pasará al Comité cuando se finalice{'n' if n > 1 else ''} "
                f"la{'s' if n > 1 else ''} {n} visita{'s' if n > 1 else ''} pendiente{'s' if n > 1 else ''}."
            )
        else:
            mensaje = "Auditoría finalizada. La evaluación y el Excel quedaron registrados en el expediente."
        return {
            "mensaje": mensaje,
            "estado": "Finalizada",
            "observaciones": observaciones,
            "calificacion": {**calificacion, "creada": creada},
            "excel": {
                "nombre": meta["nombre_original"],
                "tamano_bytes": meta["tamano_bytes"],
                "sha256": meta["sha256"],
            },
            "estado_solicitud": transicion["estado_solicitud"],
            "paso_a_comite": transicion["paso_a_comite"],
            "visitas_pendientes": transicion["visitas_pendientes"],
        }

    async def _pasar_a_comite(self, id_solicitud, usuario: dict) -> dict:
        """Aprobada (por el Coordinador) → En revision cuando no quedan visitas por finalizar.

        La solicitud ya está bloqueada (FOR UPDATE) por `registrar`.
        """
        resultado = await self.db.execute(text(f"""
            SELECT s.estado, {SQL_COMITE_DECIDIO} AS comite_decidio,
                   (SELECT COUNT(*) FROM programacion_visita p
                    WHERE p.id_solicitud = s.id_solicitud
                      AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                          ({", ".join(f"'{e}'" for e in ESTADOS_VISITA_CERRADA)})) AS pendientes
            FROM solicitud s
            WHERE s.id_solicitud = :id AND s.deleted_at IS NULL;
        """), {"id": str(id_solicitud)})
        fila = resultado.mappings().first() or {}
        estado_actual = fila.get("estado")
        pendientes = int(fila.get("pendientes") or 0)
        respuesta = {"estado_solicitud": estado_actual, "paso_a_comite": False, "visitas_pendientes": pendientes}
        if pendientes or fila.get("comite_decidio") or not estados.es(estado_actual, estados.APROBADA):
            # Radicada / En revision ya están en la bandeja del Comité.
            return respuesta

        await self.db.execute(text("""
            UPDATE solicitud SET estado = :estado
            WHERE id_solicitud = :id AND deleted_at IS NULL;
        """), {"estado": estados.EN_REVISION, "id": str(id_solicitud)})
        await self.db.execute(text("""
            INSERT INTO historial_estado (id_solicitud, estado, fecha, observacion, id_usuario_actor)
            VALUES (:id, :estado, CURRENT_DATE, :observacion, :actor);
        """), {
            "id": str(id_solicitud),
            "estado": estados.EN_REVISION,
            "observacion": "Auditoría finalizada y evaluada por el auditor: el expediente pasa al Comité.",
            "actor": _id_usuario(usuario) or None,
        })
        await bitacora.registrar(
            self.db, id_solicitud, "Cambio de estado", usuario,
            {"anterior": estado_actual, "nuevo": estados.EN_REVISION,
             "motivo": "Visitas finalizadas con evaluación y Excel"},
            codigo="SOL-006",
        )
        respuesta.update(estado_solicitud=estados.EN_REVISION, paso_a_comite=True)
        return respuesta
