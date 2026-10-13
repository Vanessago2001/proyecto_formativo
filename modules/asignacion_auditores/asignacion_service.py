"""
REQ-AUD-001 — Asignación de Auditores.

Lógica de negocio para:
- consultar solicitudes aprobadas;
- consultar auditores elegibles;
- validar competencia;
- validar conflicto de interés;
- validar disponibilidad;
- validar cruces de agenda;
- registrar la asignación.

Se utilizan las tablas existentes de PostgreSQL.
"""

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.asignacion_auditores.asignacion_schema import (
    AsignacionAuditorCrear,
)


class AsignacionAuditorService:
    """Lógica de negocio de REQ-AUD-001."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # SOLICITUDES APROBADAS
    # ============================================================

    async def listar_solicitudes_aprobadas(self) -> list[dict]:
        """
        Obtiene las solicitudes que pueden entrar al proceso
        de asignación de auditores.
        """

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
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n
                    ON n.id_norma = s.id_norma
                WHERE s.estado = 'APROBADO'
                  AND s.deleted_at IS NULL
                ORDER BY s.fecha_creacion DESC;
                """
            )
        )

        return [dict(fila) for fila in resultado.mappings().all()]

    # ============================================================
    # DETALLE DE SOLICITUD
    # ============================================================

    async def obtener_solicitud(
        self,
        id_solicitud: UUID,
    ) -> dict:
        """Obtiene una solicitud aprobada."""

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
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n
                    ON n.id_norma = s.id_norma
                WHERE s.id_solicitud = :id_solicitud
                  AND s.deleted_at IS NULL;
                """
            ),
            {
                "id_solicitud": str(id_solicitud),
            },
        )

        solicitud = resultado.mappings().first()

        if not solicitud:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud no existe.",
            )

        solicitud = dict(solicitud)

        if solicitud["estado"] != "APROBADO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se pueden asignar auditores a "
                    "solicitudes en estado APROBADO."
                ),
            )

        return solicitud

    # ============================================================
    # AUDITORES ELEGIBLES
    # ============================================================

    async def listar_auditores_elegibles(
        self,
        id_solicitud: UUID,
        fecha_inicio: datetime,
        fecha_fin: datetime,
    ) -> list[dict]:
        """
        Devuelve los auditores que cumplen las validaciones
        disponibles actualmente en la base de datos.
        """

        solicitud = await self.obtener_solicitud(id_solicitud)

        id_empresa = solicitud["id_empresa"]
        id_norma = solicitud["id_norma"]

        resultado = await self.db.execute(
            text(
                """
                SELECT
                    u.id_usuario AS id_usuario,
                    u.nombre,
                    u.correo,

                    u.estado AS estado_usuario,
                    u.estado_auditor,

                    EXISTS (
                        SELECT 1
                        FROM competencia_auditor ca
                        WHERE ca.id_usuario = u.id_usuario
                          AND ca.id_norma = :id_norma
                          AND ca.es_vigente = TRUE
                          AND ca.estado_validacion = 'APROBADO'
                          AND CAST(:fecha_inicio AS DATE) >= ca.fecha_inicio
                          AND CAST(:fecha_fin AS DATE) <= ca.fecha_fin
                    ) AS competencia_norma,

                    EXISTS (
                        SELECT 1
                        FROM conflicto_interes ci
                        WHERE ci.id_usuario = u.id_usuario
                          AND ci.id_empresa = :id_empresa
                          AND ci.bloquea_asignacion = TRUE
                          AND ci.estado = 'Activo'
                    ) AS tiene_conflicto,

                    EXISTS (
                        SELECT 1
                        FROM disponibilidad_auditor da
                        WHERE da.id_usuario = u.id_usuario
                          AND da.estado = 'Activo'
                          AND da.fecha_inicio <= :fecha_inicio
                          AND da.fecha_fin >= :fecha_fin
                    ) AS disponible,

                    EXISTS (
                        SELECT 1
                        FROM auditores_solicitud asignado
                        WHERE asignado.id_solicitud = :id_solicitud
                          AND asignado.id_auditor = u.id_usuario
                          AND asignado.estado_asignacion IN (
                              'Activo',
                              'Asignado',
                              'Confirmado'
                          )
                    ) AS ya_asignado,

                    EXISTS (
                        SELECT 1
                        FROM detalle_programacion_auditor dpa
                        INNER JOIN programacion_visita pv
                            ON pv.id_programacion = dpa.id_programacion
                        WHERE dpa.id_usuario = u.id_usuario
                          AND pv.estado NOT IN (
                              'Cancelada',
                              'Cancelado',
                              'Finalizada'
                          )
                          AND pv.fecha_inicio < :fecha_fin
                          AND pv.fecha_fin > :fecha_inicio
                    ) AS tiene_cruce

                FROM usuario u

                WHERE u.estado = 'Activo'
                  AND u.estado_auditor = 'APROBADO'

                ORDER BY u.nombre;
                """
            ),
            {
                "id_solicitud": str(id_solicitud),
                "id_empresa": str(id_empresa),
                "id_norma": str(id_norma),
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
            },
        )

        auditores = []

        for fila in resultado.mappings().all():

            fila = dict(fila)

            competencia = bool(fila["competencia_norma"])
            conflicto = bool(fila["tiene_conflicto"])
            disponible = bool(fila["disponible"])
            ya_asignado = bool(fila["ya_asignado"])
            cruce = bool(fila["tiene_cruce"])

            elegible = (
                competencia
                and not conflicto
                and disponible
                and not ya_asignado
                and not cruce
            )

            motivos = []

            if not competencia:
                motivos.append(
                    "No tiene competencia vigente para la norma."
                )

            if conflicto:
                motivos.append(
                    "Tiene conflicto de interés con la empresa."
                )

            if not disponible:
                motivos.append(
                    "No tiene disponibilidad para el horario."
                )

            if ya_asignado:
                motivos.append(
                    "Ya está asignado a esta solicitud."
                )

            if cruce:
                motivos.append(
                    "Tiene otra auditoría en el mismo horario."
                )

            auditores.append(
                {
                    "id_usuario": fila["id_usuario"],
                    "nombre": fila["nombre"],
                    "correo": fila["correo"],
                    "estado_usuario": fila["estado_usuario"],
                    "estado_auditor": fila["estado_auditor"],
                    "competencia_norma": competencia,
                    "experiencia_sector": None,
                    "conflicto_interes": conflicto,
                    "disponible": disponible,
                    "sin_cruce_horario": not cruce,
                    "elegible": elegible,
                    "motivo": (
                        "Auditor elegible."
                        if elegible
                        else " ".join(motivos)
                    ),
                }
            )

        return auditores

    # ============================================================
    # VALIDACIÓN FINAL DEL AUDITOR
    # ============================================================

    async def validar_auditor(
        self,
        id_solicitud: UUID,
        id_auditor: UUID,
        fecha_inicio: datetime,
        fecha_fin: datetime,
    ) -> dict:
        """
        Revalida todas las condiciones justo antes de insertar
        la asignación.

        Esto evita que el frontend pueda saltarse las validaciones.
        """

        auditores = await self.listar_auditores_elegibles(
            id_solicitud=id_solicitud,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )

        auditor = next(
            (
                item
                for item in auditores
                if str(item["id_usuario"]) == str(id_auditor)
            ),
            None,
        )

        if not auditor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El auditor no existe.",
            )

        if not auditor["elegible"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El auditor no cumple las condiciones "
                    "para ser asignado. "
                    + (auditor["motivo"] or "")
                ),
            )

        return auditor

    # ============================================================
    # CREAR ASIGNACIÓN
    # ============================================================

    async def asignar(
        self,
        data: AsignacionAuditorCrear,
        usuario: dict,
    ) -> dict:
        """
        Realiza la asignación después de ejecutar nuevamente
        las validaciones.
        """

        await self.validar_auditor(
            id_solicitud=data.id_solicitud,
            id_auditor=data.id_auditor,
            fecha_inicio=data.fecha_inicio_planificada,
            fecha_fin=data.fecha_fin_planificada,
        )

        # --------------------------------------------------------
        # Evitar que existan dos auditores líderes
        # --------------------------------------------------------

        if data.rol_auditor.value == "Auditor líder":

            resultado_lider = await self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM auditores_solicitud
                    WHERE id_solicitud = :id_solicitud
                      AND especialidad = 'Auditor líder'
                      AND estado_asignacion IN (
                          'Activo',
                          'Asignado',
                          'Confirmado'
                      )
                    LIMIT 1;
                    """
                ),
                {
                    "id_solicitud": str(data.id_solicitud),
                },
            )

            if resultado_lider.first():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "La solicitud ya tiene un auditor líder."
                    ),
                )

        # --------------------------------------------------------
        # Insertar asignación
        # --------------------------------------------------------

        resultado = await self.db.execute(
            text(
                """
                INSERT INTO auditores_solicitud (
                    id_solicitud,
                    id_auditor,
                    especialidad,
                    declaracion,
                    fecha_inicio_planificada,
                    fecha_fin_planificada,
                    estado_asignacion
                )
                VALUES (
                    :id_solicitud,
                    :id_auditor,
                    :especialidad,
                    TRUE,
                    :fecha_inicio,
                    :fecha_fin,
                    'Asignado'
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
                "id_solicitud": str(data.id_solicitud),
                "id_auditor": str(data.id_auditor),
                "especialidad": data.rol_auditor.value,
                "fecha_inicio": data.fecha_inicio_planificada,
                "fecha_fin": data.fecha_fin_planificada,
            },
        )

        asignacion = dict(resultado.mappings().one())

        await self.db.commit()

        return {
            **asignacion,
            "mensaje": "Auditor asignado correctamente.",
        }

    # ============================================================
    # LISTAR ASIGNACIONES
    # ============================================================

    async def listar_asignaciones(
        self,
        id_solicitud: UUID | None = None,
    ) -> list[dict]:
        """Lista las asignaciones existentes."""

        condiciones = []
        parametros = {}

        if id_solicitud:
            condiciones.append(
                "a.id_solicitud = :id_solicitud"
            )
            parametros["id_solicitud"] = str(id_solicitud)

        where = ""

        if condiciones:
            where = "WHERE " + " AND ".join(condiciones)

        resultado = await self.db.execute(
            text(
                f"""
                SELECT
        a.id,
        a.id_solicitud,
        a.id_auditor,
        a.especialidad,
        a.declaracion,
        a.fecha_inicio_planificada,
        a.fecha_fin_planificada,
        a.estado_asignacion,

        s.numero_radicado,

        u.nombre AS auditor_nombre,
        u.correo AS auditor_correo

    FROM auditores_solicitud a

    INNER JOIN solicitud s
        ON s.id_solicitud = a.id_solicitud

    INNER JOIN usuario u
        ON u.id_usuario = a.id_auditor

    ORDER BY
        a.fecha_inicio_planificada DESC
                """
            ),
            parametros,
        )

        return [
            dict(fila)
            for fila in resultado.mappings().all()
        ]