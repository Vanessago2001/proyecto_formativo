"""
Calificación de visitas por los auditores (1 a 100 %) para el Comité.

Cada auditor asignado a una visita (`detalle_programacion_auditor`) la
califica y deja comentarios: sobre la visita, situaciones encontradas y
oportunidades de mejora. El Comité las ve en el expediente antes de
aprobar o rechazar el certificado.

Reglas:
  · Solo califica un usuario con rol Auditor que esté asignado a esa visita.
  · La visita no puede estar cancelada y debe haber empezado
    (fecha_inicio ya pasó) o estar Finalizada/Ejecutada.
  · La visita debe pertenecer a una solicitud vigente.
  · Se puede editar mientras el Comité no haya decidido: con la solicitud
    Aprobada, Rechazada, Cerrada (o Cancelada) queda bloqueada (409).
  · Lo lee el Comité y el Coordinador; nadie más.

La tabla `calificacion_visita` la crea la usuaria con
documentacion/sql_calificacion_visitas.sql. Mientras no exista, todo
responde 503 con un mensaje claro en vez de un 500.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name
from modules.solicitudes import estado_solicitud as estados

TABLA = "calificacion_visita"
MENSAJE_FALTA_SQL = "Falta aplicar el SQL de calificación de visitas"

CALIFICACION_MIN = 1
CALIFICACION_MAX = 100
COMENTARIO_MIN = 10
COMENTARIO_MAX = 2000

CAMPOS_COMENTARIO = {
    "comentario_visita": "Comentarios sobre la visita",
    "situaciones_encontradas": "Situaciones encontradas",
    "oportunidades_mejora": "Oportunidades de mejora",
}

ESTADOS_VISITA_CANCELADA = {"CANCELADA", "CANCELADO"}
ESTADOS_VISITA_TERMINADA = {"FINALIZADA", "FINALIZADO", "EJECUTADA", "EJECUTADO"}
# Con el expediente en uno de estos estados el Comité ya decidió (o la
# solicitud se canceló): la calificación queda bloqueada.
ESTADOS_SOLICITUD_BLOQUEADA = {
    estados.APROBADA, estados.RECHAZADA, estados.CERRADA, estados.CANCELADA,
}

ROLES_LECTURA_COMITE = {"comite", "admin"}  # Comité y Coordinador


def _rol(usuario: dict | None) -> str:
    return _normalize_role_name((usuario or {}).get("role_name"))


def _id_usuario(usuario: dict | None) -> str:
    return str((usuario or {}).get("id_usuario") or "")


def _falta_sql() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MENSAJE_FALTA_SQL)


def _es_tabla_inexistente(exc: Exception) -> bool:
    texto = str(getattr(exc, "orig", None) or exc).lower()
    return TABLA in texto and ("does not exist" in texto or "no existe" in texto)


def validar_calificacion(datos: dict | None) -> dict:
    """Valida y limpia el cuerpo. Devuelve los valores listos para guardar (422 si algo falla)."""
    datos = datos if isinstance(datos, dict) else {}
    valor = datos.get("calificacion")
    if isinstance(valor, bool) or valor is None:
        numero = None
    elif isinstance(valor, int):
        numero = valor
    elif isinstance(valor, float) and valor.is_integer():
        numero = int(valor)
    elif isinstance(valor, str) and valor.strip().isdigit():
        numero = int(valor.strip())
    else:
        numero = None
    if numero is None or not CALIFICACION_MIN <= numero <= CALIFICACION_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La calificación debe ser un número entero entre 1 y 100 %.",
        )

    limpio: dict = {"calificacion": numero}
    for campo, etiqueta in CAMPOS_COMENTARIO.items():
        texto = datos.get(campo)
        if texto is not None and not isinstance(texto, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"El campo «{etiqueta}» debe ser texto.",
            )
        texto = (texto or "").strip()
        if texto and len(texto) < COMENTARIO_MIN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"«{etiqueta}» debe tener al menos {COMENTARIO_MIN} caracteres.",
            )
        if len(texto) > COMENTARIO_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"«{etiqueta}» admite máximo {COMENTARIO_MAX} caracteres.",
            )
        limpio[campo] = texto or None
    if not any(limpio[campo] for campo in CAMPOS_COMENTARIO):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Escribe al menos un comentario: sobre la visita, situaciones "
                "encontradas u oportunidades de mejora."
            ),
        )
    return limpio


def _ya_empezo(fecha_inicio, ahora: datetime | None = None) -> bool:
    if fecha_inicio is None:
        return False
    ahora = ahora or datetime.now(timezone.utc)
    if isinstance(fecha_inicio, datetime) and fecha_inicio.tzinfo is None:
        # programacion_visita.fecha_inicio es TIMESTAMP sin zona (hora local).
        ahora = ahora.astimezone().replace(tzinfo=None)
    elif not isinstance(fecha_inicio, datetime):
        return False
    return fecha_inicio <= ahora


def _decision_tomada(estado_solicitud) -> bool:
    return (estados.normalizar(estado_solicitud) or "") in ESTADOS_SOLICITUD_BLOQUEADA


class CalificacionVisitaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _exigir_tabla(self) -> None:
        resultado = await self.db.execute(text("SELECT to_regclass('public.calificacion_visita') IS NOT NULL AS existe;"))
        fila = resultado.mappings().first()
        if not fila or not fila["existe"]:
            raise _falta_sql()

    # ------------------------------------------------------------------
    # Auditor
    # ------------------------------------------------------------------
    async def mis_calificaciones(self, usuario: dict) -> dict:
        if _rol(usuario) != "auditor":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo los auditores califican visitas.")
        await self._exigir_tabla()
        resultado = await self.db.execute(text("""
            SELECT c.id_calificacion, c.id_programacion, c.id_solicitud, c.calificacion,
                   c.comentario_visita, c.situaciones_encontradas, c.oportunidades_mejora,
                   c.fecha_registro, c.fecha_actualizacion,
                   s.estado AS estado_solicitud
            FROM calificacion_visita c
            LEFT JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            WHERE c.id_auditor = :id_auditor
            ORDER BY COALESCE(c.fecha_actualizacion, c.fecha_registro) DESC;
        """), {"id_auditor": _id_usuario(usuario)})
        filas = []
        for fila in resultado.mappings().all():
            dato = dict(fila)
            dato["bloqueada"] = _decision_tomada(dato.pop("estado_solicitud", None))
            filas.append(dato)
        return {"calificaciones": filas}

    async def guardar(self, id_programacion: UUID, datos: dict, usuario: dict) -> dict:
        if _rol(usuario) != "auditor":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo los auditores califican visitas.")
        valores = validar_calificacion(datos)
        await self._exigir_tabla()
        id_auditor = _id_usuario(usuario)

        resultado = await self.db.execute(text("""
            SELECT p.id_programacion, p.id_solicitud, p.estado, p.fecha_inicio,
                   EXISTS (
                       SELECT 1 FROM detalle_programacion_auditor d
                       WHERE d.id_programacion = p.id_programacion
                         AND d.id_usuario = :id_auditor
                   ) AS asignado
            FROM programacion_visita p
            WHERE p.id_programacion = :id_programacion;
        """), {"id_programacion": str(id_programacion), "id_auditor": id_auditor})
        visita = resultado.mappings().first()
        if not visita:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La visita programada no existe.")
        if not visita["asignado"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el auditor asignado a esta visita puede calificarla.",
            )
        estado_visita = str(visita["estado"] or "").strip().upper()
        if estado_visita in ESTADOS_VISITA_CANCELADA:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede calificar una visita cancelada.")
        if estado_visita not in ESTADOS_VISITA_TERMINADA and not _ya_empezo(visita["fecha_inicio"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La visita todavía no ha empezado: podrás calificarla desde su fecha de inicio.",
            )
        if not visita["id_solicitud"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La visita no está asociada a una solicitud, así que no hay expediente para el Comité.",
            )

        # Se bloquea la solicitud como lo hace el Comité al decidir, así una
        # calificación no se cuela justo mientras se aprueba o rechaza.
        resultado = await self.db.execute(text("""
            SELECT estado FROM solicitud
            WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL
            FOR UPDATE;
        """), {"id_solicitud": str(visita["id_solicitud"])})
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La solicitud de la visita no existe o fue eliminada.")
        if _decision_tomada(solicitud["estado"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El expediente ya está {str(solicitud['estado']).lower()}: "
                    "la calificación quedó cerrada y no se puede modificar."
                ),
            )

        try:
            guardado = await self.db.execute(text("""
                INSERT INTO calificacion_visita (
                    id_programacion, id_solicitud, id_auditor, calificacion,
                    comentario_visita, situaciones_encontradas, oportunidades_mejora
                )
                VALUES (
                    :id_programacion, :id_solicitud, :id_auditor, :calificacion,
                    :comentario_visita, :situaciones_encontradas, :oportunidades_mejora
                )
                ON CONFLICT (id_programacion, id_auditor) DO UPDATE SET
                    calificacion = EXCLUDED.calificacion,
                    comentario_visita = EXCLUDED.comentario_visita,
                    situaciones_encontradas = EXCLUDED.situaciones_encontradas,
                    oportunidades_mejora = EXCLUDED.oportunidades_mejora,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                RETURNING id_calificacion, id_programacion, id_solicitud, calificacion,
                          comentario_visita, situaciones_encontradas, oportunidades_mejora,
                          fecha_registro, fecha_actualizacion, (xmax = 0) AS creada;
            """), {
                "id_programacion": str(id_programacion),
                "id_solicitud": str(visita["id_solicitud"]),
                "id_auditor": id_auditor,
                **valores,
            })
            fila = dict(guardado.mappings().first() or {})
            await self.db.commit()
        except DBAPIError as exc:
            await self.db.rollback()
            if _es_tabla_inexistente(exc):
                raise _falta_sql() from exc
            raise
        creada = bool(fila.pop("creada", True))
        return {
            "mensaje": "Calificación registrada." if creada else "Calificación actualizada.",
            "calificacion": fila,
        }

    # ------------------------------------------------------------------
    # Comité
    # ------------------------------------------------------------------
    async def calificaciones_expediente(self, id_solicitud: UUID, usuario: dict) -> dict:
        if _rol(usuario) not in ROLES_LECTURA_COMITE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el Comité y el Coordinador pueden consultar las calificaciones de los auditores.",
            )
        await self._exigir_tabla()
        resultado = await self.db.execute(text("""
            SELECT id_solicitud, estado FROM solicitud
            WHERE id_solicitud = :id AND deleted_at IS NULL;
        """), {"id": str(id_solicitud)})
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")

        # Todo el equipo de cada visita no cancelada, haya calificado o no;
        # más las calificaciones de quien ya no esté en el equipo (no se pierden).
        resultado = await self.db.execute(text("""
            SELECT p.id_programacion, p.fecha_inicio, p.fecha_fin, p.estado AS estado_visita,
                   u.id_usuario AS id_auditor, u.nombre, d.rol_auditor AS rol,
                   c.calificacion, c.comentario_visita, c.situaciones_encontradas,
                   c.oportunidades_mejora, c.fecha_registro, c.fecha_actualizacion
            FROM programacion_visita p
            JOIN detalle_programacion_auditor d ON d.id_programacion = p.id_programacion
            JOIN usuario u ON u.id_usuario = d.id_usuario
            LEFT JOIN calificacion_visita c
                   ON c.id_programacion = p.id_programacion AND c.id_auditor = d.id_usuario
            WHERE p.id_solicitud = :id
              AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN ('CANCELADA', 'CANCELADO')
            UNION ALL
            SELECT p.id_programacion, p.fecha_inicio, p.fecha_fin, p.estado,
                   u.id_usuario, u.nombre, NULL,
                   c.calificacion, c.comentario_visita, c.situaciones_encontradas,
                   c.oportunidades_mejora, c.fecha_registro, c.fecha_actualizacion
            FROM calificacion_visita c
            JOIN programacion_visita p ON p.id_programacion = c.id_programacion
            JOIN usuario u ON u.id_usuario = c.id_auditor
            WHERE c.id_solicitud = :id
              AND NOT EXISTS (
                  SELECT 1 FROM detalle_programacion_auditor d
                  WHERE d.id_programacion = c.id_programacion AND d.id_usuario = c.id_auditor
              )
        """), {"id": str(id_solicitud)})
        auditores = [dict(fila) for fila in resultado.mappings().all()]
        # Por visita (la más antigua primero) y, dentro de cada una, el líder primero.
        auditores.sort(key=lambda a: (
            str(a.get("fecha_inicio") or ""),
            str(a.get("id_programacion") or ""),
            0 if "lider" in str(a.get("rol") or "").lower().replace("í", "i") else 1,
            str(a.get("nombre") or "").lower(),
        ))
        notas = [a["calificacion"] for a in auditores if a.get("calificacion") is not None]
        promedio = round(sum(notas) / len(notas), 1) if notas else None
        return {
            "expediente_id": str(id_solicitud),
            "estado_expediente": solicitud["estado"],
            "bloqueada": _decision_tomada(solicitud["estado"]),
            "auditores": auditores,
            "total_auditores": len(auditores),
            "calificados": len(notas),
            "promedio": promedio,
        }
