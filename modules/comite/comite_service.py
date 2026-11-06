"""Persistencia y transiciones del ciclo de vida de decisiones del comité."""

import json
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes import estado_solicitud as estados


# Los estados los pone el catalogo de M5, que es el dueno del ciclo de vida
# de la solicitud. Antes aqui se escribia 'APROBADO' mientras M5 guardaba
# 'Aprobada': para una consulta no son lo mismo, y las solicitudes que pasaban
# por el Comite desaparecian de las listas del resto de modulos.
ESTADOS_FINALES = {estados.APROBADA, estados.RECHAZADA, estados.CERRADA}
ESTADOS_DICTAMEN = {estados.APROBADA, estados.RECHAZADA}
CAMBIOS_ESTADO = {
    "aprobar": estados.APROBADA,
    "rechazar": estados.RECHAZADA,
    "cerrar-expediente": estados.CERRADA,
    "reabrir-dictamen": estados.EN_REVISION,
}


# Cola del Comité (COM-001). El estado lo decide SIEMPRE el filtro de estado;
# el buscador (NIT, radicado o empresa), la norma y las fechas solo restringen.
# Antes la lista inicial traía solo Radicada/En revisión y la búsqueda por NIT
# traía todos los estados, así que el mismo expediente aparecía o no según se
# hubiera escrito algo en el buscador.
FILTRO_ESTADO_PENDIENTES = "pendientes"
FILTRO_ESTADO_TODOS = "todos"
ESTADOS_PENDIENTES_COMITE = (estados.RADICADA, estados.EN_REVISION)


def _sin_separadores(valor: str) -> str:
    return "".join(c for c in str(valor or "").upper() if c.isalnum())


def construir_filtro_expedientes(
    estado: str | None = None,
    q: str | None = None,
    norma: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> tuple[str, dict]:
    """
    Devuelve (condiciones SQL adicionales, parámetros) para la cola del Comité.

    `estado`: 'pendientes' (por defecto: Radicada y En revision), 'todos' o
    cualquier estado del catálogo de M5 escrito como sea ('APROBADO' vale
    por 'Aprobada'). Se compara contra el valor canónico de la columna, así
    que también entran filas viejas con otra grafía.
    """
    condiciones: list[str] = []
    params: dict = {}

    valor_estado = str(estado or FILTRO_ESTADO_PENDIENTES).strip().lower()
    if valor_estado == FILTRO_ESTADO_PENDIENTES:
        lista = ESTADOS_PENDIENTES_COMITE
    elif valor_estado == FILTRO_ESTADO_TODOS:
        lista = ()
    else:
        canonico = estados.normalizar(estado)
        if canonico is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Estado de expediente desconocido: {estado!r}. Usa 'pendientes', "
                    f"'todos' o uno de: {', '.join(estados.ESTADOS)}."
                ),
            )
        lista = (canonico,)
    if lista:
        nombres = []
        for i, valor in enumerate(lista):
            params[f"estado_{i}"] = valor
            nombres.append(f":estado_{i}")
        condiciones.append(f"({estados.sql_canonico('s.estado')}) IN ({', '.join(nombres)})")

    texto = str(q or "").strip()
    if texto:
        params["q"] = f"%{texto}%"
        compacto = _sin_separadores(texto)
        params["q_compacto"] = f"%{compacto}%" if compacto else params["q"]
        condiciones.append(
            "(s.numero_radicado ILIKE :q OR e.nit ILIKE :q OR e.nombre ILIKE :q"
            " OR REGEXP_REPLACE(UPPER(COALESCE(e.nit, '')), '[^A-Z0-9]', '', 'g') LIKE :q_compacto)"
        )

    valor_norma = _sin_separadores(norma or "")
    if valor_norma:
        params["norma"] = valor_norma
        condiciones.append(
            "REGEXP_REPLACE(UPPER(COALESCE(n.codigo, '')), '[^A-Z0-9]', '', 'g') = :norma"
        )

    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La fecha inicial no puede ser posterior a la fecha final.",
        )
    if fecha_desde:
        params["fecha_desde"] = fecha_desde
        condiciones.append("CAST(COALESCE(s.fecha_radicacion, s.fecha_creacion) AS DATE) >= :fecha_desde")
    if fecha_hasta:
        params["fecha_hasta"] = fecha_hasta
        condiciones.append("CAST(COALESCE(s.fecha_radicacion, s.fecha_creacion) AS DATE) <= :fecha_hasta")

    sql = "".join(f"\n          AND {c}" for c in condiciones)
    return sql, params


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
        # Se compara por el valor canonico, no por mayusculas: asi da igual
        # como estuviera escrito el estado en la base.
        estado_normalizado = estados.normalizar(estado_actual) or str(estado_actual).strip()
        if estado_normalizado == estados.CERRADA and accion != "reabrir-dictamen":
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
