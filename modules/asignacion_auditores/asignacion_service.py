"""
REQ-AUD-001 — Asignación de Auditores.

La asignación relaciona auditor, solicitud y rol. Las fechas, la disponibilidad
por intervalo y los cruces horarios se validan al programar desde Agenda.
"""

from datetime import date
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.asignacion_auditores.asignacion_schema import AsignacionAuditorCrear


# Estado aceptado por la constraint actual de auditores_solicitud.
ESTADO_ASIGNACION_INICIAL = "Agendada"
ESTADOS_ASIGNACION_ACTIVOS = (
    "Agendada",
    "Programada",
    "Confirmado",
    "Asignado",
    "Activo",
)


# Se consulta el perfil, las competencias y los conflictos de la postulación aprobada más reciente.
CTE_AUDITORES = """
WITH postulaciones_aprobadas AS (
    SELECT DISTINCT ON (pa.id_usuario)
        pa.id_usuario,
        pa.id_postulacion
    FROM postulacion_auditor pa
    WHERE LOWER(pa.estado) IN ('aprobado', 'aprobada')
    ORDER BY
        pa.id_usuario,
        pa.fecha_revision DESC NULLS LAST,
        pa.fecha_postulacion DESC NULLS LAST
), candidatos AS (
    SELECT
        u.id_usuario,
        u.nombre,
        u.correo,
        u.tipo_doc,
        u.num_doc,
        u.estado AS estado_usuario,
        u.estado_auditor,
        p.ciudad_residencia,
        p.departamento_residencia,
        p.modalidad_preferida,
        EXISTS (
            SELECT 1
            FROM competencia_auditor ca
            WHERE ca.id_usuario = u.id_usuario
              AND ca.id_postulacion = pa.id_postulacion
              AND ca.id_norma = :id_norma
              AND ca.es_vigente = TRUE
              AND ca.estado_validacion = 'Validado'
              AND CURRENT_DATE >= ca.fecha_inicio
              AND CURRENT_DATE <= ca.fecha_fin
        ) AS competencia_norma,
        EXISTS (
            SELECT 1
            FROM conflicto_interes ci
            WHERE ci.id_usuario = u.id_usuario
              AND ci.id_postulacion = pa.id_postulacion
              AND ci.id_empresa = :id_empresa
              AND ci.bloquea_asignacion = TRUE
              AND ci.estado = 'Activo'
        ) AS conflicto_interes,
        EXISTS (
            SELECT 1
            FROM auditores_solicitud asignado
            WHERE asignado.id_solicitud = :id_solicitud
              AND asignado.id_auditor = u.id_usuario
              AND asignado.estado_asignacion = ANY(
                  CAST(:estados_activos AS VARCHAR[])
              )
        ) AS ya_asignado
    FROM usuario u
    INNER JOIN postulaciones_aprobadas pa
        ON pa.id_usuario = u.id_usuario
    LEFT JOIN perfil_auditor p
        ON p.id_usuario = u.id_usuario
       AND p.id_postulacion = pa.id_postulacion
    CROSS JOIN (
        SELECT codigo AS norma_codigo, nombre AS norma_nombre
        FROM norma
        WHERE id_norma = :id_norma
        LIMIT 1
    ) n
    WHERE u.estado = 'Activo'
      AND u.estado_auditor = 'Activo'
)
"""


class AsignacionAuditorService:
    """Lógica de negocio de asignación y consulta de auditores."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # SOLICITUDES APROBADAS
    # ------------------------------------------------------------------
    async def listar_solicitudes_aprobadas(
        self,
        *,
        page: int = 1,
        page_size: int = 12,
        buscar: str | None = None,
        ciudad: str | None = None,
        desde: date | None = None,
        hasta: date | None = None,
        norma: str | None = None,
        sector: str | None = None,
    ) -> dict:
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        buscar = (buscar or "").strip() or None
        ciudad = (ciudad or "").strip() or None
        norma = (norma or "").strip() or None
        sector = (sector or "").strip() or None

        filtros = ["s.estado = 'APROBADO'", "s.deleted_at IS NULL"]
        params: dict = {}
        if buscar:
            filtros.append(
                "(COALESCE(s.numero_radicado, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%' "
                "OR COALESCE(e.nombre, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%' "
                "OR COALESCE(n.codigo, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%')"
            )
            params["buscar"] = buscar
        if ciudad:
            filtros.append("LOWER(COALESCE(e.ciudad, '')) LIKE LOWER(:ciudad)")
            params["ciudad"] = f"%{ciudad.strip().lower()}%"
        if desde:
            filtros.append("CAST(s.fecha AS DATE) >= :desde")
            params["desde"] = desde
        if hasta:
            filtros.append("CAST(s.fecha AS DATE) <= :hasta")
            params["hasta"] = hasta
        if norma:
            filtros.append("LOWER(COALESCE(n.codigo, '')) = LOWER(:norma)")
            params["norma"] = norma.strip()
        if sector:
            filtros.append(
                """EXISTS (
                    SELECT 1
                    FROM competencia_auditor ca
                    WHERE ca.id_norma = s.id_norma
                      AND LOWER(TRIM(COALESCE(ca.codigo_sector_iaf, ''))) = LOWER(:sector)
                      AND ca.es_vigente = TRUE
                      AND ca.estado_validacion = 'Validado'
                )"""
            )
            params["sector"] = sector.strip()

        where = " AND ".join(filtros)
        count_result = await self.db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE {where}
                """
            ),
            params,
        )
        total = int(count_result.scalar_one() or 0)
        total_pages = (total + page_size - 1) // page_size
        if total_pages and page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size

        result = await self.db.execute(
            text(
                f"""
                SELECT
                    s.id_solicitud,
                    s.numero_radicado,
                    s.estado,
                    s.id_empresa,
                    e.nombre AS empresa_nombre,
                    e.ciudad AS empresa_ciudad,
                    s.id_norma,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version,
                    s.fecha,
                    EXISTS (
                        SELECT 1
                        FROM programacion_visita pv
                        WHERE pv.id_solicitud = s.id_solicitud
                          AND UPPER(TRIM(COALESCE(pv.estado, ''))) NOT IN
                              ('CANCELADA', 'CANCELADO', 'EJECUTADA', 'EJECUTADO',
                               'FINALIZADA', 'FINALIZADO')
                    ) AS tiene_programacion
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE {where}
                ORDER BY s.fecha_creacion DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": offset},
        )
        return {
            "items": [dict(fila) for fila in result.mappings().all()],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    async def obtener_solicitud(self, id_solicitud: UUID) -> dict:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    s.id_solicitud,
                    s.numero_radicado,
                    s.estado,
                    s.id_empresa,
                    e.nombre AS empresa_nombre,
                    s.id_norma,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version,
                    s.fecha
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_solicitud = :id_solicitud
                  AND s.deleted_at IS NULL;
                """
            ),
            {"id_solicitud": str(id_solicitud)},
        )
        solicitud = resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La solicitud no existe.")

        solicitud = dict(solicitud)
        if solicitud["estado"] != "APROBADO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se pueden asignar auditores a solicitudes en estado APROBADO.",
            )
        if not solicitud.get("id_norma"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La solicitud no tiene una norma asociada para validar competencias.",
            )
        return solicitud

    # ------------------------------------------------------------------
    # CANDIDATOS Y PAGINACIÓN EN EL SERVIDOR
    # ------------------------------------------------------------------
    async def listar_auditores_elegibles(
        self,
        id_solicitud: UUID,
        *,
        page: int = 1,
        page_size: int = 12,
        buscar: str | None = None,
        ciudad: str | None = None,
        modalidad: str | None = None,
        competencia: str | None = None,
        conflicto: str | None = None,
    ) -> dict:
        solicitud = await self.obtener_solicitud(id_solicitud)
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        buscar = (buscar or "").strip() or None
        ciudad = (ciudad or "").strip() or None
        modalidad = (modalidad or "").strip() or None
        competencia = (competencia or "").strip().lower() or None
        conflicto = (conflicto or "").strip().lower() or None

        if competencia not in (None, "si", "no"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El filtro competencia debe ser 'si' o 'no'.",
            )
        if conflicto not in (None, "si", "no"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="El filtro conflicto debe ser 'si' o 'no'.",
            )

        params = {
            "id_solicitud": str(id_solicitud),
            "id_empresa": str(solicitud["id_empresa"]) if solicitud.get("id_empresa") else None,
            "id_norma": str(solicitud["id_norma"]),
            "estados_activos": list(ESTADOS_ASIGNACION_ACTIVOS),
            "buscar": buscar,
            "ciudad": ciudad,
            "modalidad": modalidad,
            "competencia": competencia,
            "conflicto": conflicto,
        }
        filtros = """
            WHERE (
                CAST(:buscar AS TEXT) IS NULL
                OR COALESCE(nombre, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%'
                OR COALESCE(correo, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%'
                OR COALESCE(tipo_doc, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%'
                OR COALESCE(num_doc, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%'
                OR CONCAT_WS(' ', tipo_doc, num_doc) ILIKE '%' || CAST(:buscar AS TEXT) || '%'
            )
              AND (
                CAST(:ciudad AS TEXT) IS NULL
                OR COALESCE(ciudad_residencia, '') ILIKE '%' || CAST(:ciudad AS TEXT) || '%'
            )
              AND (
                CAST(:modalidad AS TEXT) IS NULL
                OR LOWER(COALESCE(modalidad_preferida, '')) = LOWER(CAST(:modalidad AS TEXT))
            )
              AND (
                CAST(:competencia AS TEXT) IS NULL
                OR (CAST(:competencia AS TEXT) = 'si' AND competencia_norma = TRUE)
                OR (CAST(:competencia AS TEXT) = 'no' AND competencia_norma = FALSE)
            )
              AND (
                CAST(:conflicto AS TEXT) IS NULL
                OR (CAST(:conflicto AS TEXT) = 'si' AND conflicto_interes = TRUE)
                OR (CAST(:conflicto AS TEXT) = 'no' AND conflicto_interes = FALSE)
            )
        """
        count_result = await self.db.execute(
            text(CTE_AUDITORES + " SELECT COUNT(*) AS total FROM candidatos " + filtros),
            params,
        )
        total = int(count_result.scalar_one() or 0)
        total_pages = (total + page_size - 1) // page_size
        if total_pages and page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size

        result = await self.db.execute(
            text(
                CTE_AUDITORES
                + " SELECT * FROM candidatos "
                + filtros
                + " ORDER BY nombre ASC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": page_size, "offset": offset},
        )

        items = []
        for raw in result.mappings().all():
            fila = dict(raw)
            competencia_norma = bool(fila["competencia_norma"])
            conflicto = bool(fila["conflicto_interes"])
            ya_asignado = bool(fila["ya_asignado"])
            elegible = competencia_norma and not conflicto and not ya_asignado

            motivos = []
            if not competencia_norma:
                motivos.append("No tiene competencia vigente y validada para la norma de la solicitud.")
            if conflicto:
                motivos.append("Tiene un conflicto de interés activo con la empresa.")
            if ya_asignado:
                motivos.append("Ya tiene una asignación activa para esta solicitud.")

            items.append(
                {
                    "id_usuario": fila["id_usuario"],
                    "nombre": fila["nombre"],
                    "correo": fila["correo"],
                    "tipo_doc": fila["tipo_doc"],
                    "num_doc": fila["num_doc"],
                    "estado_usuario": fila["estado_usuario"],
                    "estado_auditor": fila["estado_auditor"],
                    "ciudad_residencia": fila["ciudad_residencia"],
                    "departamento_residencia": fila["departamento_residencia"],
                    "modalidad_preferida": fila["modalidad_preferida"],
                    "norma_codigo": fila.get("norma_codigo"),
                    "norma_nombre": fila.get("norma_nombre"),
                    "competencia_norma": competencia_norma,
                    "experiencia_sector": None,
                    "conflicto_interes": conflicto,
                    # Estas dos validaciones necesitan fechas/horas y se completan en Agenda.
                    "disponible": None,
                    "sin_cruce_horario": None,
                    "ya_asignado": ya_asignado,
                    "elegible": elegible,
                    "motivo": (
                        "Auditor elegible. La disponibilidad y los cruces se validan al programar en Agenda."
                        if elegible
                        else " ".join(motivos)
                    ),
                }
            )

        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    async def validar_auditor(
        self,
        id_solicitud: UUID,
        id_auditor: UUID,
        ignorar_ya_asignado: bool = False,
    ) -> dict:
        solicitud = await self.obtener_solicitud(id_solicitud)
        result = await self.db.execute(
            text(CTE_AUDITORES + " SELECT * FROM candidatos WHERE id_usuario = :id_auditor LIMIT 1"),
            {
                "id_solicitud": str(id_solicitud),
                "id_empresa": str(solicitud["id_empresa"]) if solicitud.get("id_empresa") else None,
                "id_norma": str(solicitud["id_norma"]),
                "estados_activos": list(ESTADOS_ASIGNACION_ACTIVOS),
                "id_auditor": str(id_auditor),
            },
        )
        fila = result.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El auditor no existe, no está activo o no tiene una postulación aprobada.",
            )

        competencia_norma = bool(fila["competencia_norma"])
        conflicto = bool(fila["conflicto_interes"])
        ya_asignado = bool(fila["ya_asignado"])
        elegible = competencia_norma and not conflicto
        if not ignorar_ya_asignado:
            elegible = elegible and not ya_asignado
        auditor = {
            "id_usuario": fila["id_usuario"],
            "competencia_norma": competencia_norma,
            "conflicto_interes": conflicto,
            "ya_asignado": ya_asignado,
            "elegible": elegible,
        }
        if not auditor["elegible"]:
            motivos = []
            if not competencia_norma:
                motivos.append("No tiene competencia vigente y validada para la norma.")
            if conflicto:
                motivos.append("Tiene un conflicto de interés activo con la empresa.")
            if ya_asignado:
                motivos.append("Ya está asignado a esta solicitud.")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El auditor no cumple las condiciones para ser asignado. " + " ".join(motivos),
            )
        return auditor

    # ------------------------------------------------------------------
    # CREAR ASIGNACIÓN SIN FECHAS
    # ------------------------------------------------------------------
    async def asignar(self, data: AsignacionAuditorCrear, usuario: dict) -> dict:
        del usuario  # El usuario autenticado se mantiene en la firma de la ruta.

        programacion_result = await self.db.execute(
            text(
                """
                SELECT 1
                FROM programacion_visita
                WHERE id_solicitud = :id_solicitud
                  AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'EJECUTADA', 'EJECUTADO',
                       'FINALIZADA', 'FINALIZADO')
                LIMIT 1
                """
            ),
            {"id_solicitud": str(data.id_solicitud)},
        )
        if programacion_result.first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La solicitud ya tiene una programacion activa. "
                    "No se pueden asignar mas auditores desde esta pantalla."
                ),
            )

        await self.validar_auditor(data.id_solicitud, data.id_auditor)

        if data.rol_auditor.value == "Auditor líder":
            resultado_lider = await self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM auditores_solicitud
                    WHERE id_solicitud = :id_solicitud
                      AND especialidad = 'Auditor líder'
                      AND estado_asignacion = ANY(CAST(:estados_activos AS VARCHAR[]))
                    LIMIT 1;
                    """
                ),
                {
                    "id_solicitud": str(data.id_solicitud),
                    "estados_activos": list(ESTADOS_ASIGNACION_ACTIVOS),
                },
            )
            if resultado_lider.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="La solicitud ya tiene un auditor líder.",
                )

        id_asignacion = uuid4()
        try:
            resultado = await self.db.execute(
                text(
                    """
                    INSERT INTO auditores_solicitud (
                        id,
                        id_solicitud,
                        id_auditor,
                        especialidad,
                        declaracion,
                        fecha_inicio_planificada,
                        fecha_fin_planificada,
                        estado_asignacion
                    )
                    VALUES (
                        :id,
                        :id_solicitud,
                        :id_auditor,
                        :especialidad,
                        TRUE,
                        NULL,
                        NULL,
                        :estado_asignacion
                    )
                    RETURNING
                        id,
                        id_solicitud,
                        id_auditor,
                        especialidad,
                        declaracion,
                        fecha_inicio_planificada,
                        fecha_fin_planificada,
                        estado_asignacion;
                    """
                ),
                {
                    "id": str(id_asignacion),
                    "id_solicitud": str(data.id_solicitud),
                    "id_auditor": str(data.id_auditor),
                    "especialidad": data.rol_auditor.value,
                    "estado_asignacion": ESTADO_ASIGNACION_INICIAL,
                },
            )
            asignacion = dict(resultado.mappings().one())
            info_result = await self.db.execute(
                text("SELECT nombre, correo FROM usuario WHERE id_usuario = :id_auditor LIMIT 1"),
                {"id_auditor": str(data.id_auditor)},
            )
            info = info_result.mappings().first() or {}
            await self.db.commit()
        except HTTPException:
            raise
        except Exception as exc:
            await self.db.rollback()
            mensaje = str(exc)
            if "chk_estado_asignacion" in mensaje:
                mensaje = (
                    f"El estado inicial '{ESTADO_ASIGNACION_INICIAL}' no está permitido por la base de datos. "
                    "Revisa la constraint chk_estado_asignacion."
                )
            if "not-null" in mensaje.lower() or "null value" in mensaje.lower():
                mensaje += (
                    " Si fecha_inicio_planificada o fecha_fin_planificada tienen NOT NULL, "
                    "aplica la migración para permitir asignaciones pendientes de agenda."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible registrar la asignación del auditor. Detalle: " + mensaje,
            ) from exc

        return {
            "id": str(asignacion["id"]),
            "id_solicitud": str(asignacion["id_solicitud"]),
            "id_auditor": str(asignacion["id_auditor"]),
            "auditor_nombre": info.get("nombre", ""),
            "auditor_correo": info.get("correo", ""),
            "rol_auditor": asignacion["especialidad"],
            "especialidad": asignacion["especialidad"],
            "fecha_inicio_planificada": None,
            "fecha_fin_planificada": None,
            "estado_asignacion": asignacion["estado_asignacion"],
            "mensaje": "Auditor asignado correctamente. La fecha y el horario se definirán desde Agenda.",
        }

    # ------------------------------------------------------------------
    # LISTAR ASIGNACIONES
    # ------------------------------------------------------------------
    async def listar_asignaciones(self, id_solicitud: UUID | None = None) -> list[dict]:
        condiciones = []
        parametros: dict = {}
        if id_solicitud:
            condiciones.append("a.id_solicitud = :id_solicitud")
            parametros["id_solicitud"] = str(id_solicitud)
        where = "WHERE " + " AND ".join(condiciones) if condiciones else ""

        resultado = await self.db.execute(
            text(
                f"""
                SELECT
                    a.id,
                    a.id_solicitud,
                    a.id_auditor,
                    a.especialidad,
                    a.declaracion,
                    COALESCE(agenda.fecha_inicio, a.fecha_inicio_planificada) AS fecha_inicio_planificada,
                    COALESCE(agenda.fecha_fin, a.fecha_fin_planificada) AS fecha_fin_planificada,
                    CASE WHEN agenda.id_programacion IS NOT NULL THEN TRUE ELSE FALSE END AS tiene_programacion,
                    agenda.estado AS estado_programacion,
                    a.estado_asignacion,
                    s.numero_radicado,
                    u.nombre AS auditor_nombre,
                    u.correo AS auditor_correo
                FROM auditores_solicitud a
                INNER JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                INNER JOIN usuario u ON u.id_usuario = a.id_auditor
                LEFT JOIN LATERAL (
                    SELECT pv.id_programacion, pv.fecha_inicio, pv.fecha_fin, pv.estado
                    FROM detalle_programacion_auditor dpa
                    INNER JOIN programacion_visita pv
                        ON pv.id_programacion = dpa.id_programacion
                    WHERE dpa.id_usuario = a.id_auditor
                      AND pv.id_solicitud = a.id_solicitud
                      AND COALESCE(pv.estado, '') NOT IN ('Cancelada', 'Cancelado')
                    ORDER BY pv.fecha_inicio DESC NULLS LAST
                    LIMIT 1
                ) agenda ON TRUE
                {where}
                ORDER BY COALESCE(agenda.fecha_inicio, a.fecha_inicio_planificada) DESC NULLS LAST, a.id DESC
                """
            ),
            parametros,
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def cancelar_asignacion(self, id_asignacion: UUID) -> dict:
        # Verifica si la solicitud ya tiene una programación de visita.
        solicitud_result = await self.db.execute(
            text(
                """
                SELECT a.id_solicitud
                FROM auditores_solicitud a
                WHERE a.id = :id
                LIMIT 1
                """
            ),
            {"id": str(id_asignacion)},
        )
        asignacion = solicitud_result.mappings().first()
        if not asignacion:
            raise HTTPException(status_code=404, detail="La asignación no existe.")

        programacion_result = await self.db.execute(
            text(
                """
                SELECT 1
                FROM programacion_visita
                WHERE id_solicitud = :id_solicitud
                  AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                LIMIT 1
                """
            ),
            {"id_solicitud": str(asignacion["id_solicitud"])},
        )
        if programacion_result.first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede cancelar la asignación porque la solicitud ya tiene una programación de visita.",
            )

        result = await self.db.execute(
            text(
                """
                UPDATE auditores_solicitud
                SET estado_asignacion = 'Cancelada'
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": str(id_asignacion)},
        )
        if not result.first():
            raise HTTPException(status_code=404, detail="La asignación no existe.")
        await self.db.commit()
        return {"mensaje": "Asignación cancelada correctamente."}
