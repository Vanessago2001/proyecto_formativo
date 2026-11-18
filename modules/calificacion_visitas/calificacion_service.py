"""
Calificación (evaluación) de visitas por los auditores (1 a 100 %) para el Comité.

Rol único "Auditor" (decisión de la usuaria, 17/11/2026): "El auditor de la
visita es el auditor encargado de subir la evaluación; al tener evaluación
se puede aprobar o rechazar." Cualquier auditor asignado a la visita
(`detalle_programacion_auditor`) la evalúa y deja comentarios: sobre la
visita, situaciones encontradas y oportunidades de mejora. El Comité las ve
en el expediente antes de aprobar o rechazar.

Reglas:
  · Evalúa cualquier auditor asignado a esa visita (los demás reciben 403).
    Cada auditor tiene UNA evaluación por visita (UNIQUE id_programacion,
    id_auditor) que puede editar.
  · Cada visita no cancelada del expediente necesita AL MENOS UNA
    evaluación de un auditor asignado para que el Comité apruebe o rechace
    (409 con la visita que falta, ver `estado_para_decidir`). Si varios
    auditores de la misma visita la evalúan se muestran todas y su promedio.
    Si la tabla aún no existe (falta el SQL) la decisión NO se bloquea.
  · La visita no puede estar cancelada y debe haber empezado
    (fecha_inicio ya pasó) o estar Finalizada/Ejecutada.
  · La visita debe pertenecer a una solicitud vigente.
  · Se puede editar mientras el Comité no haya decidido: con la solicitud
    Aprobada, Rechazada, Cerrada (o Cancelada) queda bloqueada (409).
  · Lo lee el Comité y el Coordinador; nadie más. Un miembro del Comité
    impedido para la solicitud no lo ve (regla de imparcialidad,
    modules/comite/imparcialidad.py).

La tabla `calificacion_visita` la crea la usuaria con
documentacion/sql_calificacion_visitas.sql. Mientras no exista, todo
responde 503 con un mensaje claro en vez de un 500.
"""

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core import almacen_archivos
from core.security import _normalize_role_name
from modules.calificacion_visitas import evaluacion_excel
from modules.comite.imparcialidad import exigir_imparcialidad
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

MENSAJE_NO_ASIGNADO = "Solo un auditor asignado a esta visita puede evaluarla."


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


# Acciones del Comité que fijan su decisión (ver comite_service).
ACCIONES_DECISION_COMITE = ("aprobar", "rechazar", "decisiones", "decision-definitiva")
SQL_COMITE_DECIDIO = (
    "EXISTS (SELECT 1 FROM comite_accion ca WHERE ca.id_solicitud = s.id_solicitud "
    "AND ca.accion IN ('aprobar', 'rechazar', 'decisiones', 'decision-definitiva'))"
)


def _decision_tomada(estado_solicitud, comite_decidio: bool | None = True) -> bool:
    """¿El expediente ya tiene la decisión del Comité (o se cerró/canceló)?

    'Aprobada' es ambiguo: el Coordinador aprueba la solicitud ANTES de asignar
    el auditor y programar las visitas (asignacion_service exige 'Aprobada'),
    y el Comité también deja 'Aprobada' al otorgar. Con 'Aprobada' solo cuenta
    como decidido si el Comité registró su decisión (`comite_accion`); así el
    auditor puede evaluar y finalizar las visitas de una solicitud aprobada
    por el Coordinador. Rechazada, Cerrada y Cancelada siempre bloquean.
    """
    canonico = estados.normalizar(estado_solicitud) or ""
    if canonico == estados.APROBADA:
        return bool(comite_decidio)
    return canonico in ESTADOS_SOLICITUD_BLOQUEADA


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
        resultado = await self.db.execute(text(f"""
            SELECT c.id_calificacion, c.id_programacion, c.id_solicitud, c.calificacion,
                   c.comentario_visita, c.situaciones_encontradas, c.oportunidades_mejora,
                   c.fecha_registro, c.fecha_actualizacion,
                   s.estado AS estado_solicitud,
                   {SQL_COMITE_DECIDIO} AS comite_decidio
            FROM calificacion_visita c
            LEFT JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            WHERE c.id_auditor = :id_auditor
            ORDER BY COALESCE(c.fecha_actualizacion, c.fecha_registro) DESC;
        """), {"id_auditor": _id_usuario(usuario)})
        filas = []
        for fila in resultado.mappings().all():
            dato = dict(fila)
            dato["bloqueada"] = _decision_tomada(
                dato.pop("estado_solicitud", None), dato.pop("comite_decidio", True)
            )
            filas.append(dato)
        # Visitas a las que está asignado: en todas ve el botón de evaluar.
        asignaciones = await self.db.execute(text("""
            SELECT DISTINCT id_programacion
            FROM detalle_programacion_auditor
            WHERE id_usuario = :id_auditor;
        """), {"id_auditor": _id_usuario(usuario)})
        visitas = sorted({str(fila["id_programacion"]) for fila in asignaciones.mappings().all()})
        # `visitas_lider` se conserva por compatibilidad con pantallas viejas.
        return {"calificaciones": filas, "visitas_asignadas": visitas, "visitas_lider": visitas}

    async def guardar(self, id_programacion: UUID, datos: dict, usuario: dict) -> dict:
        valores = self._validar_para(usuario, datos)
        try:
            fila = await self.registrar(id_programacion, valores, usuario)
            await self.db.commit()
        except DBAPIError as exc:
            await self.db.rollback()
            if _es_tabla_inexistente(exc):
                raise _falta_sql() from exc
            raise
        creada = bool(fila.pop("creada", True))
        fila.pop("id_solicitud_visita", None)
        return {
            "mensaje": "Calificación registrada." if creada else "Calificación actualizada.",
            "calificacion": fila,
        }

    @staticmethod
    def _validar_para(usuario: dict, datos: dict) -> dict:
        if _rol(usuario) != "auditor":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo los auditores califican visitas.")
        return validar_calificacion(datos)

    async def registrar(
        self,
        id_programacion: UUID,
        valores: dict,
        usuario: dict,
        exigir_inicio: bool = False,
    ) -> dict:
        """Inserta o actualiza la calificación SIN confirmar (quien llama hace commit).

        `valores` ya pasó por `validar_calificacion`. `exigir_inicio`: la
        visita debe haber empezado aunque ya figure como terminada (al
        finalizarla en la misma transacción su estado ya cambió).
        """
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
            # Evalúa cualquier auditor de la visita (rol único "Auditor").
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MENSAJE_NO_ASIGNADO)
        estado_visita = str(visita["estado"] or "").strip().upper()
        if estado_visita in ESTADOS_VISITA_CANCELADA:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede calificar una visita cancelada.")
        terminada = estado_visita in ESTADOS_VISITA_TERMINADA and not exigir_inicio
        if not terminada and not _ya_empezo(visita["fecha_inicio"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La visita todavía no ha empezado: podrás "
                    + ("finalizarla y evaluarla" if exigir_inicio else "calificarla")
                    + " desde su fecha de inicio."
                ),
            )
        if not visita["id_solicitud"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La visita no está asociada a una solicitud, así que no hay expediente para el Comité.",
            )

        # Se bloquea la solicitud como lo hace el Comité al decidir, así una
        # calificación no se cuela justo mientras se aprueba o rechaza.
        resultado = await self.db.execute(text(f"""
            SELECT s.estado, {SQL_COMITE_DECIDIO} AS comite_decidio
            FROM solicitud s
            WHERE s.id_solicitud = :id_solicitud AND s.deleted_at IS NULL
            FOR UPDATE OF s;
        """), {"id_solicitud": str(visita["id_solicitud"])})
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La solicitud de la visita no existe o fue eliminada.")
        if _decision_tomada(solicitud["estado"], solicitud.get("comite_decidio", True)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"El expediente ya está {str(solicitud['estado']).lower()}: "
                    "la calificación quedó cerrada y no se puede modificar."
                ),
            )

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
        fila["id_solicitud_visita"] = visita["id_solicitud"]
        return fila

    # ------------------------------------------------------------------
    # Comité
    # ------------------------------------------------------------------
    async def _tabla_existe(self) -> bool:
        resultado = await self.db.execute(text("SELECT to_regclass('public.calificacion_visita') IS NOT NULL AS existe;"))
        fila = resultado.mappings().first()
        return bool(fila and fila["existe"])

    async def _visitas_con_evaluaciones(self, id_solicitud) -> list[dict]:
        """
        Cada visita no cancelada del expediente con las evaluaciones de sus
        auditores asignados (todas) y su promedio.
        """
        resultado = await self.db.execute(text("""
            SELECT p.id_programacion, p.fecha_inicio, p.fecha_fin, p.estado AS estado_visita,
                   (SELECT COUNT(DISTINCT d.id_usuario) FROM detalle_programacion_auditor d
                    WHERE d.id_programacion = p.id_programacion) AS auditores_asignados,
                   COALESCE((
                       SELECT json_agg(json_build_object(
                           'id_auditor', c.id_auditor,
                           'nombre', u.nombre,
                           'rol', 'Auditor',
                           'calificacion', c.calificacion,
                           'comentario_visita', c.comentario_visita,
                           'situaciones_encontradas', c.situaciones_encontradas,
                           'oportunidades_mejora', c.oportunidades_mejora,
                           'fecha_registro', c.fecha_registro,
                           'fecha_actualizacion', c.fecha_actualizacion
                       ) ORDER BY c.fecha_registro, c.id_calificacion)
                       FROM calificacion_visita c
                       LEFT JOIN usuario u ON u.id_usuario = c.id_auditor
                       WHERE c.id_programacion = p.id_programacion
                         -- Solo cuentan las de auditores que siguen asignados.
                         AND EXISTS (SELECT 1 FROM detalle_programacion_auditor d
                                     WHERE d.id_programacion = c.id_programacion
                                       AND d.id_usuario = c.id_auditor)
                   ), '[]'::json) AS evaluaciones
            FROM programacion_visita p
            WHERE p.id_solicitud = CAST(:id AS UUID)
              AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN ('CANCELADA', 'CANCELADO')
            ORDER BY p.fecha_inicio NULLS LAST, p.id_programacion;
        """), {"id": str(id_solicitud)})
        visitas = []
        for fila in resultado.mappings().all():
            visita = dict(fila)
            evaluaciones = visita.get("evaluaciones") or []
            if isinstance(evaluaciones, str):
                evaluaciones = json.loads(evaluaciones)
            notas = [e["calificacion"] for e in evaluaciones if e.get("calificacion") is not None]
            visita["evaluaciones"] = evaluaciones
            visita["total_evaluaciones"] = len(notas)
            # Nota de la visita: el promedio de sus evaluaciones (o la única).
            visita["calificacion"] = round(sum(notas) / len(notas), 1) if notas else None
            visitas.append(visita)
        return visitas

    @staticmethod
    def _faltantes(visitas: list[dict]) -> list[dict]:
        faltantes = []
        for numero, visita in enumerate(visitas, start=1):
            if visita.get("total_evaluaciones"):
                continue
            faltantes.append({
                "numero": numero,
                "id_programacion": str(visita.get("id_programacion")),
                "fecha_inicio": visita.get("fecha_inicio"),
                "motivo": "sin_evaluacion" if visita.get("auditores_asignados") else "sin_auditor",
            })
        return faltantes

    @staticmethod
    def describir_faltante(faltante: dict) -> str:
        fecha = faltante.get("fecha_inicio")
        if isinstance(fecha, datetime):
            fecha = fecha.strftime("%d/%m/%Y")
        visita = f"visita {faltante.get('numero')}" + (f" del {fecha}" if fecha else "")
        if faltante.get("motivo") == "sin_auditor":
            return f"la {visita} no tiene auditores asignados que puedan evaluarla"
        return f"falta la evaluación de la {visita}"

    async def estado_para_decidir(self, id_solicitud) -> dict:
        """
        ¿Puede el Comité aprobar o rechazar? Exige al menos una evaluación de
        un auditor asignado en cada visita no cancelada. Sin la tabla (SQL sin aplicar) NO bloquea:
        devuelve activa=False para que la pantalla muestre el aviso.
        """
        if not await self._tabla_existe():
            return {"activa": False, "faltantes": [], "puede_decidir": True}
        faltantes = self._faltantes(await self._visitas_con_evaluaciones(id_solicitud))
        return {"activa": True, "faltantes": faltantes, "puede_decidir": not faltantes}

    async def exigir_calificaciones_para_decidir(self, id_solicitud) -> None:
        """409 si alguna visita no cancelada no tiene ninguna evaluación de un auditor asignado."""
        estado = await self.estado_para_decidir(id_solicitud)
        if estado["faltantes"]:
            detalle = "; ".join(self.describir_faltante(f) for f in estado["faltantes"])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El Comité no puede aprobar ni rechazar todavía: "
                    f"{detalle}. La evaluación la sube un auditor asignado a la visita."
                ),
            )

    async def calificaciones_expediente(self, id_solicitud: UUID, usuario: dict) -> dict:
        if _rol(usuario) not in ROLES_LECTURA_COMITE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el Comité y el Coordinador pueden consultar las calificaciones de los auditores.",
            )
        # Un miembro del Comité impedido para la solicitud no la ve.
        await exigir_imparcialidad(self.db, id_solicitud, usuario)
        await self._exigir_tabla()
        resultado = await self.db.execute(text("""
            SELECT id_solicitud, estado FROM solicitud
            WHERE id_solicitud = :id AND deleted_at IS NULL;
        """), {"id": str(id_solicitud)})
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El expediente no existe o fue eliminado.")

        visitas = await self._visitas_con_evaluaciones(id_solicitud)
        await self._adjuntar_excel(visitas)
        faltantes = self._faltantes(visitas)
        # Nota de cada visita = promedio de sus evaluaciones.
        notas = [v["calificacion"] for v in visitas if v.get("calificacion") is not None]
        # El promedio solo tiene sentido con varias visitas.
        promedio = round(sum(notas) / len(notas), 1) if notas and len(visitas) > 1 else None
        return {
            "expediente_id": str(id_solicitud),
            "estado_expediente": solicitud["estado"],
            "bloqueada": _decision_tomada(solicitud["estado"]),
            "activa": True,
            "visitas": visitas,
            "total_visitas": len(visitas),
            "calificadas": len(notas),
            "promedio": promedio,
            "faltantes": [{**f, "texto": self.describir_faltante(f)} for f in faltantes],
            "puede_decidir": not faltantes,
        }

    # ------------------------------------------------------------------
    # Excel de la evaluación (adjunto obligatorio al finalizar la visita)
    # ------------------------------------------------------------------
    async def _adjuntar_excel(self, visitas: list[dict]) -> None:
        """Agrega a cada evaluación `excel` = {nombre, tamano_bytes, fecha_subida} o None."""
        for visita in visitas:
            for evaluacion in visita.get("evaluaciones") or []:
                meta = await evaluacion_excel.leer_metadatos(
                    self.db, visita.get("id_programacion"), evaluacion.get("id_auditor")
                )
                evaluacion["excel"] = (
                    {
                        "nombre": meta.get("nombre_original"),
                        "tamano_bytes": meta.get("tamano_bytes"),
                        "fecha_subida": meta.get("fecha_subida"),
                    }
                    if meta else None
                )

    async def descargar_excel(
        self, id_solicitud: UUID, id_programacion: UUID, id_auditor: UUID, usuario: dict
    ) -> tuple[bytes, str, str]:
        """Contenido, nombre y tipo del Excel de una evaluación (mismos permisos del expediente)."""
        if _rol(usuario) not in ROLES_LECTURA_COMITE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el Comité y el Coordinador pueden descargar la evaluación de la visita.",
            )
        # Un miembro del Comité impedido para la solicitud no la ve.
        await exigir_imparcialidad(self.db, id_solicitud, usuario)
        resultado = await self.db.execute(text("""
            SELECT p.id_programacion
            FROM programacion_visita p
            JOIN solicitud s ON s.id_solicitud = p.id_solicitud AND s.deleted_at IS NULL
            WHERE p.id_programacion = :id_programacion
              AND p.id_solicitud = :id_solicitud
              AND EXISTS (SELECT 1 FROM detalle_programacion_auditor d
                          WHERE d.id_programacion = p.id_programacion
                            AND d.id_usuario = :id_auditor);
        """), {
            "id_programacion": str(id_programacion),
            "id_solicitud": str(id_solicitud),
            "id_auditor": str(id_auditor),
        })
        if not resultado.mappings().first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La visita no pertenece a este expediente.")
        meta = await evaluacion_excel.leer_metadatos(self.db, id_programacion, id_auditor)
        contenido = None
        if meta:
            contenido = await almacen_archivos.leer(
                evaluacion_excel.ruta_excel(id_programacion, id_auditor, meta["extension"]), db=self.db
            )
        if not contenido:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Esta evaluación no tiene el archivo Excel adjunto en este servidor.",
            )
        nombre = meta.get("nombre_original") or f"evaluacion_visita{meta['extension']}"
        return contenido, nombre, evaluacion_excel.TIPOS_CONTENIDO[meta["extension"]]
