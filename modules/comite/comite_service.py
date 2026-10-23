"""Persistencia y transiciones del ciclo de vida de decisiones del comité."""

import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


ESTADOS_FINALES = {
    "APROBADO",
    "APROBADA",
    "RECHAZADO",
    "RECHAZADA",
    "CERRADO",
    "CERRADA",
}
ESTADOS_DICTAMEN = {"APROBADO", "APROBADA", "RECHAZADO", "RECHAZADA"}
CAMBIOS_ESTADO = {
    "aprobar": "APROBADO",
    "rechazar": "RECHAZADO",
    "cerrar-expediente": "CERRADO",
    "reabrir-dictamen": "En revision",
}


class ComiteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def registrar_accion(
        self,
        accion: str,
        datos: dict,
        usuario: dict,
    ) -> dict:
        """Guarda una acción y su transición de estado en una única transacción."""
        try:
            id_solicitud = UUID(str(datos.get("expediente_id") or datos.get("id_solicitud")))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El campo expediente_id debe ser un UUID válido.",
            )

        comentario = datos.get("comentario")
        if not isinstance(comentario, str) or not comentario.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El comentario es obligatorio para registrar una acción del comité.",
            )

        resultado = await self.db.execute(
            text("""
                SELECT id_solicitud, estado
                FROM solicitud
                WHERE id_solicitud = :id_solicitud
                  AND deleted_at IS NULL
                FOR UPDATE;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El expediente no existe o fue eliminado.",
            )

        estado_actual = solicitud["estado"]
        nuevo_estado = CAMBIOS_ESTADO.get(accion)
        estado_normalizado = str(estado_actual).strip().upper()
        if estado_normalizado in {"CERRADO", "CERRADA"} and accion != "reabrir-dictamen":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El expediente ya está en estado {estado_actual}.",
            )
        if accion in {"aprobar", "rechazar", "decision-definitiva"} and estado_normalizado in ESTADOS_DICTAMEN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El expediente ya tiene un dictamen {estado_actual.lower()}.",
            )
        if accion in {"acta-definitiva", "firmar-acta", "cerrar-expediente"} and estado_normalizado not in ESTADOS_DICTAMEN:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La acción requiere que el expediente tenga un dictamen aprobado o rechazado.",
            )
        if accion == "reabrir-dictamen" and estado_normalizado not in ESTADOS_FINALES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se puede reabrir un expediente con dictamen final o cerrado.",
            )

        if nuevo_estado:
            actualizacion = await self.db.execute(
                text("""
                    UPDATE solicitud
                    SET estado = :estado
                    WHERE id_solicitud = :id_solicitud
                      AND deleted_at IS NULL
                    RETURNING estado;
                """),
                {"estado": nuevo_estado, "id_solicitud": str(id_solicitud)},
            )
            fila_estado = actualizacion.mappings().first()
            if not fila_estado:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El expediente no existe o fue eliminado.",
                )
            estado_actual = fila_estado["estado"]
            await self.db.execute(
                text("""
                    INSERT INTO historial_estado (
                        id_solicitud, estado, fecha, observacion
                    )
                    VALUES (
                        :id_solicitud,
                        :estado,
                        CURRENT_DATE,
                        :observacion
                    );
                """),
                {
                    "id_solicitud": str(id_solicitud),
                    "estado": estado_actual,
                    "observacion": f"[COM] {accion} por {usuario.get('nombre') or usuario.get('correo') or 'usuario'}"[:255],
                },
            )

        datos_json = json.dumps(datos, ensure_ascii=False, default=str)
        guardado = await self.db.execute(
            text("""
                INSERT INTO comite_accion (id_solicitud, accion, datos, id_usuario)
                VALUES (
                    :id_solicitud,
                    :accion,
                    CAST(:datos AS JSONB),
                    :id_usuario
                )
                RETURNING id_accion, id_solicitud, accion, fecha;
            """),
            {
                "id_solicitud": str(id_solicitud),
                "accion": accion,
                "datos": datos_json,
                "id_usuario": str(usuario.get("id_usuario") or usuario.get("id") or ""),
            },
        )
        registro = guardado.mappings().first()
        if not registro:
            raise RuntimeError("La base de datos no devolvió el registro de la acción del comité.")

        await self.db.commit()
        mensaje = "La acción del comité fue guardada."
        if accion == "firmar-acta":
            mensaje = "La solicitud de firma quedó registrada; aún no se genera firma electrónica ni PDF."
        elif accion == "acta-definitiva":
            mensaje = "La solicitud de generación del acta quedó registrada; aún no se genera un PDF."
        elif accion == "solicitar-info-adicional":
            mensaje = "La solicitud de información quedó registrada; no se envió una notificación al auditor."
        return {
            "id_accion": str(registro["id_accion"]),
            "expediente_id": str(registro["id_solicitud"]),
            "accion": registro["accion"],
            "estado": estado_actual,
            "fecha": registro["fecha"],
            "mensaje": mensaje,
        }
