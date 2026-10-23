from datetime import date, datetime, time, timedelta
import calendar
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from modules.solicitudes import estado_solicitud as estados
from modules.auditores.auditor_service import AuditorService
from modules.agenda_auditor.agenda_schema import (
    DisponibilidadEditar,
    DisponibilidadExtraordinariaCrear,
    DisponibilidadSemanalCrear,
    FechaNoDisponibleCrear,
    ProgramacionAuditoriaCrear,
    normalizar_dia,
)
from modules.asignacion_auditores.asignacion_service import (
    CTE_AUDITORES,
    ESTADOS_ASIGNACION_ACTIVOS,
)


class AgendaAuditorService(AuditorService):
    """Consulta y administra la agenda de auditorías de cada auditor."""

    ESTADOS_PROGRAMACION_ACTIVOS = ("Programada", "Confirmada", "Reprogramada")

    async def consultar_agenda(
        self,
        id_usuario: UUID,
        desde: date | None = None,
        hasta: date | None = None,
        tipo_registro: str | None = None,
        incluir_inactivos: bool = True,
    ):
        """Consulta registros de disponibilidad, incluidos bloqueos y vigencias."""
        filtros = ["id_usuario = :id_usuario"]
        params: dict = {"id_usuario": str(id_usuario)}
        if desde:
            filtros.append("(fecha_fin IS NULL OR CAST(fecha_fin AS DATE) >= :desde)")
            params["desde"] = desde
        if hasta:
            filtros.append("CAST(fecha_inicio AS DATE) <= :hasta")
            params["hasta"] = hasta
        if tipo_registro:
            filtros.append("LOWER(COALESCE(tipo_registro, '')) = LOWER(:tipo_registro)")
            params["tipo_registro"] = tipo_registro.strip()
        if not incluir_inactivos:
            filtros.append("UPPER(TRIM(COALESCE(estado, ''))) IN ('ACTIVO', 'ACTIVA')")

        result = await self.db.execute(
            text(f"""
                SELECT
                    id_disponibilidad,
                    tipo_registro,
                    dia_semana,
                    fecha_inicio,
                    fecha_fin,
                    hora_inicio,
                    hora_fin,
                    motivo,
                    estado
                FROM disponibilidad_auditor
                WHERE {' AND '.join(filtros)}
                ORDER BY fecha_inicio DESC NULLS LAST, dia_semana
            """),
            params,
        )
        return [dict(row) for row in result.mappings().all()]

    async def listar_auditores_activos(self):
        """Lista auditores activos/aprobados para administrar su agenda."""
        result = await self.db.execute(text("""
            SELECT u.id_usuario, u.nombre, u.correo, u.estado, u.estado_auditor, u.tipo_doc, u.num_doc,
                   (
                       SELECT a2.especialidad
                       FROM auditores_solicitud a2
                       WHERE a2.id_auditor = u.id_usuario
                         AND a2.especialidad IS NOT NULL
                         AND UPPER(TRIM(COALESCE(a2.estado_asignacion, ''))) IN ('AGENDADA', 'PROGRAMADA', 'CONFIRMADO')
                       ORDER BY a2.fecha_asignacion DESC NULLS LAST
                       LIMIT 1
                   ) AS rol_auditor
            FROM usuario u
            WHERE UPPER(TRIM(COALESCE(u.estado, ''))) = 'ACTIVO'
              AND UPPER(TRIM(COALESCE(u.estado_auditor, ''))) IN ('ACTIVO', 'APROBADO', 'APROBADA')
            ORDER BY u.nombre
        """))
        return [dict(row) for row in result.mappings().all()]

    async def listar_asignaciones_programables(self):
        """Retorna las solicitudes aprobadas con un auditor ya asignado."""
        return await self._listar_asignaciones_programables(None)

    async def listar_asignaciones_programables_auditor(self, id_usuario: UUID):
        """Retorna las solicitudes aprobadas asignadas a un auditor específico."""
        return await self._listar_asignaciones_programables(id_usuario)

    # ------------------------------------------------------------------
    # AUDITORES DISPONIBLES PARA UNA SEDE
    # ------------------------------------------------------------------
    async def listar_auditores_disponibles_para_sede(
        self,
        id_solicitud: UUID,
        id_sede: UUID | None = None,
        fecha: date | None = None,
        hora_inicio: time | None = None,
        hora_fin: time | None = None,
        *,
        page: int = 1,
        page_size: int = 12,
        buscar: str | None = None,
        ciudad: str | None = None,
        modalidad: str | None = None,
        competencia: str | None = None,
        conflicto: str | None = None,
    ) -> dict:
        """
        Lista los auditores que pueden asignarse a una sede concreta.

        Reutiliza las validaciones de "Asignación de Auditores" (competencia
        vigente en la norma y conflicto de interés) y añade las validaciones
        propias de la Agenda (disponibilidad activa y cruces de horario)
        cuando se informa la fecha/hora de la visita.

        Solo se devuelven los auditores realmente disponibles para la sede: los
        que ya tienen una auditoría programada, los que están asignados a otra
        sede y los que no cumplen las validaciones quedan excluidos.

        La lista no modifica ninguna asignación: solo informa qué auditores
        están disponibles para la sede seleccionada.
        """
        solicitud_result = await self.db.execute(
            text("""
                SELECT s.id_solicitud, s.id_empresa, s.id_norma, s.estado
                FROM solicitud s
                WHERE s.id_solicitud = :id_solicitud
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        solicitud = solicitud_result.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="La solicitud no existe.")
        if not solicitud.get("id_empresa") or not solicitud.get("id_norma"):
            return {
                "items": [],
                "page": 1,
                "page_size": page_size,
                "total": 0,
                "total_pages": 0,
                "total_candidatos": 0,
                "total_no_disponibles": 0,
            }

        page = max(1, page)
        page_size = min(100, max(1, page_size))
        buscar = (buscar or "").strip() or None
        ciudad = (ciudad or "").strip() or None
        modalidad = (modalidad or "").strip() or None
        competencia = (competencia or "").strip().lower() or None
        conflicto = (conflicto or "").strip().lower() or None
        if competencia not in (None, "si", "no"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El filtro competencia debe ser 'si' o 'no'.",
            )
        if conflicto not in (None, "si", "no"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El filtro conflicto debe ser 'si' o 'no'.",
            )

        params = {
            "id_solicitud": str(id_solicitud),
            "id_empresa": str(solicitud["id_empresa"]),
            "id_norma": str(solicitud["id_norma"]),
            "estados_activos": list(ESTADOS_ASIGNACION_ACTIVOS),
            "buscar": buscar,
            "ciudad": ciudad,
            "modalidad": modalidad,
            "competencia": competencia,
            "conflicto": conflicto,
        }
        # El equipo que ya está en la sede no se vuelve a ofrecer.
        if id_sede:
            params["id_sede"] = str(id_sede)
            sede_fragmento = """
                    EXISTS (
                        SELECT 1
                        FROM detalle_programacion_auditor d
                        INNER JOIN programacion_visita p
                            ON p.id_programacion = d.id_programacion
                        WHERE d.id_usuario = c.id_usuario
                          AND p.id_sede = :id_sede
                          AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                              ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                    ) AS ya_en_sede
            """
        else:
            sede_fragmento = """
                    EXISTS (
                        SELECT 1
                        FROM detalle_programacion_auditor d
                        INNER JOIN programacion_visita p
                            ON p.id_programacion = d.id_programacion
                        WHERE d.id_usuario = c.id_usuario
                          AND p.id_sede IS NULL
                          AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                              ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                    ) AS ya_en_sede
            """

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
        # Rol que el auditor ya tiene en la solicitud (si existe).
        rol_fragmento = """
                rol.especialidad AS rol_asignado
        """
        seleccion = (
            CTE_AUDITORES
            + " SELECT c.*, "
            + sede_fragmento
            + ", "
            + rol_fragmento
            + " FROM candidatos c "
            + " LEFT JOIN LATERAL ("
            + "     SELECT a.especialidad"
            + "     FROM auditores_solicitud a"
            + "     WHERE a.id_solicitud = :id_solicitud"
            + "       AND a.id_auditor = c.id_usuario"
            + "       AND UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) IN"
            + "           ('AGENDADA', 'PROGRAMADA', 'CONFIRMADO')"
            + "     ORDER BY a.id"
            + "     LIMIT 1"
            + " ) rol ON TRUE "
            + filtros
        )

        result = await self.db.execute(
            text(seleccion + " ORDER BY nombre ASC LIMIT :limite"),
            {**params, "limite": 500},
        )
        candidatos = [dict(fila) for fila in result.mappings().all()]

        # Rango horario a validar (opcional).
        inicio_consulta = datetime.combine(fecha, hora_inicio or time.min) if fecha else None
        fin_consulta = datetime.combine(fecha, hora_fin or time.max) if fecha else None

        # Validaciones de agenda aplicadas en bloque (disponibilidad y cruces).
        ids = [str(fila["id_usuario"]) for fila in candidatos]
        con_disponibilidad = await self._ids_con_disponibilidad(
            ids, fecha, hora_inicio, hora_fin
        ) if fecha is not None and ids else set()
        con_cruce = await self._ids_con_cruce(
            ids, inicio_consulta, fin_consulta
        ) if (fecha is not None and inicio_consulta and fin_consulta and ids) else {}

        disponibles = []
        no_disponibles = 0
        for fila in candidatos:
            id_usuario = str(fila["id_usuario"])
            competencia_norma = bool(fila["competencia_norma"])
            conflicto_interes = bool(fila["conflicto_interes"])
            ya_asignado = bool(fila["ya_asignado"])
            ya_en_sede = bool(fila.get("ya_en_sede"))
            disponible = None if fecha is None else (id_usuario in con_disponibilidad)
            cruce = con_cruce.get(id_usuario) if fecha is not None else None

            # Solo se ofrecen los auditores que pueden asignarse a la sede.
            if not competencia_norma or conflicto_interes or ya_en_sede:
                no_disponibles += 1
                continue
            if disponible is False or cruce:
                no_disponibles += 1
                continue

            disponibles.append({
                "id_usuario": id_usuario,
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
                "rol_auditor": fila.get("rol_asignado"),
                "competencia_norma": competencia_norma,
                "conflicto_interes": conflicto_interes,
                "ya_asignado": ya_asignado,
                "ya_en_sede": ya_en_sede,
                "disponible": disponible,
                "sin_cruce_horario": None if fecha is None else True,
                "conflicto_horario": None,
                "elegible": True,
                "motivo": (
                    "Auditor disponible para esta sede."
                    if fecha is not None
                    else "Auditor elegible para esta sede. La disponibilidad y los cruces "
                    "se validan al programar en Agenda."
                ),
            })

        total = len(disponibles)
        total_pages = (total + page_size - 1) // page_size
        if total_pages and page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size
        items = disponibles[offset:offset + page_size]

        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "total_candidatos": len(candidatos),
            "total_no_disponibles": no_disponibles,
        }

    async def _ids_con_disponibilidad(
        self,
        ids: list[str],
        fecha: date,
        hora_inicio: time | None,
        hora_fin: time | None,
    ) -> set[str]:
        """Auditores (del conjunto indicado) con disponibilidad activa para la fecha/hora."""
        if not ids:
            return set()
        dia_es = [
            "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
        ][fecha.weekday()]
        dia_numero = {
            "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
            "viernes": 5, "sabado": 6, "domingo": 7,
        }[normalizar_dia(dia_es)]
        tiene_horas = await self._tabla_tiene_columna("disponibilidad_auditor", "hora_inicio")
        disp_time_clause = (
            "AND (da.hora_inicio IS NULL OR da.hora_fin IS NULL "
            "OR (da.hora_inicio <= :hora_inicio AND da.hora_fin >= :hora_fin))"
            if tiene_horas else ""
        )
        bloqueo_time_clause = (
            "AND (nd.hora_inicio IS NULL OR nd.hora_fin IS NULL "
            "OR (nd.hora_inicio < :hora_fin AND nd.hora_fin > :hora_inicio))"
            if tiene_horas else ""
        )
        params = {
            "ids": ids,
            "fecha": fecha,
            "dia_numero": dia_numero,
        }
        if tiene_horas:
            params["hora_inicio"] = hora_inicio or time.min
            params["hora_fin"] = hora_fin or time.max
        result = await self.db.execute(text(f"""
            SELECT DISTINCT da.id_usuario
            FROM disponibilidad_auditor da
            WHERE da.id_usuario = ANY(CAST(:ids AS UUID[]))
              AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
              AND CAST(da.fecha_inicio AS DATE) <= :fecha
              AND (da.fecha_fin IS NULL OR CAST(da.fecha_fin AS DATE) >= :fecha)
              AND (
                  da.dia_semana IS NULL
                  OR da.dia_semana = :dia_numero
                  OR (:dia_numero = 7 AND da.dia_semana = 0)
              )
              AND LOWER(TRIM(COALESCE(da.tipo_registro, ''))) IN
                  ('disponible', 'disponibilidad', 'horario disponible', 'availability', 'semanal', 'disponibilidad extra', 'disponibilidad_extra')
              {disp_time_clause}
              AND NOT EXISTS (
                  SELECT 1
                  FROM disponibilidad_auditor nd
                  WHERE nd.id_usuario = da.id_usuario
                    AND UPPER(TRIM(COALESCE(nd.estado, ''))) IN ('ACTIVO', 'ACTIVA')
                    AND LOWER(TRIM(COALESCE(nd.tipo_registro, ''))) IN
                        ('no disponible', 'no_disponible', 'indisponible', 'bloqueo', 'bloqueo fecha')
                    AND CAST(nd.fecha_inicio AS DATE) <= :fecha
                    AND (nd.fecha_fin IS NULL OR CAST(nd.fecha_fin AS DATE) >= :fecha)
                    {bloqueo_time_clause}
              )
        """), params)
        return {str(fila["id_usuario"]) for fila in result.mappings().all()}

    async def _ids_con_cruce(
        self,
        ids: list[str],
        inicio: datetime,
        fin: datetime,
    ) -> dict[str, dict]:
        """Auditores (del conjunto indicado) que ya tienen una auditoría en ese horario."""
        if not ids:
            return {}
        result = await self.db.execute(text("""
            SELECT x.id_usuario, c.id_programacion, c.fecha_inicio, c.fecha_fin,
                   c.empresa_nombre, c.direccion_servicio
            FROM (
                SELECT DISTINCT d.id_usuario
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                WHERE d.id_usuario = ANY(CAST(:ids AS UUID[]))
                  AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                  AND p.fecha_inicio < :fecha_fin
                  AND p.fecha_fin > :fecha_inicio
            ) x
            LEFT JOIN LATERAL (
                SELECT p2.id_programacion, p2.fecha_inicio, p2.fecha_fin, p2.estado,
                       e2.direccion AS direccion_servicio, e2.nombre AS empresa_nombre
                FROM detalle_programacion_auditor d2
                INNER JOIN programacion_visita p2
                    ON p2.id_programacion = d2.id_programacion
                LEFT JOIN solicitud s2
                    ON s2.id_solicitud = p2.id_solicitud
                LEFT JOIN empresa e2
                    ON e2.id_empresa = s2.id_empresa
                WHERE d2.id_usuario = x.id_usuario
                  AND UPPER(TRIM(COALESCE(p2.estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                  AND p2.fecha_inicio < :fecha_fin
                  AND p2.fecha_fin > :fecha_inicio
                ORDER BY p2.fecha_inicio
                LIMIT 1
            ) c ON TRUE
        """), {
            "ids": ids,
            "fecha_inicio": inicio,
            "fecha_fin": fin,
        })
        return {
            str(fila["id_usuario"]): {
                "id_programacion": fila["id_programacion"],
                "fecha_inicio": fila["fecha_inicio"],
                "fecha_fin": fila["fecha_fin"],
                "empresa_nombre": fila["empresa_nombre"],
                "direccion_servicio": fila["direccion_servicio"],
            }
            for fila in result.mappings().all()
        }

    async def _listar_asignaciones_programables(self, id_usuario: UUID | None):
        filtros = [
            # Contra el catalogo de M5: 'APROBADO' exacto dejaba fuera a las
            # solicitudes guardadas como 'Aprobada'.
            f"s.estado = '{estados.APROBADA}'",
            "UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) IN ('AGENDADA', 'PROGRAMADA', 'CONFIRMADO')",
            "UPPER(TRIM(COALESCE(u.estado, ''))) = 'ACTIVO'",
            "UPPER(TRIM(COALESCE(u.estado_auditor, ''))) IN ('ACTIVO', 'APROBADO', 'APROBADA')",
        ]
        params = {}
        if id_usuario:
            filtros.append("a.id_auditor = :id_usuario")
            params["id_usuario"] = str(id_usuario)
        result = await self.db.execute(
            text(f"""
                SELECT
                    s.id_solicitud,
                    s.id_empresa,
                    s.numero_radicado,
                    s.estado AS estado_solicitud,
                    e.nombre AS empresa_nombre,
                    e.nit AS empresa_nit,
                    e.direccion AS empresa_direccion,
                    e.ciudad AS empresa_ciudad,
                    a.id_auditor AS id_usuario,
                    u.nombre AS auditor_nombre,
                    u.correo AS auditor_correo,
                    u.tipo_doc AS auditor_tipo_doc,
                    u.num_doc AS auditor_num_doc,
                    a.especialidad AS rol_auditor,
                    a.estado_asignacion
                FROM auditores_solicitud a
                INNER JOIN solicitud s
                    ON s.id_solicitud = a.id_solicitud
                INNER JOIN usuario u
                    ON u.id_usuario = a.id_auditor
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                WHERE {' AND '.join(filtros)}
                ORDER BY e.nombre, s.numero_radicado, u.nombre
            """),
            params,
        )
        return [dict(fila) for fila in result.mappings().all()]

    async def listar_todas_programaciones(
        self,
        desde: date | None = None,
        hasta: date | None = None,
        ciudad: str | None = None,
        modalidad: str | None = None,
        estado: str | None = None,
    ):
        filtros = []
        params: dict = {}
        if desde:
            filtros.append("p.fecha_fin >= :desde")
            params["desde"] = datetime.combine(desde, time.min)
        if hasta:
            filtros.append("p.fecha_inicio <= :hasta")
            params["hasta"] = datetime.combine(hasta, time.max)
        if ciudad and ciudad.strip():
            filtros.append("LOWER(COALESCE(p.ciudad_servicio, '')) LIKE :ciudad")
            params["ciudad"] = f"%{ciudad.strip().lower()}%"
        if modalidad and modalidad.strip():
            filtros.append("LOWER(COALESCE(p.modalidad, '')) = LOWER(:modalidad)")
            params["modalidad"] = modalidad.strip()
        if estado and estado.strip():
            filtros.append("UPPER(TRIM(COALESCE(p.estado, ''))) = UPPER(:estado)")
            params["estado"] = estado.strip()

        where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
        result = await self.db.execute(
            text(f"""
                SELECT
                    d.id_detalle,
                    d.id_programacion,
                    d.id_usuario,
                    d.rol_auditor,
                    d.horas_asignadas,
                    COALESCE(d.confirmado, FALSE) AS auditor_confirmado,
                    d.fecha_confirmacion,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dc
                        WHERE dc.id_programacion = p.id_programacion
                          AND COALESCE(dc.confirmado, FALSE) = TRUE
                    ) AS auditores_confirmados,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dt
                        WHERE dt.id_programacion = p.id_programacion
                    ) AS auditores_total,
                    p.id_solicitud,
                    s.numero_radicado,
                    e.nombre AS empresa_nombre,
                    e.direccion AS empresa_direccion,
                    e.ciudad AS empresa_ciudad,
                    u.nombre AS auditor_nombre,
                    u.correo AS auditor_correo,
                    u.tipo_doc AS auditor_tipo_doc,
                    u.num_doc AS auditor_num_doc,
                    p.direccion_servicio,
                    p.id_sede,
                    p.fecha_inicio,
                    p.fecha_fin,
                    p.modalidad,
                    p.ciudad_servicio,
                    p.estado,
                    p.notificacion_enviada,
                    p.motivo_reprogramacion,
                    p.motivo_cancelacion,
                    bloq.id_disponibilidad AS bloqueo_id,
                    bloq.motivo AS bloqueo_motivo,
                    (bloq.id_disponibilidad IS NOT NULL) AS dia_no_disponible,
                    p.estado_solicitud_reprogramacion,
                    p.motivo_solicitud_reprogramacion,
                    CASE
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'RECHAZADA'
                            THEN 'Reprogramación rechazada' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'APROBADA'
                            THEN 'Reprogramación resuelta' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        ELSE p.motivo_reprogramacion
                    END AS observacion_auditor,
                    p.id_usuario_solicitante_reprogramacion,
                    (SELECT u2.nombre FROM usuario u2
                      WHERE u2.id_usuario = p.id_usuario_solicitante_reprogramacion) AS solicitante_nombre,
                    (SELECT u2.correo FROM usuario u2
                      WHERE u2.id_usuario = p.id_usuario_solicitante_reprogramacion) AS solicitante_correo
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN usuario u
                    ON u.id_usuario = d.id_usuario
                LEFT JOIN LATERAL (
                    SELECT da.id_disponibilidad, da.motivo
                    FROM disponibilidad_auditor da
                    WHERE da.id_usuario = d.id_usuario
                      AND da.tipo_registro = 'Bloqueo Fecha'
                      AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
                      AND CAST(da.fecha_inicio AS DATE) <= CAST(p.fecha_fin AS DATE)
                      AND CAST(COALESCE(da.fecha_fin, da.fecha_inicio) AS DATE) >= CAST(p.fecha_inicio AS DATE)
                    ORDER BY da.fecha_inicio DESC
                    LIMIT 1
                ) bloq ON TRUE
                {where}
                ORDER BY p.fecha_inicio DESC
            """),
            params,
        )
        return [dict(row) for row in result.mappings().all()]

    # ------------------------------------------------------------------
    # PROGRAMACIONES FUTURAS
    # ------------------------------------------------------------------
    async def listar_programaciones_futuras(
        self,
        dias: int = 7,
        id_usuario: UUID | None = None,
        estado: str | None = None,
        ciudad: str | None = None,
        modalidad: str | None = None,
    ) -> list[dict]:
        """
        Programaciones con fecha de inicio igual o superior a hoy + `dias`.

        Si se indica `id_usuario` solo se devuelven las programaciones en las
        que ese auditor está asignado (alcance propio del auditor). La
        consulta usa siempre las fechas reales registradas en el sistema.

        Solo se devuelven las programaciones vigentes: las canceladas o ya
        ejecutadas quedan excluidas del listado.
        """
        filtros = [
            "CAST(p.fecha_inicio AS DATE) >= (CURRENT_DATE + CAST(:dias AS INTEGER))",
            # Se excluyen las programaciones cerradas (canceladas o ejecutadas).
            "UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'EJECUTADA', 'EJECUTADO')",
        ]
        params: dict = {"dias": int(dias)}
        if id_usuario:
            filtros.append("d.id_usuario = :id_usuario")
            params["id_usuario"] = str(id_usuario)
        if estado and estado.strip():
            filtros.append("UPPER(TRIM(COALESCE(p.estado, ''))) = UPPER(:estado)")
            params["estado"] = estado.strip()
        if ciudad and ciudad.strip():
            filtros.append("LOWER(COALESCE(p.ciudad_servicio, '')) LIKE :ciudad")
            params["ciudad"] = f"%{ciudad.strip().lower()}%"
        if modalidad and modalidad.strip():
            filtros.append("LOWER(COALESCE(p.modalidad, '')) = LOWER(:modalidad)")
            params["modalidad"] = modalidad.strip()

        result = await self.db.execute(
            text(f"""
                SELECT
                    p.id_programacion,
                    p.id_solicitud,
                    s.numero_radicado,
                    s.estado AS estado_solicitud,
                    e.nombre AS empresa_nombre,
                    e.nit AS empresa_nit,
                    p.id_sede,
                    se.nombre_sede,
                    p.direccion_servicio,
                    p.ciudad_servicio,
                    p.fecha_inicio,
                    p.fecha_fin,
                    p.modalidad,
                    p.estado,
                    p.notificacion_enviada,
                    p.estado_solicitud_reprogramacion,
                    p.motivo_solicitud_reprogramacion,
                    CASE
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'RECHAZADA'
                            THEN 'Reprogramación rechazada' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'APROBADA'
                            THEN 'Reprogramación resuelta' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        ELSE p.motivo_reprogramacion
                    END AS observacion_auditor,
                    d.id_usuario,
                    d.rol_auditor,
                    d.horas_asignadas,
                    COALESCE(d.confirmado, FALSE) AS auditor_confirmado,
                    d.fecha_confirmacion,
                    u.nombre AS auditor_nombre,
                    u.correo AS auditor_correo,
                    u.tipo_doc AS auditor_tipo_doc,
                    u.num_doc AS auditor_num_doc,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dt
                        WHERE dt.id_programacion = p.id_programacion
                    ) AS auditores_total,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dc
                        WHERE dc.id_programacion = p.id_programacion
                          AND COALESCE(dc.confirmado, FALSE) = TRUE
                    ) AS auditores_confirmados
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN sede_empresa se
                    ON se.id_sede = p.id_sede
                LEFT JOIN usuario u
                    ON u.id_usuario = d.id_usuario
                WHERE {' AND '.join(filtros)}
                ORDER BY p.fecha_inicio ASC, u.nombre ASC
            """),
            params,
        )
        return [dict(fila) for fila in result.mappings().all()]

    async def consultar_detalle_programacion(self, id_programacion: UUID) -> dict:
        """Detalle completo de una programación: solicitud, empresa, sede y auditores."""
        result = await self.db.execute(
            text("""
                SELECT
                    p.id_programacion,
                    p.id_solicitud,
                    p.id_empresa,
                    p.id_sede,
                    p.fecha_inicio,
                    p.fecha_fin,
                    p.modalidad,
                    p.estado,
                    p.direccion_servicio,
                    p.ciudad_servicio,
                    p.notificacion_enviada,
                    p.anio_ciclo,
                    p.motivo_reprogramacion,
                    p.motivo_cancelacion,
                    p.estado_solicitud_reprogramacion,
                    p.motivo_solicitud_reprogramacion,
                    s.numero_radicado,
                    s.estado AS estado_solicitud,
                    s.fecha AS fecha_solicitud,
                    s.alcance_certificacion,
                    s.numero_empleados,
                    s.numero_sedes,
                    s.persona_contacto,
                    s.observaciones AS observaciones_solicitud,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version,
                    e.nombre AS empresa_nombre,
                    e.nit AS empresa_nit,
                    e.direccion AS empresa_direccion,
                    e.ciudad AS empresa_ciudad,
                    e.correo AS empresa_correo,
                    e.estado AS empresa_estado,
                    se.nombre_sede,
                    se.direccion AS sede_direccion,
                    se.ciudad AS sede_ciudad,
                    se.departamento AS sede_departamento,
                    se.pais AS sede_pais,
                    se.es_principal AS sede_es_principal
                FROM programacion_visita p
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n
                    ON n.id_norma = s.id_norma
                LEFT JOIN sede_empresa se
                    ON se.id_sede = p.id_sede
                WHERE p.id_programacion = :id_programacion
            """),
            {"id_programacion": str(id_programacion)},
        )
        fila = result.mappings().first()
        if not fila:
            raise HTTPException(status_code=404, detail="La programación no existe.")
        programacion = dict(fila)

        auditores_result = await self.db.execute(
            text("""
                SELECT
                    d.id_usuario,
                    d.rol_auditor,
                    d.horas_asignadas,
                    COALESCE(d.confirmado, FALSE) AS confirmado,
                    d.fecha_confirmacion,
                    u.nombre,
                    u.correo,
                    u.tipo_doc,
                    u.num_doc,
                    u.estado AS estado_usuario,
                    u.estado_auditor,
                    pr.ciudad_residencia,
                    pr.departamento_residencia,
                    pr.modalidad_preferida
                FROM detalle_programacion_auditor d
                INNER JOIN usuario u
                    ON u.id_usuario = d.id_usuario
                LEFT JOIN LATERAL (
                    SELECT p2.ciudad_residencia, p2.departamento_residencia, p2.modalidad_preferida
                    FROM perfil_auditor p2
                    WHERE p2.id_usuario = u.id_usuario
                    ORDER BY p2.id_postulacion DESC
                    LIMIT 1
                ) pr ON TRUE
                WHERE d.id_programacion = :id_programacion
                ORDER BY u.nombre ASC
            """),
            {"id_programacion": str(id_programacion)},
        )
        auditores = [dict(item) for item in auditores_result.mappings().all()]

        return {
            "programacion": programacion,
            "auditores": auditores,
        }

    async def consultar_auditorias_programadas(
        self,
        id_usuario: UUID,
        desde: date | None = None,
        hasta: date | None = None,
        ciudad: str | None = None,
        modalidad: str | None = None,
    ):
        filtros = ["d.id_usuario = :id_usuario"]
        params: dict = {"id_usuario": str(id_usuario)}
        if desde:
            filtros.append("p.fecha_fin >= :desde")
            params["desde"] = datetime.combine(desde, time.min)
        if hasta:
            filtros.append("p.fecha_inicio <= :hasta")
            params["hasta"] = datetime.combine(hasta, time.max)
        if ciudad and ciudad.strip():
            filtros.append("LOWER(COALESCE(p.ciudad_servicio, '')) LIKE :ciudad")
            params["ciudad"] = f"%{ciudad.strip().lower()}%"
        if modalidad and modalidad.strip():
            filtros.append("LOWER(COALESCE(p.modalidad, '')) = LOWER(:modalidad)")
            params["modalidad"] = modalidad.strip()

        result = await self.db.execute(
            text(f"""
                SELECT
                    d.id_detalle,
                    d.id_programacion,
                    d.id_usuario,
                    d.rol_auditor,
                    d.horas_asignadas,
                    COALESCE(d.confirmado, FALSE) AS auditor_confirmado,
                    d.fecha_confirmacion,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dc
                        WHERE dc.id_programacion = p.id_programacion
                          AND COALESCE(dc.confirmado, FALSE) = TRUE
                    ) AS auditores_confirmados,
                    (
                        SELECT COUNT(*) FROM detalle_programacion_auditor dt
                        WHERE dt.id_programacion = p.id_programacion
                    ) AS auditores_total,
                    p.id_solicitud,
                    s.numero_radicado,
                    e.nombre AS empresa_nombre,
                    e.direccion AS direccion_servicio,
                    p.id_sede,
                    p.fecha_inicio,
                    p.fecha_fin,
                    p.modalidad,
                    p.ciudad_servicio,
                    p.estado,
                    p.notificacion_enviada,
                    p.motivo_reprogramacion,
                    p.motivo_cancelacion,
                    p.estado_solicitud_reprogramacion,
                    p.motivo_solicitud_reprogramacion,
                    CASE
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'RECHAZADA'
                            THEN 'Reprogramación rechazada' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        WHEN UPPER(TRIM(COALESCE(p.estado_solicitud_reprogramacion, ''))) = 'APROBADA'
                            THEN 'Reprogramación resuelta' || CASE
                                WHEN p.motivo_solicitud_reprogramacion IS NOT NULL
                                    THEN ': ' || p.motivo_solicitud_reprogramacion
                                ELSE '' END
                        ELSE p.motivo_reprogramacion
                    END AS observacion_auditor,
                    bloq.id_disponibilidad AS bloqueo_id,
                    bloq.motivo AS bloqueo_motivo,
                    (bloq.id_disponibilidad IS NOT NULL) AS dia_no_disponible
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN LATERAL (
                    SELECT da.id_disponibilidad, da.motivo
                    FROM disponibilidad_auditor da
                    WHERE da.id_usuario = d.id_usuario
                      AND da.tipo_registro = 'Bloqueo Fecha'
                      AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
                      AND CAST(da.fecha_inicio AS DATE) <= CAST(p.fecha_fin AS DATE)
                      AND CAST(COALESCE(da.fecha_fin, da.fecha_inicio) AS DATE) >= CAST(p.fecha_inicio AS DATE)
                    ORDER BY da.fecha_inicio DESC
                    LIMIT 1
                ) bloq ON TRUE
                WHERE {' AND '.join(filtros)}
                ORDER BY p.fecha_inicio DESC
            """),
            params,
        )
        return [dict(row) for row in result.mappings().all()]

    async def consultar_disponibilidad(
        self,
        id_usuario: UUID,
        fecha: date,
        hora_inicio: datetime,
        hora_fin: datetime,
    ) -> dict:
        if hora_fin <= hora_inicio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La hora final debe ser posterior a la hora inicial.",
            )
        if hora_inicio.date() != fecha or hora_fin.date() != fecha:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El intervalo consultado debe corresponder a la fecha seleccionada.",
            )

        auditor = await self.db.execute(text("""
            SELECT estado, estado_auditor
            FROM usuario
            WHERE id_usuario = :id_usuario
        """), {"id_usuario": str(id_usuario)})
        auditor = auditor.mappings().first()
        if not auditor:
            raise HTTPException(status_code=404, detail="El auditor no existe.")
        if str(auditor["estado"] or "").strip().upper() != "ACTIVO" or str(
            auditor["estado_auditor"] or ""
        ).strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
            return {"disponible": False, "motivo": "El auditor no está activo/aprobado."}

        tiene_disponibilidad = await self._tiene_disponibilidad_fecha(
            id_usuario, fecha, hora_inicio.time(), hora_fin.time()
        )
        if not tiene_disponibilidad:
            return {
                "disponible": False,
                "motivo": "El auditor no tiene un intervalo de disponibilidad que cubra la fecha y las horas indicadas, o registró ese día como no disponible.",
            }

        cruce = await self._buscar_cruce(id_usuario, hora_inicio, hora_fin)
        if cruce:
            return {
                "disponible": False,
                "motivo": "El auditor tiene otra auditoría en ese intervalo.",
                "conflicto": cruce,
            }
        return {"disponible": True, "motivo": "El auditor está disponible en el intervalo."}

    def _normalizar_rol_agenda(self, rol: str | None) -> str:
        valor = (rol or "").strip()
        mapeo = {
            "Auditor líder": "Auditor Líder",
            "Auditor Líder": "Auditor Líder",
            "Experto técnicos": "Auditor Técnico",
            "Experto técnico": "Auditor Técnico",
            "Auditor Técnico": "Auditor Técnico",
            "Auditor integral": "Auditor Técnico",
            "Observador": "Observador",
        }
        return mapeo.get(valor, "Auditor Técnico")

    async def _tabla_existe(self, tabla: str) -> bool:
        result = await self.db.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_name = :tabla
        """), {"tabla": tabla})
        return result.scalar() is not None

    async def _tabla_tiene_columna(self, tabla: str, columna: str) -> bool:
        result = await self.db.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = :tabla AND column_name = :columna
        """), {"tabla": tabla, "columna": columna})
        return result.scalar() is not None

    async def _programacion_tiene_columna(self, columna: str) -> bool:
        return await self._tabla_tiene_columna("programacion_visita", columna)

    async def _tiene_disponibilidad_fecha(
        self,
        id_usuario: UUID,
        fecha: date,
        hora_inicio: time | None = None,
        hora_fin: time | None = None,
    ) -> bool:
        """Verifica disponibilidad activa para el día y, si existen las columnas, sus horas."""
        dia_es = [
            "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
        ][fecha.weekday()]
        dia_normalizado = normalizar_dia(dia_es)
        dia_numero = {
            "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
            "viernes": 5, "sabado": 6, "domingo": 7,
        }[dia_normalizado]
        hora_inicio_consulta = hora_inicio or time.min
        hora_fin_consulta = hora_fin or time.max

        tiene_horas = await self._tabla_tiene_columna("disponibilidad_auditor", "hora_inicio")

        disp_time_clause = "AND (da.hora_inicio IS NULL OR da.hora_fin IS NULL OR (da.hora_inicio <= :hora_inicio AND da.hora_fin >= :hora_fin))" if tiene_horas else ""
        bloqueo_time_clause = "AND (nd.hora_inicio IS NULL OR nd.hora_fin IS NULL OR (nd.hora_inicio < :hora_fin AND nd.hora_fin > :hora_inicio))" if tiene_horas else ""

        sql = f"""
            SELECT EXISTS (
                SELECT 1
                FROM disponibilidad_auditor da
                WHERE da.id_usuario = :id_usuario
                  AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
                  AND CAST(da.fecha_inicio AS DATE) <= :fecha
                  AND (da.fecha_fin IS NULL OR CAST(da.fecha_fin AS DATE) >= :fecha)
                  AND (
                      da.dia_semana IS NULL
                      OR da.dia_semana = :dia_numero
                      OR (:dia_numero = 7 AND da.dia_semana = 0)
                  )
                  AND LOWER(TRIM(COALESCE(da.tipo_registro, ''))) IN
                      ('disponible', 'disponibilidad', 'horario disponible', 'availability', 'semanal', 'disponibilidad extra', 'disponibilidad_extra')
                  {disp_time_clause}
            )
            AND NOT EXISTS (
                SELECT 1
                FROM disponibilidad_auditor nd
                WHERE nd.id_usuario = :id_usuario
                  AND UPPER(TRIM(COALESCE(nd.estado, ''))) IN ('ACTIVO', 'ACTIVA')
                  AND LOWER(TRIM(COALESCE(nd.tipo_registro, ''))) IN
                      ('no disponible', 'no_disponible', 'indisponible', 'bloqueo', 'bloqueo fecha')
                  AND CAST(nd.fecha_inicio AS DATE) <= :fecha
                  AND (nd.fecha_fin IS NULL OR CAST(nd.fecha_fin AS DATE) >= :fecha)
                  {bloqueo_time_clause}
            )
        """
        params = {
            "id_usuario": str(id_usuario),
            "fecha": fecha,
            "dia_numero": dia_numero,
        }
        if tiene_horas:
            params["hora_inicio"] = hora_inicio_consulta
            params["hora_fin"] = hora_fin_consulta
        result = await self.db.execute(text(sql), params)
        return bool(result.scalar())

    async def _validar_sede_disponible(
        self,
        id_solicitud: UUID,
        id_sede: UUID | None,
        fecha_inicio: datetime,
        fecha_fin: datetime,
        excluir_programacion: UUID | None = None,
    ) -> None:
        """
        Impide programar una sede que ya tiene una visita vigente.

        La programacion anterior debe cancelarse para poder reutilizar la sede.
        """
        params = {
            "id_solicitud": str(id_solicitud),
            "id_sede": str(id_sede) if id_sede else None,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "excluir": str(excluir_programacion) if excluir_programacion else None,
        }
        result = await self.db.execute(text("""
            SELECT p.id_programacion, p.fecha_inicio, p.fecha_fin, p.estado,
                   s.numero_radicado
            FROM programacion_visita p
            LEFT JOIN solicitud s ON s.id_solicitud = p.id_solicitud
            WHERE UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                  ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
              AND (CAST(:id_sede AS UUID) IS NULL AND p.id_sede IS NULL
                   OR p.id_sede = CAST(:id_sede AS UUID))
              AND (CAST(:excluir AS UUID) IS NULL OR p.id_programacion <> CAST(:excluir AS UUID))
            ORDER BY p.fecha_inicio
            LIMIT 1
        """), params)
        conflicto = result.mappings().first()
        if not conflicto:
            return
        nombre_sede = "la dirección principal de la empresa" if not id_sede else "la sede seleccionada"
        raise HTTPException(
            status_code=409,
            detail=(
                f"No se puede programar: {nombre_sede} ya tiene una visita vigente "
                f"({conflicto['numero_radicado'] or 'otra solicitud'}) el "
                f"{conflicto['fecha_inicio'].strftime('%d/%m/%Y')}. "
                "Cancela esa programación para poder utilizar la sede."
            ),
        )

    async def _buscar_cruce(
        self,
        id_usuario: UUID,
        fecha_inicio: datetime,
        fecha_fin: datetime,
        excluir_programacion: UUID | None = None,
    ):
        result = await self.db.execute(
            text("""
                SELECT
                    p.id_programacion,
                    p.fecha_inicio,
                    p.fecha_fin,
                    p.estado,
                    e.direccion AS direccion_servicio,
                    e.nombre AS empresa_nombre
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                WHERE d.id_usuario = :id_usuario
                  AND UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                  AND p.fecha_inicio < :fecha_fin
                  AND p.fecha_fin > :fecha_inicio
                  AND (CAST(:excluir AS UUID) IS NULL OR p.id_programacion <> CAST(:excluir AS UUID))
                ORDER BY p.fecha_inicio
                LIMIT 1
            """),
            {
                "id_usuario": str(id_usuario),
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "excluir": str(excluir_programacion) if excluir_programacion else None,
            },
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _registrar_asignacion_auditor(
        self,
        id_solicitud: UUID,
        id_usuario: UUID,
        rol_auditor: str | None,
    ) -> None:
        """
        Registra la asignación de un auditor que se incorpora al equipo de
        una sede concreta. Solo crea registros nuevos: nunca modifica las
        asignaciones que ya existen para la solicitud.
        """
        await self.db.execute(
            text("""
                INSERT INTO auditores_solicitud (
                    id, id_solicitud, id_auditor, especialidad, declaracion,
                    fecha_inicio_planificada, fecha_fin_planificada, estado_asignacion
                ) VALUES (
                    :id, :id_solicitud, :id_auditor, :especialidad, TRUE,
                    NULL, NULL, :estado_asignacion
                )
            """),
            {
                "id": str(uuid4()),
                "id_solicitud": str(id_solicitud),
                "id_auditor": str(id_usuario),
                "especialidad": self._normalizar_rol_agenda(rol_auditor),
                "estado_asignacion": "Agendada",
            },
        )

    async def crear_programacion(self, data: ProgramacionAuditoriaCrear) -> dict:
        """Crea la programación, las relaciones con cada auditor y sus notificaciones en una transacción."""
        id_programacion = uuid4()
        fecha_programacion = data.fecha_inicio.date()

        auditores_list = data.auditores or []
        if not auditores_list:
            raise HTTPException(status_code=422, detail="Debe indicar al menos un auditor.")

        try:
            # Valida la solicitud una sola vez.
            solicitud_result = await self.db.execute(
                text("""
                    SELECT s.id_solicitud, s.estado, s.id_empresa
                    FROM solicitud s
                    WHERE s.id_solicitud = :id_solicitud
                    FOR SHARE
                """),
                {"id_solicitud": str(data.id_solicitud)},
            )
            solicitud = solicitud_result.mappings().first()
            if not solicitud:
                raise HTTPException(status_code=404, detail="La solicitud no existe.")
            if str(solicitud["estado"] or "").strip().upper() != "APROBADO":
                raise HTTPException(status_code=409, detail="Solo se puede programar una solicitud aprobada.")

            # Una sede no puede recibir dos visitas vigentes: si ya tiene una
            # programacion activa se rechaza hasta que se cancele esa.
            await self._validar_sede_disponible(
                data.id_solicitud,
                data.id_sede,
                data.fecha_inicio,
                data.fecha_fin,
            )

            # Valida cada auditor y su asignación.
            auditores_ok = []
            for aud in auditores_list:
                id_usuario = aud.id_usuario
                rol_solicitado = aud.rol_auditor

                auditor_result = await self.db.execute(
                    text("""
                        SELECT id_usuario, estado, estado_auditor
                        FROM usuario
                        WHERE id_usuario = :id_usuario
                        FOR UPDATE
                    """),
                    {"id_usuario": str(id_usuario)},
                )
                auditor = auditor_result.mappings().first()
                if not auditor:
                    raise HTTPException(status_code=404, detail=f"El auditor {id_usuario} no existe.")
                if str(auditor["estado"] or "").strip().upper() != "ACTIVO":
                    raise HTTPException(status_code=409, detail=f"El auditor {id_usuario} fue desactivado y no puede programarse.")
                if str(auditor["estado_auditor"] or "").strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
                    raise HTTPException(status_code=409, detail=f"El auditor {id_usuario} no se encuentra aprobado/activo.")

                asignacion_result = await self.db.execute(
                    text("""
                        SELECT especialidad, estado_asignacion
                        FROM auditores_solicitud
                        WHERE id_solicitud = :id_solicitud
                          AND id_auditor = :id_usuario
                          AND UPPER(TRIM(COALESCE(estado_asignacion, ''))) IN ('AGENDADA', 'PROGRAMADA', 'CONFIRMADO')
                        LIMIT 1
                    """),
                    {"id_solicitud": str(data.id_solicitud), "id_usuario": str(id_usuario)},
                )
                asignacion = asignacion_result.mappings().first()
                if not asignacion:
                    # Flujo "Mostrar más auditores disponibles": el auditor se
                    # incorpora al equipo de esta sede y se registra su
                    # asignación. No se modifican las asignaciones existentes.
                    if not data.asignar_auditores_adicionales:
                        raise HTTPException(
                            status_code=409,
                            detail=f"El auditor {id_usuario} debe estar asignado a esta solicitud antes de programar la visita.",
                        )
                    await self._registrar_asignacion_auditor(
                        id_solicitud=data.id_solicitud,
                        id_usuario=id_usuario,
                        rol_auditor=rol_solicitado,
                    )
                    asignacion = {"especialidad": rol_solicitado, "estado_asignacion": "Agendada"}

                tiene_disponibilidad = await self._tiene_disponibilidad_fecha(
                    id_usuario, fecha_programacion, data.fecha_inicio.time(), data.fecha_fin.time()
                )
                if not tiene_disponibilidad:
                    raise HTTPException(
                        status_code=409,
                        detail=f"El auditor {id_usuario} no tiene disponibilidad activa para la fecha seleccionada.",
                    )

                cruce = await self._buscar_cruce(id_usuario, data.fecha_inicio, data.fecha_fin)
                if cruce:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "mensaje": f"El auditor {id_usuario} ya tiene otra auditoría en ese horario.",
                            "conflicto": cruce,
                        },
                    )

                rol_final = rol_solicitado or (asignacion.get("especialidad") if isinstance(asignacion, dict) else asignacion["especialidad"]) or "Auditor"
                auditores_ok.append((id_usuario, rol_final))

            duracion_horas = Decimal(str((data.fecha_fin - data.fecha_inicio).total_seconds() / 3600))
            nombre_empresa = await self._nombre_empresa(data.id_solicitud)

            # La dirección y ciudad provienen de la empresa/sede: no se modifican manualmente.
            empresa_result = await self.db.execute(
                text("""
                    SELECT direccion, ciudad FROM empresa
                    WHERE id_empresa = :id_empresa
                """),
                {"id_empresa": str(solicitud["id_empresa"])},
            )
            empresa = empresa_result.mappings().first() or {}
            direccion_empresa = str((empresa.get("direccion") if isinstance(empresa, dict) else empresa["direccion"])).strip()
            ciudad_empresa = str((empresa.get("ciudad") if isinstance(empresa, dict) else empresa["ciudad"])).strip()

            if data.id_sede:
                sede_result = await self.db.execute(
                    text("""
                        SELECT direccion, ciudad, nombre_sede
                        FROM sede_empresa
                        WHERE id_sede = :id_sede
                    """),
                    {"id_sede": str(data.id_sede)},
                )
                sede = sede_result.mappings().first()
                if not sede:
                    raise HTTPException(status_code=404, detail="La sede seleccionada no existe.")
                sede_direccion = str((sede.get("direccion") if isinstance(sede, dict) else sede["direccion"])).strip()
                sede_ciudad = str((sede.get("ciudad") if isinstance(sede, dict) else sede["ciudad"])).strip()
                if sede_direccion:
                    direccion_empresa = sede_direccion
                if sede_ciudad:
                    ciudad_empresa = sede_ciudad

            if not direccion_empresa:
                direccion_empresa = data.direccion_servicio.strip()
            if not ciudad_empresa:
                ciudad_empresa = data.ciudad_servicio.strip()

            # Inserta la programación una sola vez. La columna direccion_servicio solo
            # existe si la migración ya se aplicó.
            direccion_columna = await self._programacion_tiene_columna("direccion_servicio")
            sede_columna = await self._programacion_tiene_columna("id_sede")
            if direccion_columna and sede_columna:
                columnas = "id_programacion, id_solicitud, id_empresa, id_sede, direccion_servicio, fecha_inicio, fecha_fin, modalidad, ciudad_servicio, estado, notificacion_enviada, anio_ciclo"
                valores = ":id_programacion, :id_solicitud, :id_empresa, :id_sede, :direccion, :fecha_inicio, :fecha_fin, :modalidad, :ciudad, 'Programada', TRUE, :anio_ciclo"
                params = {
                    "id_programacion": str(id_programacion),
                    "id_solicitud": str(data.id_solicitud),
                    "id_empresa": str(solicitud["id_empresa"]),
                    "id_sede": str(data.id_sede) if data.id_sede else None,
                    "direccion": direccion_empresa,
                    "fecha_inicio": data.fecha_inicio,
                    "fecha_fin": data.fecha_fin,
                    "modalidad": data.modalidad,
                    "ciudad": ciudad_empresa,
                    "anio_ciclo": fecha_programacion.year,
                }
            elif direccion_columna:
                columnas = "id_programacion, id_solicitud, id_empresa, direccion_servicio, fecha_inicio, fecha_fin, modalidad, ciudad_servicio, estado, notificacion_enviada, anio_ciclo"
                valores = ":id_programacion, :id_solicitud, :id_empresa, :direccion, :fecha_inicio, :fecha_fin, :modalidad, :ciudad, 'Programada', TRUE, :anio_ciclo"
                params = {
                    "id_programacion": str(id_programacion),
                    "id_solicitud": str(data.id_solicitud),
                    "id_empresa": str(solicitud["id_empresa"]),
                    "direccion": direccion_empresa,
                    "fecha_inicio": data.fecha_inicio,
                    "fecha_fin": data.fecha_fin,
                    "modalidad": data.modalidad,
                    "ciudad": ciudad_empresa,
                    "anio_ciclo": fecha_programacion.year,
                }
            else:
                columnas = "id_programacion, id_solicitud, id_empresa, fecha_inicio, fecha_fin, modalidad, ciudad_servicio, estado, notificacion_enviada, anio_ciclo"
                valores = ":id_programacion, :id_solicitud, :id_empresa, :fecha_inicio, :fecha_fin, :modalidad, :ciudad, 'Programada', TRUE, :anio_ciclo"
                params = {
                    "id_programacion": str(id_programacion),
                    "id_solicitud": str(data.id_solicitud),
                    "id_empresa": str(solicitud["id_empresa"]),
                    "fecha_inicio": data.fecha_inicio,
                    "fecha_fin": data.fecha_fin,
                    "modalidad": data.modalidad,
                    "ciudad": ciudad_empresa,
                    "anio_ciclo": fecha_programacion.year,
                }
            await self.db.execute(text(f"INSERT INTO programacion_visita ({columnas}) VALUES ({valores})"), params)

            # Un detalle por auditor.
            for id_usuario, rol_final in auditores_ok:
                id_detalle = uuid4()
                await self.db.execute(
                    text("""
                        INSERT INTO detalle_programacion_auditor (
                            id_detalle, id_programacion, id_usuario, rol_auditor, horas_asignadas
                        ) VALUES (
                            :id_detalle, :id_programacion, :id_usuario, :rol, :horas
                        )
                    """),
                    {
                        "id_detalle": str(id_detalle),
                        "id_programacion": str(id_programacion),
                        "id_usuario": str(id_usuario),
                        "rol": self._normalizar_rol_agenda(rol_final),
                        "horas": duracion_horas,
                    },
                )

            # Una notificación por auditor.
            for id_usuario, rol_final in auditores_ok:
                await self._crear_notificacion(
                    id_programacion=id_programacion,
                    id_usuario=id_usuario,
                    titulo="Nueva auditoría programada",
                    mensaje=(
                        f"Se programó una auditoría para {fecha_programacion.isoformat()} "
                        f"de {data.fecha_inicio:%H:%M} a {data.fecha_fin:%H:%M}. "
                        f"Empresa: {nombre_empresa}. "
                        f"Dirección: {data.direccion_servicio.strip()}, {data.ciudad_servicio.strip()}."
                    ),
                )

            await self.db.commit()
            return {
                "id_programacion": id_programacion,
                "id_solicitud": data.id_solicitud,
                "auditores": [str(a[0]) for a in auditores_ok],
                "fecha_inicio": data.fecha_inicio,
                "fecha_fin": data.fecha_fin,
                "estado": "Programada",
                "notificacion_creada": True,
                "mensaje": f"Auditoría registrada en la agenda para {len(auditores_ok)} auditor(es).",
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al crear programación de auditoría: {type(exc).__name__}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"No fue posible registrar la programación: {type(exc).__name__}: {exc}",
            ) from exc

    async def _nombre_empresa(self, id_solicitud: UUID) -> str:
        result = await self.db.execute(
            text("""
                SELECT COALESCE(e.nombre, 'Empresa no especificada')
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                WHERE s.id_solicitud = :id_solicitud
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return str(result.scalar() or "Empresa no especificada")

    async def _crear_notificacion(
        self,
        id_programacion: UUID,
        id_usuario: UUID,
        titulo: str,
        mensaje: str,
    ):
        if not await self._tabla_existe("notificacion_agenda_auditor"):
            return
        await self.db.execute(
            text("""
                INSERT INTO notificacion_agenda_auditor (
                    id_notificacion, id_programacion, id_usuario, titulo, mensaje, leida
                ) VALUES (
                    :id_notificacion, :id_programacion, :id_usuario, :titulo, :mensaje, FALSE
                )
                ON CONFLICT (id_programacion, id_usuario)
                DO UPDATE SET titulo = EXCLUDED.titulo,
                              mensaje = EXCLUDED.mensaje,
                              leida = FALSE,
                              fecha_creacion = CURRENT_TIMESTAMP
            """),
            {
                "id_notificacion": str(uuid4()),
                "id_programacion": str(id_programacion),
                "id_usuario": str(id_usuario),
                "titulo": titulo,
                "mensaje": mensaje,
            },
        )

    async def _registrar_bitacora_validacion(
        self,
        id_programacion: UUID | None,
        id_usuario: UUID | None,
        tipo_validacion: str,
        resultado: bool,
        detalle: str,
    ) -> None:
        """Registra una validaci��n en la bitacora_validacion_agenda."""
        try:
            await self.db.execute(text("""
                INSERT INTO bitacora_validacion_agenda (
                    id_bitacora, id_programacion, id_usuario, tipo_validacion,
                    resultado_validacion, detalle_resultado, fecha_validacion
                ) VALUES (
                    :id_bitacora, :id_programacion, :id_usuario, :tipo_validacion,
                    :resultado_validacion, :detalle_resultado, CURRENT_TIMESTAMP
                )
            """), {
                "id_bitacora": str(uuid4()),
                "id_programacion": str(id_programacion) if id_programacion else None,
                "id_usuario": str(id_usuario) if id_usuario else None,
                "tipo_validacion": tipo_validacion,
                "resultado_validacion": resultado,
                "detalle_resultado": detalle,
            })
            await self.db.commit()
        except Exception as exc:
            print(f"Error al registrar bitacora validacion: {type(exc).__name__}: {exc}")
            await self.db.rollback()

    async def _registrar_historial_disponibilidad(self, fila: dict, accion: str):
        """Guarda una instantánea para auditoría de creación/edición de disponibilidad."""
        await self.db.execute(text("""
            INSERT INTO historial_disponibilidad_auditor (
                id_historial, id_disponibilidad, id_usuario, accion,
                tipo_registro, dia_semana, fecha_inicio, fecha_fin,
                hora_inicio, hora_fin, motivo, estado, fecha_evento
            ) VALUES (
                :id_historial, :id_disponibilidad, :id_usuario, :accion,
                :tipo_registro, :dia_semana, :fecha_inicio, :fecha_fin,
                :hora_inicio, :hora_fin, :motivo, :estado, CURRENT_TIMESTAMP
            )
        """), {
            "id_historial": str(uuid4()),
            "id_disponibilidad": str(fila["id_disponibilidad"]),
            "id_usuario": str(fila["id_usuario"]),
            "accion": accion,
            "tipo_registro": fila.get("tipo_registro"),
            "dia_semana": fila.get("dia_semana"),
            "fecha_inicio": fila.get("fecha_inicio"),
            "fecha_fin": fila.get("fecha_fin"),
            "hora_inicio": fila.get("hora_inicio"),
            "hora_fin": fila.get("hora_fin"),
            "motivo": fila.get("motivo"),
            "estado": fila.get("estado"),
        })

    async def _obtener_auditor_bloqueado(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_usuario, estado, estado_auditor
            FROM usuario
            WHERE id_usuario = :id_usuario
            FOR UPDATE
        """), {"id_usuario": str(id_usuario)})
        auditor = result.mappings().first()
        if not auditor:
            raise HTTPException(status_code=404, detail="El auditor no existe.")
        if str(auditor["estado"] or "").strip().upper() != "ACTIVO":
            raise HTTPException(status_code=409, detail="El auditor está desactivado y no puede cambiar su disponibilidad.")
        if str(auditor["estado_auditor"] or "").strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
            raise HTTPException(status_code=409, detail="Solo un auditor aprobado/activo puede configurar disponibilidad.")
        return auditor

    @staticmethod
    def _numero_dia_semana(dia: str | int | None) -> int | None:
        """Mapeo ISO del campo integer dia_semana: lunes=1, ..., domingo=7."""
        if dia is None:
            return None
        if isinstance(dia, int):
            return dia
        dia_norm = normalizar_dia(str(dia))
        mapa = {"lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
                "viernes": 5, "sabado": 6, "domingo": 7}
        if dia_norm not in mapa:
            raise HTTPException(status_code=422, detail="Día de la semana no válido.")
        return mapa[dia_norm]

    @staticmethod
    def _etiqueta_dia_semana(dia: int | str | None) -> str:
        """Devuelve nombre del día para las filas de agenda mensual."""
        nombres = {0: "domingo", 1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves",
                   5: "viernes", 6: "sábado", 7: "domingo"}
        try:
            return nombres.get(int(dia), "") if dia is not None else ""
        except (TypeError, ValueError):
            return normalizar_dia(str(dia))

    async def _validar_solapamiento_disponibilidad(
        self,
        id_usuario: UUID,
        dia_semana: str | None,
        fecha_inicio: date,
        fecha_fin: date | None,
        hora_inicio: time | None,
        hora_fin: time | None,
        excluir_id: UUID | None = None,
    ):
        if not hora_inicio or not hora_fin:
            return
        params = {
            "id_usuario": str(id_usuario),
            "dia": self._numero_dia_semana(dia_semana) if dia_semana else None,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin or date(9999, 12, 31),
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "excluir_id": str(excluir_id) if excluir_id else None,
        }
        result = await self.db.execute(text("""
            SELECT id_disponibilidad
            FROM disponibilidad_auditor da
            WHERE da.id_usuario = :id_usuario
              AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
              AND LOWER(TRIM(COALESCE(da.tipo_registro, ''))) IN
                  ('disponible', 'disponibilidad', 'horario disponible', 'availability', 'semanal', 'horario semanal', 'disponibilidad extra')
              AND (CAST(:dia AS INTEGER) IS NULL OR da.dia_semana = CAST(:dia AS INTEGER) OR (CAST(:dia AS INTEGER) = 7 AND da.dia_semana = 0))
              AND CAST(da.fecha_inicio AS DATE) <= :fecha_fin
              AND (da.fecha_fin IS NULL OR CAST(da.fecha_fin AS DATE) >= :fecha_inicio)
              AND (da.hora_inicio IS NULL OR da.hora_inicio < :hora_fin)
              AND (da.hora_fin IS NULL OR da.hora_fin > :hora_inicio)
              AND (CAST(:excluir_id AS UUID) IS NULL OR da.id_disponibilidad <> CAST(:excluir_id AS UUID))
            LIMIT 1
        """), params)
        if result.first():
            await self._registrar_bitacora_validacion(
                None, id_usuario, "Cruce horario", False,
                f"Ya existe un horario disponible superpuesto para {dia_semana or 'ese periodo'}.",
            )
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un horario disponible superpuesto para {dia_semana or 'ese periodo'}.",
            )

    async def configurar_disponibilidad_semanal(
        self, id_usuario: UUID, data: DisponibilidadSemanalCrear
    ) -> dict:
        """Crea una fila recurrente por cada día configurado."""
        try:
            if data.fecha_inicio < date.today():
                raise HTTPException(status_code=422, detail="La vigencia semanal debe comenzar hoy o en una fecha futura.")
            await self._obtener_auditor_bloqueado(id_usuario)
            creados = []
            inicio = datetime.combine(data.fecha_inicio, time.min)
            fin = datetime.combine(data.fecha_fin, time.max) if data.fecha_fin else None
            for dia in data.dias:
                dia_norm = normalizar_dia(dia.dia_semana)
                dia_numero = self._numero_dia_semana(dia_norm)
                await self._validar_solapamiento_disponibilidad(
                    id_usuario, dia_norm, data.fecha_inicio, data.fecha_fin,
                    dia.hora_inicio, dia.hora_fin,
                )
                id_disp = uuid4()
                params = {
                    "id_disponibilidad": str(id_disp),
                    "id_usuario": str(id_usuario),
                    "tipo_registro": "Horario Semanal",
                    "dia_semana": dia_numero,
                    "fecha_inicio": inicio,
                    "fecha_fin": fin,
                    "hora_inicio": dia.hora_inicio,
                    "hora_fin": dia.hora_fin,
                    "motivo": data.motivo.strip() or "Disponibilidad semanal",
                    "estado": "Activo",
                }
                result = await self.db.execute(text("""
                    INSERT INTO disponibilidad_auditor (
                        id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                        fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
                    ) VALUES (
                        :id_disponibilidad, :id_usuario, :tipo_registro, :dia_semana,
                        :fecha_inicio, :fecha_fin, :hora_inicio, :hora_fin, :motivo, :estado
                    )
                    RETURNING id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                              fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
                """), params)
                row = dict(result.mappings().one())
                await self._registrar_historial_disponibilidad(row, "CREADA")
                creados.append(row)
            await self.db.commit()
            return {"mensaje": "Disponibilidad semanal configurada.", "registros": creados}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al configurar disponibilidad semanal: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible configurar la disponibilidad semanal.") from exc

    @staticmethod
    def _serializar_conflicto(conflicto: dict | None) -> dict | None:
        """Convierte el cruce a tipos serializables en JSON (UUID, datetime, date)."""
        if not conflicto:
            return None
        serializable = {}
        for clave, valor in conflicto.items():
            if isinstance(valor, datetime):
                serializable[clave] = valor.isoformat()
            elif isinstance(valor, date):
                serializable[clave] = valor.isoformat()
            elif isinstance(valor, UUID):
                serializable[clave] = str(valor)
            else:
                serializable[clave] = valor
        return serializable

    async def _retirar_auditor_por_bloqueo(
        self,
        id_programacion: UUID,
        id_usuario: UUID,
        fecha_bloqueo: date,
        motivo: str,
    ) -> dict:
        """
        Registra la indisponibilidad de un auditor en un día de la programación.

        El auditor NO se elimina de la visita: conserva la agenda programmed y
        el día bloqueado queda marcado como "No disponible" en las consultas.
        La programación tampoco se cancela, de modo que los demás auditores
        continúan con la visita.
        """
        prog = await self.db.execute(text("""
            SELECT id_programacion, fecha_inicio, fecha_fin, estado
            FROM programacion_visita
            WHERE id_programacion = :id
        """), {"id": str(id_programacion)})
        actual = prog.mappings().first()
        if not actual:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "La programación no existe.")
        if str(actual["estado"] or "").strip().upper() in {"CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO"}:
            raise HTTPException(status.HTTP_409_CONFLICT, "La programación ya está cancelada o finalizada.")

        detalle = await self.db.execute(text("""
            SELECT 1 FROM detalle_programacion_auditor
            WHERE id_programacion = :id AND id_usuario = :usuario
        """), {"id": str(id_programacion), "usuario": str(id_usuario)})
        if not detalle.first():
            raise HTTPException(status.HTTP_409_CONFLICT, "El auditor no está asignado a esta programación.")
        await self.db.commit()
        return {
            "mensaje": "El día quedó bloqueado para el auditor; conserva su agenda y los demás continúan con la visita.",
            "quedan_auditores": True,
            "programacion_cancelada": False,
        }

    async def listar_bloqueos_activos(self):
        """Lista los bloqueos de fecha vigentes con los datos del auditor."""
        result = await self.db.execute(text("""
            SELECT da.id_disponibilidad, da.id_usuario,
                   u.nombre, u.correo, u.tipo_doc, u.num_doc,
                   da.fecha_inicio, da.fecha_fin, da.motivo
            FROM disponibilidad_auditor da
            INNER JOIN usuario u ON u.id_usuario = da.id_usuario
            WHERE da.tipo_registro = 'Bloqueo Fecha'
              AND UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')
            ORDER BY da.fecha_inicio DESC, u.nombre
        """))
        return [dict(row) for row in result.mappings().all()]

    async def consultar_dias_programacion(self, id_usuario: UUID, id_programacion: UUID) -> dict:
        """Detalla, día por día, el estado de disponibilidad del auditor en una programación."""
        result = await self.db.execute(text("""
            SELECT p.fecha_inicio, p.fecha_fin, p.estado
            FROM programacion_visita p
            WHERE p.id_programacion = :id
        """), {"id": str(id_programacion)})
        prog = result.mappings().first()
        if not prog:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "La programación no existe.")

        auditor = await self.db.execute(text("""
            SELECT id_usuario, nombre, correo, tipo_doc, num_doc
            FROM usuario WHERE id_usuario = :u
        """), {"u": str(id_usuario)})
        datos = dict(auditor.mappings().first() or {})

        inicio = prog["fecha_inicio"].date()
        fin = prog["fecha_fin"].date()
        dias = []
        actual = inicio
        while actual <= fin:
            registros = await self.db.execute(text("""
                SELECT tipo_registro, motivo, hora_inicio, hora_fin
                FROM disponibilidad_auditor
                WHERE id_usuario = :u
                  AND UPPER(TRIM(COALESCE(estado, ''))) IN ('ACTIVO', 'ACTIVA')
                  AND CAST(fecha_inicio AS DATE) <= :d
                  AND CAST(COALESCE(fecha_fin, fecha_inicio) AS DATE) >= :d
            """), {"u": str(id_usuario), "d": actual})
            filas = registros.mappings().all()
            bloqueo = next((f for f in filas if str(f["tipo_registro"] or "").lower() == "bloqueo fecha"), None)
            horario = next((f for f in filas if str(f["tipo_registro"] or "").lower() in ("horario semanal", "disponibilidad extra")), None)
            franja = None
            if horario and horario["hora_inicio"] and horario["hora_fin"]:
                franja = f"{horario['hora_inicio'].strftime('%H:%M')} - {horario['hora_fin'].strftime('%H:%M')}"
            dias.append({
                "fecha": actual.isoformat(),
                "dia_semana": self._etiqueta_dia_semana(actual.weekday() + 1),
                "estado": "bloqueado" if bloqueo else "disponible",
                "motivo": bloqueo["motivo"] if bloqueo else None,
                "horario": franja,
            })
            actual += timedelta(days=1)
        return {"dias": dias, "auditor": datos, "programacion": {
            "fecha_inicio": prog["fecha_inicio"].isoformat(),
            "fecha_fin": prog["fecha_fin"].isoformat(),
            "estado": prog["estado"],
        }}

    async def registrar_fecha_no_disponible(
        self, id_usuario: UUID, data: FechaNoDisponibleCrear
    ) -> dict:
        """Registra uno o varios días completos como no disponibles."""
        try:
            if data.fecha_inicio < date.today():
                raise HTTPException(status_code=422, detail="La fecha no disponible debe ser hoy o futura.")
            await self._obtener_auditor_bloqueado(id_usuario)
            fecha_fin = data.fecha_fin or data.fecha_inicio
            inicio_dt = datetime.combine(data.fecha_inicio, time.min)
            fin_dt = datetime.combine(fecha_fin, time.max)
            retiro_info = None
            cruce = await self._buscar_cruce(id_usuario, inicio_dt, fin_dt)
            if cruce:
                # Si el conflicto es con la MISMA programación que originó el
                # bloqueo, se cancela automáticamente: esa es la intención del
                # bloqueo. Con otras programaciones se requiere autorización
                # explícita (cancelar_programacion).
                id_cruce = UUID(str(cruce.get("id_programacion")))
                es_programacion_seleccionada = bool(
                    data.id_programacion and id_cruce == UUID(str(data.id_programacion))
                )
                puede_cancelar = es_programacion_seleccionada or bool(data.cancelar_programacion)
                if not puede_cancelar:
                    await self._registrar_bitacora_validacion(
                        None, id_usuario, "Bloqueo fecha", False,
                        "No se puede bloquear la fecha porque el auditor ya tiene una auditoría programada en ese periodo.",
                    )
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "mensaje": "No se puede bloquear la fecha porque el auditor ya tiene una auditoría programada en ese periodo.",
                            "conflicto": self._serializar_conflicto(cruce),
                        },
                    )
                motivo_cancelacion = (
                    f"Bloqueo de disponibilidad: {data.motivo.strip()}"
                )
                if es_programacion_seleccionada:
                    # Se retira al auditor únicamente del día bloqueado: los demás
                    # auditores de la visita continúan y el retirado es notificado.
                    try:
                        retiro = await self._retirar_auditor_por_bloqueo(
                            id_cruce, id_usuario, data.fecha_inicio, motivo_cancelacion
                        )
                        retiro_info = retiro
                    except HTTPException:
                        await self.db.rollback()
                        raise
                    await self._registrar_bitacora_validacion(
                        id_cruce, id_usuario, "Bloqueo fecha", True,
                        "Bloqueo registrado: el auditor fue retirado del día bloqueado. " + retiro["mensaje"],
                    )
                else:
                    try:
                        await self.cancelar_programacion(id_cruce, motivo_cancelacion)
                    except HTTPException:
                        await self.db.rollback()
                        raise
                    await self._registrar_bitacora_validacion(
                        id_cruce, id_usuario, "Bloqueo fecha", True,
                        "Bloqueo registrado y auditoría programada cancelada: " + motivo_cancelacion,
                    )
            id_disp = uuid4()
            result = await self.db.execute(text("""
                INSERT INTO disponibilidad_auditor (
                    id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                    fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado,
                    id_programacion
                ) VALUES (
                    :id_disponibilidad, :id_usuario, 'Bloqueo Fecha', :dia_semana,
                    :fecha_inicio, :fecha_fin, NULL, NULL, :motivo, 'Activo',
                    :id_programacion
                )
                RETURNING id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                          fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
            """), {
                "id_disponibilidad": str(id_disp),
                "id_usuario": str(id_usuario),
                "fecha_inicio": inicio_dt,
                "fecha_fin": fin_dt,
                "motivo": data.motivo.strip(),
                "dia_semana": data.fecha_inicio.weekday() + 1,
                "id_programacion": str(data.id_programacion) if data.id_programacion else None,
            })
            row = dict(result.mappings().one())
            await self._registrar_historial_disponibilidad(row, "REGISTRADA_NO_DISPONIBLE")
            # Notificar al auditor del bloqueo (requiere la programación de referencia).
            if data.id_programacion:
                mensaje = (
                    f"Se registró el bloqueo de disponibilidad del {data.fecha_inicio.strftime('%d/%m/%Y')}"
                    f"{' al ' + fecha_fin.strftime('%d/%m/%Y') if fecha_fin != data.fecha_inicio else ''}. "
                    f"Motivo: {data.motivo.strip()}."
                )
                if retiro_info:
                    mensaje += (
                        " Además, usted fue retirado de la auditoría programada de ese día "
                        "y el resto de auditores continúan con la visita."
                    )
                await self._crear_notificacion(
                    data.id_programacion,
                    id_usuario,
                    "Día no disponible",
                    mensaje,
                )
            await self.db.commit()
            return {
                "mensaje": "Fecha(s) registrada(s) como no disponible(s).",
                "registro": row,
                "notificado": bool(data.id_programacion),
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al registrar fecha no disponible: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible registrar la fecha no disponible.") from exc

    async def desbloquear_fecha_no_disponible(self, id_usuario: UUID, fecha: date) -> dict:
        """Marca como inactivos los registros 'Bloqueo Fecha' que cubren la fecha indicada."""
        try:
            await self._obtener_auditor_bloqueado(id_usuario)
            inicio_dt = datetime.combine(fecha, time.min)
            fin_dt = datetime.combine(fecha, time.max)
            result = await self.db.execute(text("""
                UPDATE disponibilidad_auditor
                SET estado = 'Cancelado'
                WHERE id_usuario = :id_usuario
                  AND tipo_registro = 'Bloqueo Fecha'
                  AND estado = 'Activo'
                  AND fecha_inicio <= :fin_dt
                  AND fecha_fin >= :inicio_dt
                RETURNING id_disponibilidad
            """), {
                "id_usuario": str(id_usuario),
                "inicio_dt": inicio_dt,
                "fin_dt": fin_dt,
            })
            rows = result.mappings().all()
            await self.db.commit()
            return {"mensaje": "Fecha desbloqueada correctamente.", "afectados": len(rows)}
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al desbloquear fecha: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible desbloquear la fecha.") from exc

    async def registrar_disponibilidad_extraordinaria(
        self, id_usuario: UUID, data: DisponibilidadExtraordinariaCrear
    ) -> dict:
        """Registra una disponibilidad extraordinaria para un rango de fechas."""
        try:
            await self._obtener_auditor_bloqueado(id_usuario)
            fecha_fin = data.fecha_fin or data.fecha_inicio
            inicio_dt = datetime.combine(data.fecha_inicio, time.min)
            fin_dt = datetime.combine(fecha_fin, time.max)
            id_disp = uuid4()
            result = await self.db.execute(text("""
                INSERT INTO disponibilidad_auditor (
                    id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                    fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
                ) VALUES (
                    :id_disponibilidad, :id_usuario, 'Disponibilidad Extra', :dia_semana,
                    :fecha_inicio, :fecha_fin, NULL, NULL, :motivo, 'Activo'
                )
                RETURNING id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                          fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
            """), {
                "id_disponibilidad": str(id_disp),
                "id_usuario": str(id_usuario),
                "fecha_inicio": inicio_dt,
                "fecha_fin": fin_dt,
                "motivo": data.motivo.strip(),
                "dia_semana": data.fecha_inicio.weekday() + 1,
            })
            row = dict(result.mappings().one())
            await self._registrar_historial_disponibilidad(row, "REGISTRADA_EXTRAORDINARIA")
            await self.db.commit()
            return {"mensaje": "Disponibilidad extraordinaria registrada.", "registro": row}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al registrar disponibilidad extraordinaria: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible registrar la disponibilidad extraordinaria.") from exc

    async def eliminar_disponibilidad(self, id_usuario: UUID, id_disponibilidad: UUID) -> dict:
        """Marca como cancelada una disponibilidad específica."""
        try:
            await self._obtener_auditor_bloqueado(id_usuario)
            result = await self.db.execute(text("""
                UPDATE disponibilidad_auditor
                SET estado = 'Cancelado'
                WHERE id_disponibilidad = :id_disponibilidad
                  AND id_usuario = :id_usuario
                RETURNING id_disponibilidad
            """), {
                "id_disponibilidad": str(id_disponibilidad),
                "id_usuario": str(id_usuario),
            })
            row = result.mappings().first()
            if not row:
                raise HTTPException(status_code=404, detail="No se encontró la disponibilidad.")
            await self.db.commit()
            return {"mensaje": "Disponibilidad eliminada correctamente."}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al eliminar disponibilidad: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible eliminar la disponibilidad.") from exc

    async def editar_disponibilidad(
        self, id_usuario: UUID, id_disponibilidad: UUID, data: DisponibilidadEditar
    ) -> dict:
        """Edita una regla futura y conserva instantáneas del antes y del después."""
        try:
            await self._obtener_auditor_bloqueado(id_usuario)
            result = await self.db.execute(text("""
                SELECT id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                       fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
                FROM disponibilidad_auditor
                WHERE id_disponibilidad = :id_disponibilidad
                  AND id_usuario = :id_usuario
                FOR UPDATE
            """), {"id_disponibilidad": str(id_disponibilidad), "id_usuario": str(id_usuario)})
            actual = result.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="No se encontró el registro de disponibilidad para ese auditor.")
            actual = dict(actual)
            if str(actual.get("estado") or "").strip().upper() not in {"ACTIVO", "ACTIVA"}:
                raise HTTPException(status_code=409, detail="Solo se pueden editar registros de disponibilidad activos.")
            if str(actual.get("tipo_registro") or "").strip().lower() in {"no disponible", "no_disponible", "indisponible", "bloqueo"}:
                raise HTTPException(status_code=409, detail="Los bloqueos de fechas no disponibles no se editan como horarios semanales; registre un nuevo bloqueo si necesita ampliar el periodo.")
            fecha_fin_vigencia = actual.get("fecha_fin")
            if fecha_fin_vigencia and fecha_fin_vigencia.date() < date.today():
                raise HTTPException(status_code=409, detail="No se pueden editar registros cuya vigencia ya terminó.")
            if data.fecha_inicio < date.today():
                raise HTTPException(status_code=422, detail="La nueva vigencia debe comenzar hoy o en una fecha futura.")

            await self._registrar_historial_disponibilidad(actual, "ANTES_DE_EDICION")
            dia = self._numero_dia_semana(data.dia_semana) if data.dia_semana else actual.get("dia_semana")
            dia_label = normalizar_dia(data.dia_semana) if data.dia_semana else self._etiqueta_dia_semana(actual.get("dia_semana"))
            await self._validar_solapamiento_disponibilidad(
                id_usuario,
                dia_label,
                data.fecha_inicio,
                data.fecha_fin,
                data.hora_inicio,
                data.hora_fin,
                excluir_id=id_disponibilidad,
            )
            fecha_inicio_dt = datetime.combine(data.fecha_inicio, time.min)
            fecha_fin_dt = datetime.combine(data.fecha_fin, time.max) if data.fecha_fin else None
            updated = await self.db.execute(text("""
                UPDATE disponibilidad_auditor
                SET fecha_inicio = :fecha_inicio,
                    fecha_fin = :fecha_fin,
                    dia_semana = :dia_semana,
                    hora_inicio = :hora_inicio,
                    hora_fin = :hora_fin,
                    motivo = :motivo
                WHERE id_disponibilidad = :id_disponibilidad
                  AND id_usuario = :id_usuario
                RETURNING id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                          fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado
            """), {
                "fecha_inicio": fecha_inicio_dt,
                "fecha_fin": fecha_fin_dt,
                "dia_semana": dia,
                "hora_inicio": data.hora_inicio,
                "hora_fin": data.hora_fin,
                "motivo": data.motivo.strip(),
                "id_disponibilidad": str(id_disponibilidad),
                "id_usuario": str(id_usuario),
            })
            row = dict(updated.mappings().one())
            await self._registrar_historial_disponibilidad(row, "EDITADA")
            await self.db.commit()
            return {"mensaje": "Disponibilidad futura actualizada y registrada en el historial.", "registro": row}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al editar disponibilidad: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible editar la disponibilidad.") from exc

    async def consultar_bitacora_validacion(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_bitacora, id_programacion, id_usuario, tipo_validacion,
                   resultado_validacion, detalle_resultado, fecha_validacion
            FROM bitacora_validacion_agenda
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_validacion DESC
        """), {"id_usuario": str(id_usuario)})
        return [dict(row) for row in result.mappings().all()]

    async def consultar_historial_disponibilidad(self, id_usuario: UUID):
        """
        Devuelve la trazabilidad completa del auditor.

        Cada registro incluye:
          - accion: CREADA, EDITADA, REGISTRADA_NO_DISPONIBLE,
                    REGISTRADA_EXTRAORDINARIA, REGISTRO_EXISTENTE
          - fecha_evento: cuándo ocurrió
          - antes: estado del registro antes de la acción (si existe)
          - despues: estado del registro después de la acción
        """
        result = await self.db.execute(text("""
            SELECT id_historial, id_disponibilidad, id_usuario, accion, tipo_registro,
                   dia_semana, fecha_inicio, fecha_fin, hora_inicio, hora_fin,
                   motivo, estado, fecha_evento
            FROM historial_disponibilidad_auditor
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_evento ASC NULLS FIRST,
                     CASE WHEN accion = 'ANTES_DE_EDICION' THEN 0 ELSE 1 END
        """), {"id_usuario": str(id_usuario)})
        historial = [dict(row) for row in result.mappings().all()]

        # Agrupar por registro de disponibilidad para calcular antes/después
        grupos: dict[str, list] = {}
        orden: list[str] = []
        for row in historial:
            clave = str(row.get("id_disponibilidad"))
            if clave not in grupos:
                grupos[clave] = []
                orden.append(clave)
            grupos[clave].append(row)

        procesado: list = []
        for clave in orden:
            eventos = grupos[clave]
            indice = 0
            while indice < len(eventos):
                actual = eventos[indice]
                accion = str(actual.get("accion") or "")
                if accion == "ANTES_DE_EDICION" and indice + 1 < len(eventos):
                    # ANTES_DE_EDICION guarda el estado previo; el siguiente
                    # evento (EDITADA) guarda el estado posterior.
                    posterior = eventos[indice + 1]
                    procesado.append({
                        **posterior,
                        "accion": "EDITADA",
                        "antes": actual,
                        "despues": posterior,
                    })
                    indice += 2
                    continue
                procesado.append({
                    **actual,
                    "antes": eventos[indice - 1] if indice > 0 else None,
                    "despues": actual,
                })
                indice += 1

        # Registros vigentes que no tienen eventos de historial
        ids_con_historial = {str(row.get("id_disponibilidad")) for row in historial}
        actuales = await self.consultar_agenda(id_usuario, incluir_inactivos=True)
        for row in actuales:
            if str(row.get("id_disponibilidad")) not in ids_con_historial:
                procesado.append({
                    **row,
                    "accion": "REGISTRO_EXISTENTE",
                    "fecha_evento": None,
                    "antes": None,
                    "despues": None,
                })

        procesado.sort(
            key=lambda row: row.get("fecha_evento") or datetime.min,
            reverse=True,
        )
        return procesado

    async def ver_disponibilidad_mensual_general(
        self,
        anio: int,
        mes: int,
        ciudad: str | None = None,
        modalidad: str | None = None,
    ) -> dict:
        """Vista administrativa: auditorías y disponibilidad de todo el sistema en un mes."""
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=422, detail="El mes debe estar entre 1 y 12.")
        if anio < 2000 or anio > 2100:
            raise HTTPException(status_code=422, detail="El año debe estar entre 2000 y 2100.")
        primer_dia = date(anio, mes, 1)
        ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

        filtros = [
            "UPPER(TRIM(COALESCE(da.estado, ''))) IN ('ACTIVO', 'ACTIVA')",
            "CAST(da.fecha_inicio AS DATE) <= :ultimo",
            "CAST(COALESCE(da.fecha_fin, da.fecha_inicio) AS DATE) >= :primer",
        ]
        params = {
            "primer": primer_dia,
            "ultimo": ultimo_dia,
            "ciudad": f"%{ciudad.strip().lower()}%" if ciudad and ciudad.strip() else None,
            "modalidad": modalidad.strip() if modalidad and modalidad.strip() else None,
        }
        where = " AND ".join(filtros)

        # Disponibilidad de todos los auditores dentro del mes
        result = await self.db.execute(text(f"""
            SELECT da.id_disponibilidad, da.id_usuario, da.tipo_registro, da.dia_semana,
                   da.fecha_inicio, da.fecha_fin, da.hora_inicio, da.hora_fin,
                   da.motivo, da.estado,
                   u.nombre AS auditor_nombre, u.correo AS auditor_correo
            FROM disponibilidad_auditor da
            INNER JOIN usuario u ON u.id_usuario = da.id_usuario
            WHERE {where}
            ORDER BY da.fecha_inicio, u.nombre
        """), params)
        disponibilidades = [dict(row) for row in result.mappings().all()]

        # Auditorías programadas del mes con sus auditores
        filtros_aud = [
            "CAST(p.fecha_inicio AS DATE) <= :ultimo",
            "CAST(p.fecha_fin AS DATE) >= :primer",
            "UPPER(TRIM(COALESCE(p.estado, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')",
        ]
        if ciudad and ciudad.strip():
            filtros_aud.append("LOWER(COALESCE(p.ciudad_servicio, '')) LIKE :ciudad")
        if modalidad and modalidad.strip():
            filtros_aud.append("LOWER(COALESCE(p.modalidad, '')) = LOWER(:modalidad)")
        result_aud = await self.db.execute(text(f"""
            SELECT p.id_programacion, p.id_solicitud, p.fecha_inicio, p.fecha_fin,
                   p.modalidad, p.ciudad_servicio, p.estado AS estado_programacion,
                   p.direccion_servicio, p.motivo_reprogramacion, p.motivo_cancelacion,
                   d.id_usuario, d.rol_auditor,
                   s.numero_radicado, e.nombre AS empresa_nombre, e.nit AS empresa_nit,
                   u.nombre AS auditor_nombre, u.correo AS auditor_correo
            FROM programacion_visita p
            INNER JOIN detalle_programacion_auditor d ON d.id_programacion = p.id_programacion
            INNER JOIN usuario u ON u.id_usuario = d.id_usuario
            LEFT JOIN solicitud s ON s.id_solicitud = p.id_solicitud
            LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE {' AND '.join(filtros_aud)}
            ORDER BY p.fecha_inicio, u.nombre
        """), params)
        auditorias = [dict(row) for row in result_aud.mappings().all()]

        # Armar el calendario día por día
        nombres_dia = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        por_dia_aud = {}
        for item in auditorias:
            if not isinstance(item.get("fecha_inicio"), datetime):
                continue
            inicio = item["fecha_inicio"].date()
            fin = item.get("fecha_fin")
            fin = fin.date() if isinstance(fin, datetime) else inicio
            dia_actual = inicio
            while dia_actual <= fin:
                por_dia_aud.setdefault(dia_actual.isoformat(), []).append(item)
                dia_actual += timedelta(days=1)
        dias = []
        for numero in range(1, ultimo_dia.day + 1):
            fecha_actual = date(anio, mes, numero)
            iso = fecha_actual.isoformat()
            dia_nombre = nombres_dia[fecha_actual.weekday()]
            aplican = []
            for registro in disponibilidades:
                inicio = registro.get("fecha_inicio")
                fin = registro.get("fecha_fin")
                inicio_dia = inicio.date() if isinstance(inicio, datetime) else inicio
                fin_dia = fin.date() if isinstance(fin, datetime) else fin
                if inicio_dia and inicio_dia > fecha_actual:
                    continue
                if fin_dia and fin_dia < fecha_actual:
                    continue
                tipo = str(registro.get("tipo_registro") or "").strip().lower()
                dia_registro = self._etiqueta_dia_semana(registro.get("dia_semana"))
                if tipo in {"no disponible", "no_disponible", "indisponible", "bloqueo", "bloqueo fecha"}:
                    aplican.append(registro)
                elif not dia_registro or normalizar_dia(dia_registro) == dia_nombre:
                    aplican.append(registro)
            dias.append({
                "fecha": iso,
                "dia_semana": dia_nombre,
                "disponibilidad": aplican,
                "auditorias": por_dia_aud.get(iso, []),
            })
        return {
            "anio": anio,
            "mes": mes,
            "ciudad": ciudad,
            "modalidad": modalidad,
            "dias": dias,
            "auditorias": auditorias,
        }

    async def ver_disponibilidad_mensual(
        self,
        id_usuario: UUID,
        anio: int,
        mes: int,
        ciudad: str | None = None,
        modalidad: str | None = None,
    ) -> dict:
        """Entrega por día las reglas de disponibilidad y auditorías del mes."""
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=422, detail="El mes debe estar entre 1 y 12.")
        if anio < 2000 or anio > 2100:
            raise HTTPException(status_code=422, detail="El año debe estar entre 2000 y 2100.")
        primer_dia = date(anio, mes, 1)
        ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])

        registros = await self.consultar_agenda(
            id_usuario, desde=primer_dia, hasta=ultimo_dia, incluir_inactivos=False
        )
        auditorias = await self.consultar_auditorias_programadas(
            id_usuario,
            desde=primer_dia,
            hasta=ultimo_dia,
            ciudad=ciudad,
            modalidad=modalidad,
        )
        dias = []
        nombres_dia = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        for numero in range(1, ultimo_dia.day + 1):
            fecha_actual = date(anio, mes, numero)
            dia_nombre = nombres_dia[fecha_actual.weekday()]
            aplican = []
            bloqueos = []
            for registro in registros:
                inicio = registro.get("fecha_inicio")
                fin = registro.get("fecha_fin")
                inicio_dia = inicio.date() if isinstance(inicio, datetime) else inicio
                fin_dia = fin.date() if isinstance(fin, datetime) else fin
                if inicio_dia and inicio_dia > fecha_actual:
                    continue
                if fin_dia and fin_dia < fecha_actual:
                    continue
                tipo = str(registro.get("tipo_registro") or "").strip().lower()
                dia_registro = self._etiqueta_dia_semana(registro.get("dia_semana"))
                if tipo in {"no disponible", "no_disponible", "indisponible", "bloqueo", "bloqueo fecha"}:
                    bloqueos.append(registro)
                elif not dia_registro or normalizar_dia(dia_registro) == dia_nombre:
                    aplican.append(registro)
            # El bloqueo de fecha tiene prioridad visual sobre la regla semanal.
            if bloqueos:
                aplican = bloqueos
            # Las programaciones canceladas o finalizadas no ocupan el horario.
            auditorias_dia = [
                item for item in auditorias
                if isinstance(item.get("fecha_inicio"), datetime)
                and item["fecha_inicio"].date() <= fecha_actual
                and (
                    not isinstance(item.get("fecha_fin"), datetime)
                    or item["fecha_fin"].date() >= fecha_actual
                )
                and str(item.get("estado") or "").strip().upper()
                not in ("CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO")
            ]
            dias.append({
                "fecha": fecha_actual.isoformat(),
                "dia_semana": dia_nombre,
                "disponibilidad": aplican,
                "auditorias": auditorias_dia,
            })
        return {
            "id_usuario": id_usuario,
            "anio": anio,
            "mes": mes,
            "ciudad": ciudad,
            "modalidad": modalidad,
            "dias": dias,
        }

    async def _auditores_de_programacion(self, id_programacion: UUID):
        result = await self.db.execute(text("""
            SELECT d.id_usuario, u.nombre, u.correo
            FROM detalle_programacion_auditor d
            LEFT JOIN usuario u ON u.id_usuario = d.id_usuario
            WHERE d.id_programacion = :id
            ORDER BY u.nombre
        """), {"id": str(id_programacion)})
        return [dict(row) for row in result.mappings().all()]

    async def confirmar_programacion(
        self,
        id_programacion: UUID,
        id_usuario_solicitante: UUID | None = None,
        es_admin: bool = False,
    ):
        """Confirma la programación. Puede hacerlo un administrador o un auditor asignado."""
        try:
            programacion = await self.db.execute(text("""
                SELECT id_programacion, estado FROM programacion_visita
                WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            actual = programacion.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="Programación no encontrada.")
            estado = str(actual["estado"] or "").strip().upper()
            if estado in {"CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO", "EJECUTADA"}:
                raise HTTPException(status_code=409, detail="La programación ya está cancelada, ejecutada o finalizada.")
            if estado == "CONFIRMADA":
                return {"mensaje": "La programación ya estaba confirmada.", "estado": "Confirmada"}
            if not es_admin:
                auditores = await self._auditores_de_programacion(id_programacion)
                if not auditores:
                    raise HTTPException(status_code=409, detail="La programación no tiene auditores asignados.")
                if not id_usuario_solicitante or not any(
                    str(a["id_usuario"]) == str(id_usuario_solicitante) for a in auditores
                ):
                    raise HTTPException(status_code=403, detail="Solo un auditor asignado puede confirmar esta programación.")
            # La confirmación es INDIVIDUAL: solo queda confirmado el auditor
            # que la realiza; el resto del equipo debe confirmar por separado.
            if id_usuario_solicitante:
                await self.db.execute(text("""
                    UPDATE detalle_programacion_auditor
                    SET confirmado = TRUE, fecha_confirmacion = CURRENT_TIMESTAMP
                    WHERE id_programacion = :id AND id_usuario = :usuario
                """), {"id": str(id_programacion), "usuario": str(id_usuario_solicitante)})
            else:
                # El administrador confirma en nombre del equipo completo.
                await self.db.execute(text("""
                    UPDATE detalle_programacion_auditor
                    SET confirmado = TRUE, fecha_confirmacion = CURRENT_TIMESTAMP
                    WHERE id_programacion = :id
                """), {"id": str(id_programacion)})
            # El estado global solo pasa a 'Confirmada' cuando TODO el equipo confirmó.
            pendientes = await self.db.execute(text("""
                SELECT COUNT(*) FROM detalle_programacion_auditor
                WHERE id_programacion = :id AND COALESCE(confirmado, FALSE) = FALSE
            """), {"id": str(id_programacion)})
            faltantes = pendientes.scalar() or 0
            total = await self.db.execute(text("""
                SELECT COUNT(*) FROM detalle_programacion_auditor WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            total_auditores = total.scalar() or 0
            if faltantes == 0 and total_auditores > 0:
                await self.db.execute(text("""
                    UPDATE programacion_visita SET estado = 'Confirmada'
                    WHERE id_programacion = :id
                      AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO', 'EJECUTADA')
                """), {"id": str(id_programacion)})
            await self.db.commit()
            if faltantes == 0 and total_auditores > 0:
                return {
                    "mensaje": "Programación confirmada por todo el equipo.",
                    "estado": "Confirmada",
                    "confirmados": total_auditores,
                    "pendientes": 0,
                }
            return {
                "mensaje": (
                    "Su confirmación quedó registrada. Los demás auditores de la visita deben confirmarla individualmente."
                ),
                "estado": "Programada",
                "confirmados": total_auditores - faltantes,
                "pendientes": faltantes,
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="No fue posible confirmar la programación.")

    async def solicitar_reprogramacion(
        self,
        id_programacion: UUID,
        id_usuario_solicitante: UUID | None = None,
        es_admin: bool = False,
        motivo: str = "",
    ) -> dict:
        """
        El auditor solicita formalmente la reprogramación de una visita indicando el motivo.

        La visita queda en estado 'Reprogramada' con el motivo de la solicitud y se
        notifica al resto de auditores del equipo y al solicitante.
        """
        if len(motivo.strip()) < 10:
            raise HTTPException(status_code=422, detail="Debe indicar el motivo de la reprogramación (mínimo 10 caracteres).")
        try:
            programacion = await self.db.execute(text("""
                SELECT id_programacion, id_solicitud, estado, fecha_inicio, fecha_fin
                FROM programacion_visita WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            actual = programacion.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="Programación no encontrada.")
            estado = str(actual["estado"] or "").strip().upper()
            if estado in {"CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO", "EJECUTADA"}:
                raise HTTPException(status_code=409, detail="La programación ya está cancelada, ejecutada o finalizada.")
            auditores = await self._auditores_de_programacion(id_programacion)
            if not auditores:
                raise HTTPException(status_code=409, detail="La programación no tiene auditores asignados.")
            solicitante = None
            if not es_admin:
                if not id_usuario_solicitante or not any(
                    str(a["id_usuario"]) == str(id_usuario_solicitante) for a in auditores
                ):
                    raise HTTPException(status_code=403, detail="Solo un auditor asignado puede solicitar la reprogramación.")
                solicitante = next(
                    (a for a in auditores if str(a["id_usuario"]) == str(id_usuario_solicitante)), None
                )
            detalle_motivo = f"Solicitud de reprogramación: {motivo.strip()}"
            await self.db.execute(text("""
                UPDATE programacion_visita
                SET estado = 'Reprogramada',
                    motivo_reprogramacion = :motivo,
                    estado_solicitud_reprogramacion = 'Pendiente',
                    id_usuario_solicitante_reprogramacion = :solicitante,
                    motivo_solicitud_reprogramacion = :motivo_solicitud
                WHERE id_programacion = :id
            """), {
                "motivo": detalle_motivo,
                "id": str(id_programacion),
                "solicitante": str(solicitante["id_usuario"]) if solicitante else None,
                "motivo_solicitud": motivo.strip(),
            })
            mensaje = f"Se solicitó formalmente la reprogramación de la visita. Motivo: {motivo.strip()}."
            for auditor in auditores:
                if solicitante and str(auditor["id_usuario"]) == str(solicitante["id_usuario"]):
                    continue
                await self._crear_notificacion(
                    id_programacion,
                    auditor["id_usuario"],
                    "Solicitud de reprogramación",
                    mensaje,
                )
            await self.db.commit()
            return {
                "mensaje": "Solicitud de reprogramación registrada con el motivo indicado.",
                "estado": "Reprogramada",
                "motivo": detalle_motivo,
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="No fue posible registrar la solicitud de reprogramación.")

    async def _notificar_solicitante(
        self,
        id_programacion: UUID,
        id_solicitante: UUID | None,
        titulo: str,
        mensaje: str,
    ) -> None:
        """Notifica al auditor que realizo la solicitud de reprogramacion."""
        if not id_solicitante:
            return
        try:
            await self._crear_notificacion(id_programacion, id_solicitante, titulo, mensaje)
        except Exception as exc:  # pragma: no cover - la notificacion no bloquea la decision
            print(f"No se pudo notificar al solicitante: {type(exc).__name__}: {exc}")

    async def _estado_final_programacion(self, id_programacion: UUID) -> str:
        """Calcula el estado final de la visita segun las confirmaciones del equipo."""
        total = await self.db.execute(
            text("SELECT COUNT(*) FROM detalle_programacion_auditor WHERE id_programacion = :id"),
            {"id": str(id_programacion)},
        )
        total_auditores = total.scalar() or 0
        pendientes = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM detalle_programacion_auditor
                WHERE id_programacion = :id AND COALESCE(confirmado, FALSE) = FALSE
            """),
            {"id": str(id_programacion)},
        )
        faltantes = pendientes.scalar() or 0
        if total_auditores > 0 and faltantes == 0:
            return "Confirmada"
        return "Programada"

    async def rechazar_solicitud_reprogramacion(
        self,
        id_programacion: UUID,
        motivo: str,
    ) -> dict:
        """El administrador rechaza la solicitud formal de reprogramacion."""
        if not motivo.strip():
            raise HTTPException(status_code=422, detail="Debe indicar el motivo del rechazo.")
        try:
            result = await self.db.execute(text("""
                SELECT id_programacion, estado, estado_solicitud_reprogramacion,
                       id_usuario_solicitante_reprogramacion, motivo_solicitud_reprogramacion
                FROM programacion_visita WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            actual = result.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="La programación no existe.")
            estado_solicitud = str(actual["estado_solicitud_reprogramacion"] or "").strip().upper()
            if estado_solicitud != "PENDIENTE":
                raise HTTPException(status_code=409, detail="La visita no tiene una solicitud de reprogramación pendiente.")
            estado_final = await self._estado_final_programacion(id_programacion)
            await self.db.execute(text("""
                UPDATE programacion_visita
                SET estado = :estado,
                    motivo_reprogramacion = NULL,
                    estado_solicitud_reprogramacion = 'Rechazada',
                    motivo_solicitud_reprogramacion = :motivo
                WHERE id_programacion = :id
            """), {
                "estado": estado_final,
                "motivo": motivo.strip(),
                "id": str(id_programacion),
            })
            await self.db.commit()
            await self._notificar_solicitante(
                id_programacion,
                actual["id_usuario_solicitante_reprogramacion"],
                "Solicitud de reprogramación rechazada",
                f"Se rechazó su solicitud de reprogramación. Motivo: {motivo.strip()}.",
            )
            await self.db.commit()
            return {
                "mensaje": "Solicitud de reprogramación rechazada y notificada al auditor.",
                "estado": estado_final,
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="No fue posible rechazar la solicitud.")

    async def resolver_solicitud_reprogramacion(
        self,
        id_programacion: UUID,
        accion: str,
        id_usuario: UUID | None = None,
        fecha: date | None = None,
        motivo: str = "",
    ) -> dict:
        """
        Resuelve la solicitud de reprogramacion.

        accion = 'bloquear_dia'  -> registra el dia como no disponible para el auditor.
        accion = 'retirar_auditor' -> retira al auditor de la programacion.
        """
        if accion not in {"bloquear_dia", "retirar_auditor"}:
            raise HTTPException(status_code=422, detail="Acción de resolución no válida.")
        try:
            result = await self.db.execute(text("""
                SELECT id_programacion, estado, estado_solicitud_reprogramacion,
                       id_usuario_solicitante_reprogramacion, motivo_solicitud_reprogramacion,
                       fecha_inicio, fecha_fin
                FROM programacion_visita WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            actual = result.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="La programación no existe.")
            estado_solicitud = str(actual["estado_solicitud_reprogramacion"] or "").strip().upper()
            if estado_solicitud != "PENDIENTE":
                raise HTTPException(status_code=409, detail="La visita no tiene una solicitud de reprogramación pendiente.")
            solicitante = actual["id_usuario_solicitante_reprogramacion"]
            if not id_usuario:
                id_usuario = solicitante
            if not id_usuario:
                raise HTTPException(status_code=422, detail="Debe indicar el auditor afectado.")
            detalle = ""

            if accion == "bloquear_dia":
                if not fecha:
                    raise HTTPException(status_code=422, detail="Debe indicar la fecha a bloquear.")
                if fecha < date.today():
                    raise HTTPException(status_code=422, detail="No se puede bloquear una fecha que ya pasó.")
                existe = await self.db.execute(text("""
                    SELECT 1 FROM detalle_programacion_auditor
                    WHERE id_programacion = :id AND id_usuario = :usuario
                """), {"id": str(id_programacion), "usuario": str(id_usuario)})
                if not existe.first():
                    raise HTTPException(status_code=409, detail="El auditor no está asignado a esta programación.")
                await self.db.execute(text("""
                    INSERT INTO disponibilidad_auditor (
                        id_disponibilidad, id_usuario, tipo_registro, dia_semana,
                        fecha_inicio, fecha_fin, hora_inicio, hora_fin, motivo, estado,
                        id_programacion
                    ) VALUES (
                        :id, :usuario, 'Bloqueo Fecha', :dia,
                        :fecha_inicio, :fecha_fin, NULL, NULL, :motivo, 'Activo',
                        :id_programacion
                    )
                """), {
                    "id": str(uuid4()),
                    "usuario": str(id_usuario),
                    "dia": fecha.weekday() + 1,
                    "fecha_inicio": datetime.combine(fecha, time.min),
                    "fecha_fin": datetime.combine(fecha, time.max),
                    "motivo": motivo.strip() or "Bloqueo por solicitud de reprogramación",
                    "id_programacion": str(id_programacion),
                })
                detalle = f"Se bloqueó el día {fecha.strftime('%d/%m/%Y')} para el auditor."
            else:
                existe = await self.db.execute(text("""
                    SELECT 1 FROM detalle_programacion_auditor
                    WHERE id_programacion = :id AND id_usuario = :usuario
                """), {"id": str(id_programacion), "usuario": str(id_usuario)})
                if not existe.first():
                    raise HTTPException(status_code=409, detail="El auditor no está asignado a esta programación.")
                await self.db.execute(text("""
                    DELETE FROM detalle_programacion_auditor
                    WHERE id_programacion = :id AND id_usuario = :usuario
                """), {"id": str(id_programacion), "usuario": str(id_usuario)})
                detalle = "El auditor fue retirado de la programación."

            estado_final = await self._estado_final_programacion(id_programacion)
            await self.db.execute(text("""
                UPDATE programacion_visita
                SET estado = :estado,
                    estado_solicitud_reprogramacion = 'Aprobada',
                    motivo_reprogramacion = NULL,
                    motivo_solicitud_reprogramacion = :motivo
                WHERE id_programacion = :id
            """), {
                "estado": estado_final,
                "motivo": motivo.strip() or detalle,
                "id": str(id_programacion),
            })
            await self.db.commit()
            await self._notificar_solicitante(
                id_programacion,
                solicitante,
                "Solicitud de reprogramación resuelta",
                f"{detalle} Motivo: {motivo.strip() or 'sin detalle'}.",
            )
            await self.db.commit()
            return {
                "mensaje": f"Solicitud resuelta. {detalle}",
                "estado": estado_final,
                "accion": accion,
            }
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="No fue posible resolver la solicitud.")

    async def cancelar_programacion(self, id_programacion: UUID, motivo: str):
        if not motivo.strip():
            raise HTTPException(status_code=422, detail="Debe indicar el motivo de cancelación.")
        try:
            result = await self.db.execute(text("""
                UPDATE programacion_visita
                SET estado = 'Cancelada', motivo_cancelacion = :motivo
                WHERE id_programacion = :id
                  AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN ('FINALIZADA', 'FINALIZADO')
                RETURNING id_programacion
            """), {"id": str(id_programacion), "motivo": motivo.strip()})
            if not result.first():
                raise HTTPException(status_code=404, detail="Programación no encontrada o ya finalizada.")
            # Obtener auditores para notificarles.
            detalles = await self.db.execute(text("""
                SELECT d.id_usuario FROM detalle_programacion_auditor d
                WHERE d.id_programacion = :id
            """), {"id": str(id_programacion)})
            auditores = [UUID(str(row[0])) for row in detalles.all()]
            # Se liberan los bloqueos de fecha originados por esta programacion:
            # el horario queda disponible para todos los auditores involucrados.
            bloqueos = await self.db.execute(text("""
                UPDATE disponibilidad_auditor
                SET estado = 'Cancelado'
                WHERE id_programacion = :id
                  AND UPPER(TRIM(COALESCE(estado, ''))) IN ('ACTIVO', 'ACTIVA')
                RETURNING id_disponibilidad, id_usuario, fecha_inicio, fecha_fin, motivo
            """), {"id": str(id_programacion)})
            liberados = [dict(fila) for fila in bloqueos.mappings().all()]
            for fila in liberados:
                await self._registrar_historial_disponibilidad(
                    {
                        "id_disponibilidad": fila["id_disponibilidad"],
                        "id_usuario": fila["id_usuario"],
                        "tipo_registro": "Bloqueo Fecha",
                        "fecha_inicio": fila["fecha_inicio"],
                        "fecha_fin": fila["fecha_fin"],
                        "motivo": fila["motivo"],
                        "estado": "Cancelado",
                    },
                    "LIBERADA_POR_CANCELACION",
                )
            # Notificar a cada auditor (incluyendo la liberación del horario).
            texto_liberacion = (
                f" El horario bloqueado de esa visita quedó liberado y vuelve a estar disponible."
                if liberados
                else " El horario queda libre y no bloquea su agenda."
            )
            for auditor_id in auditores:
                await self._crear_notificacion(
                    id_programacion,
                    auditor_id,
                    "Auditoría cancelada",
                    f"La auditoría programada fue cancelada. Motivo: {motivo.strip()}."
                    + texto_liberacion,
                )
            await self.db.commit()
            mensaje = (
                "Programación cancelada; el intervalo ya no bloquea la agenda y se notificó a los auditores."
            )
            if liberados:
                mensaje += (
                    f" Se liberó el horario bloqueado para {len(liberados)} auditor(es)."
                )
            return {"mensaje": mensaje, "bloqueos_liberados": len(liberados)}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="No fue posible cancelar la programación.")

    async def reprogramar_programacion(
        self,
        id_programacion: UUID,
        fecha_inicio: datetime,
        fecha_fin: datetime,
        motivo: str,
    ):
        if fecha_fin <= fecha_inicio:
            raise HTTPException(status_code=422, detail="La fecha/hora final debe ser posterior a la inicial.")
        if not motivo.strip():
            raise HTTPException(status_code=422, detail="Debe indicar el motivo de reprogramación.")
        try:
            detalles = await self.db.execute(text("""
                SELECT d.id_usuario
                FROM detalle_programacion_auditor d
                WHERE d.id_programacion = :id
                FOR UPDATE
            """), {"id": str(id_programacion)})
            auditores = [UUID(str(row[0])) for row in detalles.all()]
            if not auditores:
                raise HTTPException(status_code=404, detail="No se encontró la programación ni sus auditores.")
            for auditor_id in sorted(auditores, key=str):
                estado_result = await self.db.execute(text("""
                    SELECT estado, estado_auditor
                    FROM usuario
                    WHERE id_usuario = :id_usuario
                    FOR UPDATE
                """), {"id_usuario": str(auditor_id)})
                estado_row = estado_result.mappings().first()
                if not estado_row or str(estado_row["estado"] or "").strip().upper() != "ACTIVO" or str(
                    estado_row["estado_auditor"] or ""
                ).strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
                    raise HTTPException(status_code=409, detail="Uno de los auditores está desactivado o no aprobado.")
            for auditor_id in auditores:
                cruce = await self._buscar_cruce(auditor_id, fecha_inicio, fecha_fin, id_programacion)
                if cruce:
                    raise HTTPException(status_code=409, detail="El nuevo horario se cruza con otra auditoría del auditor.")
                if not await self._tiene_disponibilidad_fecha(auditor_id, fecha_inicio.date(), fecha_inicio.time(), fecha_fin.time()):
                    raise HTTPException(status_code=409, detail="Uno de los auditores no está disponible en la nueva fecha.")
            result = await self.db.execute(text("""
                UPDATE programacion_visita
                SET fecha_inicio = :fecha_inicio,
                    fecha_fin = :fecha_fin,
                    estado = 'Reprogramada',
                    motivo_reprogramacion = :motivo,
                    notificacion_enviada = TRUE
                WHERE id_programacion = :id
                  AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN ('CANCELADA', 'CANCELADO', 'FINALIZADA', 'FINALIZADO')
                RETURNING id_programacion
            """), {"id": str(id_programacion), "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "motivo": motivo.strip()})
            if not result.first():
                raise HTTPException(status_code=404, detail="Programación no encontrada o no reprogramable.")
            for id_usuario in auditores:
                await self._crear_notificacion(
                    UUID(str(id_programacion)), UUID(str(id_usuario)),
                    "Auditoría reprogramada",
                    f"La auditoría fue reprogramada para {fecha_inicio:%d/%m/%Y %H:%M} a {fecha_fin:%H:%M}. Motivo: {motivo.strip()}.",
                )
            await self.db.commit()
            return {"mensaje": "Programación reprogramada y notificación interna actualizada."}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al reprogramar auditoría: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible reprogramar la auditoría.") from exc

    async def editar_programacion(
        self,
        id_programacion: UUID,
        modalidad: str | None,
        ciudad_servicio: str | None,
        fecha_inicio: datetime | None = None,
        fecha_fin: datetime | None = None,
        direccion_servicio: str | None = None,
        observacion: str | None = None,
    ):
        """Edita datos de la visita y revalida si cambia el intervalo."""
        try:
            actual_result = await self.db.execute(text("""
                SELECT id_programacion, fecha_inicio, fecha_fin, estado
                FROM programacion_visita
                WHERE id_programacion = :id
                FOR UPDATE
            """), {"id": str(id_programacion)})
            actual = actual_result.mappings().first()
            if not actual:
                raise HTTPException(status_code=404, detail="Programación no encontrada.")

            inicio_nuevo = fecha_inicio or actual["fecha_inicio"]
            fin_nuevo = fecha_fin or actual["fecha_fin"]
            cambio_fechas = fecha_inicio is not None or fecha_fin is not None
            if fin_nuevo <= inicio_nuevo:
                raise HTTPException(status_code=422, detail="La fecha/hora final debe ser posterior a la inicial.")
            if str(actual["estado"] or "").strip().upper() in {"CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO"}:
                raise HTTPException(status_code=409, detail="No se puede editar una programación cancelada o finalizada.")

            if cambio_fechas:
                detalles = await self.db.execute(text("""
                    SELECT d.id_usuario
                    FROM detalle_programacion_auditor d
                    WHERE d.id_programacion = :id
                    ORDER BY d.id_usuario
                """), {"id": str(id_programacion)})
                auditores = [UUID(str(row[0])) for row in detalles.all()]
                if not auditores:
                    raise HTTPException(status_code=409, detail="La programación no tiene auditores relacionados.")

                # Bloquea los auditores en orden estable para reducir riesgos de carrera.
                for auditor_id in sorted(auditores, key=str):
                    await self.db.execute(text("""
                        SELECT id_usuario
                        FROM usuario
                        WHERE id_usuario = :id_usuario
                        FOR UPDATE
                    """), {"id_usuario": str(auditor_id)})

                for auditor_id in auditores:
                    auditor_estado = await self.db.execute(text("""
                        SELECT estado, estado_auditor
                        FROM usuario
                        WHERE id_usuario = :id_usuario
                    """), {"id_usuario": str(auditor_id)})
                    estado_row = auditor_estado.mappings().first()
                    if not estado_row or str(estado_row["estado"] or "").strip().upper() != "ACTIVO" or str(
                        estado_row["estado_auditor"] or ""
                    ).strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
                        raise HTTPException(status_code=409, detail="Uno de los auditores está desactivado o no aprobado.")
                    if not await self._tiene_disponibilidad_fecha(auditor_id, inicio_nuevo.date(), inicio_nuevo.time(), fin_nuevo.time()):
                        raise HTTPException(status_code=409, detail="Uno de los auditores no está disponible en la nueva fecha.")
                    cruce = await self._buscar_cruce(auditor_id, inicio_nuevo, fin_nuevo, id_programacion)
                    if cruce:
                        raise HTTPException(status_code=409, detail="El nuevo horario se cruza con otra auditoría del auditor.")

            await self.db.execute(text("""
                UPDATE programacion_visita
                SET modalidad = COALESCE(:modalidad, modalidad),
                    ciudad_servicio = COALESCE(:ciudad, ciudad_servicio),
                    direccion_servicio = COALESCE(:direccion, direccion_servicio),
                    fecha_inicio = :fecha_inicio,
                    fecha_fin = :fecha_fin,
                    estado = CASE WHEN :cambio_fechas THEN 'Reprogramada' ELSE estado END,
                    notificacion_enviada = CASE WHEN :cambio_fechas THEN TRUE ELSE notificacion_enviada END,
                    motivo_reprogramacion = COALESCE(NULLIF(:observacion, ''), motivo_reprogramacion)
                WHERE id_programacion = :id
            """), {
                "id": str(id_programacion),
                "modalidad": modalidad,
                "ciudad": ciudad_servicio,
                "direccion": direccion_servicio,
                "fecha_inicio": inicio_nuevo,
                "fecha_fin": fin_nuevo,
                "cambio_fechas": cambio_fechas,
                "observacion": (observacion or "").strip(),
            })

            if cambio_fechas or (observacion or "").strip():
                if "auditores" not in locals() or not auditores:
                    detalles = await self.db.execute(text("""
                        SELECT d.id_usuario
                        FROM detalle_programacion_auditor d
                        WHERE d.id_programacion = :id
                    """), {"id": str(id_programacion)})
                    auditores = [UUID(str(row[0])) for row in detalles.all()]
                for auditor_id in auditores:
                    mensaje_notif = f"La auditoría fue actualizada. "
                    if cambio_fechas:
                        mensaje_notif += f"Nueva fecha: {inicio_nuevo:%d/%m/%Y %H:%M} a {fin_nuevo:%H:%M}. "
                    if (observacion or "").strip():
                        mensaje_notif += f"Observación: {observacion.strip()}."
                    await self._crear_notificacion(
                        id_programacion,
                        auditor_id,
                        "Auditoría actualizada",
                        mensaje_notif,
                    )
            await self.db.commit()
            return {"mensaje": "Programación editada." if not cambio_fechas else "Programación reprogramada; se actualizó la agenda y la notificación interna."}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al editar programación: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail=f"No fue posible editar la programación: {type(exc).__name__}: {exc}") from exc

    async def consultar_notificaciones(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_notificacion, id_programacion, titulo, mensaje, leida, fecha_creacion
            FROM notificacion_agenda_auditor
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_creacion DESC
        """), {"id_usuario": str(id_usuario)})
        return [dict(row) for row in result.mappings().all()]

    async def notificar_programacion(self, id_programacion: UUID):
        try:
            result = await self.db.execute(text("""
                SELECT d.id_usuario, p.fecha_inicio, p.fecha_fin,
                       e.direccion AS direccion_servicio, p.ciudad_servicio, e.nombre AS empresa_nombre,
                       p.motivo_reprogramacion
                FROM programacion_visita p
                INNER JOIN detalle_programacion_auditor d ON d.id_programacion = p.id_programacion
                LEFT JOIN solicitud s ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                WHERE p.id_programacion = :id
            """), {"id": str(id_programacion)})
            rows = result.mappings().all()
            if not rows:
                raise HTTPException(status_code=404, detail="Programación no encontrada.")
            for row in rows:
                await self._crear_notificacion(
                    id_programacion, UUID(str(row["id_usuario"])),
                    "Recordatorio de auditoría programada",
                    f"Auditoría: {row['empresa_nombre'] or 'Empresa no especificada'}. "
                    f"Fecha: {row['fecha_inicio']:%d/%m/%Y %H:%M} a {row['fecha_fin']:%H:%M}. "
                    f"Lugar: {row['direccion_servicio']}, {row['ciudad_servicio']}. "
                    f"Observación: {row.get('motivo_reprogramacion') or 'Sin observación.'}",
                )
            await self.db.execute(text("""
                UPDATE programacion_visita
                SET notificacion_enviada = TRUE
                WHERE id_programacion = :id
            """), {"id": str(id_programacion)})
            await self.db.commit()
            return {"mensaje": "Notificación interna registrada para el auditor."}
        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            print(f"Error al notificar programación: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail="No fue posible crear la notificación.") from exc
