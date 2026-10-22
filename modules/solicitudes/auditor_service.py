"""
M5 — GESTIÓN DE SOLICITUDES
Bloque 5: asignación de auditores (SOL-041 a SOL-050).

Este bloque NO duplica el módulo de asignación de auditores: trabaja sobre
las mismas tablas (`auditores_solicitud`, `historial_asignacion_auditor`,
`competencia_auditor`, `conflicto_interes`, `disponibilidad_auditor`) y solo
añade lo que la hoja de M5 pide y allí no existe: la búsqueda filtrada desde
la solicitud y el ciclo propuesta → aprobación → reasignación → cancelación.

El estado 'Propuesto' es el que distingue a M5: un auditor propuesto
(SOL-047) todavía no cuenta como asignado hasta que SOL-048 lo aprueba, y
solo entonces la agenda del otro módulo lo recoge.
"""

from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes import bitacora
from modules.solicitudes.solicitud_permissions import exigir_permisos
from modules.solicitudes.solicitud_service import SolicitudService

ESTADO_PROPUESTO = "Propuesto"
ESTADO_ASIGNADO = "Asignado"
ESTADO_CANCELADA = "Cancelada"
ESTADO_REASIGNADO = "Reasignado"

# Mientras la asignación esté en uno de estos estados, el auditor cuenta
# como ocupado en esa solicitud.
ESTADOS_VIGENTES = (
    ESTADO_PROPUESTO,
    ESTADO_ASIGNADO,
    "Agendada",
    "Programada",
    "Confirmado",
)

COLUMNAS_ASIGNACION = """
    a.id, a.id_solicitud, a.id_auditor, a.especialidad, a.estado_asignacion,
    a.fecha_inicio_planificada, a.fecha_fin_planificada,
    a.fecha_propuesta, a.fecha_asignacion, a.fecha_aprobacion, a.fecha_cancelacion,
    a.motivo_cancelacion, a.motivo_reasignacion,
    a.usuario_asigna, a.usuario_aprueba, a.usuario_cancela
"""


class AuditorSolicitudService:
    """Búsqueda de auditores competentes y ciclo de su asignación."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def _solicitud(self, id_solicitud: UUID, usuario: dict) -> dict:
        """La solicitud, comprobando que el usuario pueda verla."""
        return await self.solicitudes.consultar(id_solicitud, usuario)

    async def _asignacion(self, id_solicitud: UUID, id_asignacion: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_ASIGNACION}
                FROM auditores_solicitud a
                WHERE a.id = CAST(:id_asignacion AS UUID)
                  AND a.id_solicitud = :id_solicitud;
            """),
            {"id_asignacion": str(id_asignacion), "id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La asignación no existe para esta solicitud.",
            )
        return dict(fila)

    async def _registrar(
        self,
        id_solicitud: UUID,
        id_auditor,
        accion: str,
        usuario: dict,
        estado_anterior: str | None,
        estado_nuevo: str | None,
        motivo: str | None = None,
    ) -> None:
        """Deja la huella en la tabla del módulo y en la bitácora de M5."""
        await self.db.execute(
            text("""
                INSERT INTO historial_asignacion_auditor (
                    id_solicitud, id_auditor, accion, motivo,
                    estado_anterior, estado_nuevo, id_usuario_accion
                )
                VALUES (
                    :id_solicitud, :id_auditor, :accion, :motivo,
                    :estado_anterior, :estado_nuevo, :id_usuario
                );
            """),
            {
                "id_solicitud": str(id_solicitud),
                "id_auditor": str(id_auditor) if id_auditor else None,
                "accion": accion,
                "motivo": motivo,
                "estado_anterior": estado_anterior,
                "estado_nuevo": estado_nuevo,
                "id_usuario": str(usuario["id_usuario"]) if usuario.get("id_usuario") else None,
            },
        )
        await bitacora.registrar(
            self.db,
            id_solicitud,
            accion,
            usuario,
            {"id_auditor": str(id_auditor) if id_auditor else None, "motivo": motivo},
        )

    # ========================================================
    # SOL-041 a SOL-046 · BUSCAR Y FILTRAR CANDIDATOS
    # ========================================================

    async def buscar_candidatos(
        self,
        id_solicitud: UUID,
        usuario: dict,
        *,
        texto: str | None = None,
        filtrar_por_norma: bool = True,
        sector_iaf: str | None = None,
        ciudad: str | None = None,
        solo_disponibles: bool = False,
        excluir_conflictos: bool = True,
    ) -> dict:
        """
        SOL-041, con los filtros de SOL-042 a SOL-046.

        Cada filtro es un permiso distinto en la hoja, así que se verifica
        solo el de los filtros que realmente se piden. La respuesta marca
        cada candidato en vez de esconderlo cuando el filtro no está activo:
        quien asigna necesita ver por qué alguien no es apto.
        """
        pedidos = []
        if filtrar_por_norma:
            pedidos.append("SOL-042")
        if sector_iaf:
            pedidos.append("SOL-043")
        if ciudad:
            pedidos.append("SOL-044")
        if solo_disponibles:
            pedidos.append("SOL-045")
        if excluir_conflictos:
            pedidos.append("SOL-046")
        if pedidos:
            exigir_permisos(usuario, *pedidos)

        solicitud = await self._solicitud(id_solicitud, usuario)

        consulta = text(f"""
            WITH postulacion AS (
                -- Mismo criterio que usa el modulo de asignacion de auditores:
                -- postulacion aprobada y la cuenta habilitada como auditor.
                SELECT DISTINCT ON (p.id_usuario) p.id_usuario, p.id_postulacion
                FROM postulacion_auditor p
                WHERE p.estado = 'Aprobado'
                ORDER BY p.id_usuario, p.fecha_aprobacion DESC NULLS LAST
            )
            SELECT
                u.id_usuario,
                u.nombre,
                u.correo,
                pf.ciudad_residencia,
                pf.departamento_residencia,
                pf.calificacion_promedio,
                EXISTS (
                    SELECT 1 FROM competencia_auditor c
                    WHERE c.id_usuario = u.id_usuario
                      AND c.id_norma = :id_norma
                      AND c.es_vigente = TRUE
                      AND c.estado_validacion = 'Validado'
                ) AS competente_en_norma,
                EXISTS (
                    SELECT 1 FROM competencia_auditor c
                    WHERE c.id_usuario = u.id_usuario
                      AND (CAST(:sector_iaf AS VARCHAR) IS NULL
                           OR c.codigo_sector_iaf = CAST(:sector_iaf AS VARCHAR))
                      AND c.es_vigente = TRUE
                      AND c.estado_validacion = 'Validado'
                ) AS competente_en_sector,
                EXISTS (
                    SELECT 1 FROM conflicto_interes ci
                    WHERE ci.id_usuario = u.id_usuario
                      AND ci.id_empresa = :id_empresa
                      AND ci.bloquea_asignacion = TRUE
                      AND ci.estado = 'Activo'
                ) AS tiene_conflicto,
                EXISTS (
                    SELECT 1 FROM disponibilidad_auditor d
                    WHERE d.id_usuario = u.id_usuario
                      AND d.estado = 'Activo'
                      AND d.tipo_registro = 'Disponibilidad'
                ) AS tiene_disponibilidad,
                EXISTS (
                    SELECT 1 FROM auditores_solicitud asig
                    WHERE asig.id_solicitud = :id_solicitud
                      AND asig.id_auditor = u.id_usuario
                      AND asig.estado_asignacion = ANY(CAST(:vigentes AS VARCHAR[]))
                ) AS ya_en_la_solicitud
            FROM usuario u
            JOIN postulacion p ON p.id_usuario = u.id_usuario
            -- Un auditor puede tener mas de un perfil (uno por postulacion);
            -- sin esto saldria repetido en la lista.
            LEFT JOIN LATERAL (
                SELECT ciudad_residencia, departamento_residencia, calificacion_promedio
                FROM perfil_auditor
                WHERE id_usuario = u.id_usuario
                ORDER BY (id_postulacion = p.id_postulacion) DESC
                LIMIT 1
            ) pf ON TRUE
            WHERE u.estado = 'Activo'
              AND u.estado_auditor = 'Activo'
              AND (CAST(:texto AS VARCHAR) IS NULL
                   OR u.nombre ILIKE '%' || CAST(:texto AS VARCHAR) || '%'
                   OR u.correo ILIKE '%' || CAST(:texto AS VARCHAR) || '%')
              AND (CAST(:ciudad AS VARCHAR) IS NULL
                   OR pf.ciudad_residencia ILIKE CAST(:ciudad AS VARCHAR))
            ORDER BY u.nombre;
        """)

        resultado = await self.db.execute(
            consulta,
            {
                "id_norma": str(solicitud["id_norma"]) if solicitud.get("id_norma") else None,
                "id_empresa": str(solicitud["id_empresa"]),
                "id_solicitud": str(id_solicitud),
                "sector_iaf": sector_iaf,
                "ciudad": ciudad,
                "texto": texto,
                "vigentes": list(ESTADOS_VIGENTES),
            },
        )

        candidatos = []
        for fila in resultado.mappings().all():
            candidato = dict(fila)
            motivos = []
            if filtrar_por_norma and not candidato["competente_en_norma"]:
                motivos.append("No tiene competencia vigente en la norma solicitada.")
            if sector_iaf and not candidato["competente_en_sector"]:
                motivos.append(f"No tiene competencia en el sector IAF {sector_iaf}.")
            if excluir_conflictos and candidato["tiene_conflicto"]:
                motivos.append("Tiene un conflicto de interés con la empresa.")
            if solo_disponibles and not candidato["tiene_disponibilidad"]:
                motivos.append("No registró disponibilidad.")
            if candidato["ya_en_la_solicitud"]:
                motivos.append("Ya está en esta solicitud.")

            candidato["apto"] = not motivos
            candidato["motivos"] = motivos
            candidatos.append(candidato)

        return {
            "id_solicitud": str(id_solicitud),
            "norma": solicitud.get("id_norma"),
            "filtros": {
                "norma": filtrar_por_norma,
                "sector_iaf": sector_iaf,
                "ciudad": ciudad,
                "solo_disponibles": solo_disponibles,
                "excluir_conflictos": excluir_conflictos,
                "texto": texto,
            },
            "total": len(candidatos),
            "aptos": sum(1 for c in candidatos if c["apto"]),
            "candidatos": candidatos,
        }

    # ========================================================
    # CONSULTA DE LAS ASIGNACIONES DE LA SOLICITUD
    # ========================================================

    async def listar(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        await self._solicitud(id_solicitud, usuario)
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_ASIGNACION},
                       COALESCE(u.nombre, u.correo) AS auditor,
                       u.correo AS auditor_correo
                FROM auditores_solicitud a
                LEFT JOIN usuario u ON u.id_usuario = a.id_auditor
                WHERE a.id_solicitud = :id_solicitud
                ORDER BY a.fecha_propuesta DESC NULLS LAST, a.id DESC;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-047 · PROPONER AUDITOR
    # ========================================================

    async def proponer(
        self,
        id_solicitud: UUID,
        id_auditor: UUID,
        usuario: dict,
        *,
        especialidad: str | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
    ) -> dict:
        solicitud = await self._solicitud(id_solicitud, usuario)

        repetida = await self.db.execute(
            text("""
                SELECT id FROM auditores_solicitud
                WHERE id_solicitud = :id_solicitud
                  AND id_auditor = :id_auditor
                  AND estado_asignacion = ANY(CAST(:vigentes AS VARCHAR[]));
            """),
            {
                "id_solicitud": str(id_solicitud),
                "id_auditor": str(id_auditor),
                "vigentes": list(ESTADOS_VIGENTES),
            },
        )
        if repetida.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ese auditor ya está propuesto o asignado en esta solicitud.",
            )

        conflicto = await self.db.execute(
            text("""
                SELECT descripcion FROM conflicto_interes
                WHERE id_usuario = :id_auditor
                  AND id_empresa = :id_empresa
                  AND bloquea_asignacion = TRUE
                  AND estado = 'Activo'
                LIMIT 1;
            """),
            {"id_auditor": str(id_auditor), "id_empresa": str(solicitud["id_empresa"])},
        )
        motivo_conflicto = conflicto.scalar()
        if motivo_conflicto is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El auditor tiene un conflicto de interés declarado con la "
                    f"empresa: {motivo_conflicto}"
                ),
            )

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO auditores_solicitud (
                    id_solicitud, id_auditor, especialidad, estado_asignacion,
                    fecha_inicio_planificada, fecha_fin_planificada,
                    fecha_propuesta, usuario_asigna
                )
                VALUES (
                    :id_solicitud, :id_auditor, :especialidad, :estado,
                    :fecha_inicio, :fecha_fin, CURRENT_TIMESTAMP, :usuario
                )
                RETURNING {COLUMNAS_ASIGNACION.replace('a.', '')};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "id_auditor": str(id_auditor),
                "especialidad": especialidad,
                "estado": ESTADO_PROPUESTO,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        asignacion = dict(resultado.mappings().first())

        await self._registrar(
            id_solicitud, id_auditor, "Auditor propuesto", usuario,
            None, ESTADO_PROPUESTO,
        )
        await self.db.commit()
        return asignacion

    # ========================================================
    # SOL-048 · APROBAR LA ASIGNACIÓN
    # ========================================================

    async def aprobar(self, id_solicitud: UUID, id_asignacion: UUID, usuario: dict) -> dict:
        await self._solicitud(id_solicitud, usuario)
        asignacion = await self._asignacion(id_solicitud, id_asignacion)

        if asignacion["estado_asignacion"] != ESTADO_PROPUESTO:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La asignación está '{asignacion['estado_asignacion']}'. "
                    "Solo se aprueba una propuesta."
                ),
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE auditores_solicitud
                SET estado_asignacion = :estado,
                    fecha_aprobacion = CURRENT_TIMESTAMP,
                    fecha_asignacion = CURRENT_TIMESTAMP,
                    usuario_aprueba = :usuario
                WHERE id = CAST(:id_asignacion AS UUID)
                RETURNING {COLUMNAS_ASIGNACION.replace('a.', '')};
            """),
            {
                "estado": ESTADO_ASIGNADO,
                "usuario": str(usuario["id_usuario"]),
                "id_asignacion": str(id_asignacion),
            },
        )
        aprobada = dict(resultado.mappings().first())

        await self._registrar(
            id_solicitud, asignacion["id_auditor"], "Asignación aprobada", usuario,
            ESTADO_PROPUESTO, ESTADO_ASIGNADO,
        )
        await self.db.commit()
        return aprobada

    # ========================================================
    # SOL-050 · CANCELAR LA ASIGNACIÓN
    # ========================================================

    async def cancelar(
        self, id_solicitud: UUID, id_asignacion: UUID, motivo: str, usuario: dict
    ) -> dict:
        await self._solicitud(id_solicitud, usuario)
        asignacion = await self._asignacion(id_solicitud, id_asignacion)

        if asignacion["estado_asignacion"] == ESTADO_CANCELADA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La asignación ya estaba cancelada.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE auditores_solicitud
                SET estado_asignacion = :estado,
                    motivo_cancelacion = :motivo,
                    fecha_cancelacion = CURRENT_TIMESTAMP,
                    usuario_cancela = :usuario
                WHERE id = CAST(:id_asignacion AS UUID)
                RETURNING {COLUMNAS_ASIGNACION.replace('a.', '')};
            """),
            {
                "estado": ESTADO_CANCELADA,
                "motivo": motivo,
                "usuario": str(usuario["id_usuario"]),
                "id_asignacion": str(id_asignacion),
            },
        )
        cancelada = dict(resultado.mappings().first())

        await self._registrar(
            id_solicitud, asignacion["id_auditor"], "Asignación cancelada", usuario,
            asignacion["estado_asignacion"], ESTADO_CANCELADA, motivo,
        )
        await self.db.commit()
        return cancelada

    # ========================================================
    # SOL-049 · REASIGNAR AUDITOR
    # ========================================================

    async def reasignar(
        self,
        id_solicitud: UUID,
        id_asignacion: UUID,
        id_nuevo_auditor: UUID,
        motivo: str,
        usuario: dict,
    ) -> dict:
        """
        Cierra la asignación vigente y deja propuesta la del reemplazo, en una
        sola operación: la solicitud nunca se queda sin auditor por un fallo
        a mitad de camino.
        """
        solicitud = await self._solicitud(id_solicitud, usuario)
        asignacion = await self._asignacion(id_solicitud, id_asignacion)

        if asignacion["estado_asignacion"] in (ESTADO_CANCELADA, ESTADO_REASIGNADO):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La asignación está '{asignacion['estado_asignacion']}' y no se puede reasignar.",
            )
        if str(asignacion["id_auditor"]) == str(id_nuevo_auditor):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El auditor de reemplazo es el mismo que ya estaba asignado.",
            )

        conflicto = await self.db.execute(
            text("""
                SELECT 1 FROM conflicto_interes
                WHERE id_usuario = :id_auditor AND id_empresa = :id_empresa
                  AND bloquea_asignacion = TRUE AND estado = 'Activo'
                LIMIT 1;
            """),
            {"id_auditor": str(id_nuevo_auditor), "id_empresa": str(solicitud["id_empresa"])},
        )
        if conflicto.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El auditor de reemplazo tiene un conflicto de interés con la empresa.",
            )

        await self.db.execute(
            text("""
                UPDATE auditores_solicitud
                SET estado_asignacion = :estado,
                    motivo_reasignacion = :motivo,
                    fecha_cancelacion = CURRENT_TIMESTAMP,
                    usuario_cancela = :usuario
                WHERE id = CAST(:id_asignacion AS UUID);
            """),
            {
                "estado": ESTADO_REASIGNADO,
                "motivo": motivo,
                "usuario": str(usuario["id_usuario"]),
                "id_asignacion": str(id_asignacion),
            },
        )

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO auditores_solicitud (
                    id_solicitud, id_auditor, especialidad, estado_asignacion,
                    fecha_inicio_planificada, fecha_fin_planificada,
                    fecha_propuesta, usuario_asigna, motivo_reasignacion
                )
                VALUES (
                    :id_solicitud, :id_auditor, :especialidad, :estado,
                    :fecha_inicio, :fecha_fin, CURRENT_TIMESTAMP, :usuario, :motivo
                )
                RETURNING {COLUMNAS_ASIGNACION.replace('a.', '')};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "id_auditor": str(id_nuevo_auditor),
                "especialidad": asignacion["especialidad"],
                "estado": ESTADO_PROPUESTO,
                "fecha_inicio": asignacion["fecha_inicio_planificada"],
                "fecha_fin": asignacion["fecha_fin_planificada"],
                "usuario": str(usuario["id_usuario"]),
                "motivo": motivo,
            },
        )
        nueva = dict(resultado.mappings().first())

        await self._registrar(
            id_solicitud, asignacion["id_auditor"], "Auditor reasignado", usuario,
            asignacion["estado_asignacion"], ESTADO_REASIGNADO, motivo,
        )
        await self._registrar(
            id_solicitud, id_nuevo_auditor, "Auditor propuesto en reemplazo", usuario,
            None, ESTADO_PROPUESTO, motivo,
        )
        await self.db.commit()
        return {"reemplazada": str(id_asignacion), "nueva": nueva, "motivo": motivo}

    # ========================================================
    # HISTORIAL DE LAS ASIGNACIONES
    # ========================================================

    async def historial(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        await self._solicitud(id_solicitud, usuario)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.accion, h.motivo, h.estado_anterior,
                       h.estado_nuevo, h.fecha,
                       COALESCE(ua.nombre, ua.correo) AS auditor,
                       COALESCE(uq.nombre, uq.correo) AS registrado_por
                FROM historial_asignacion_auditor h
                LEFT JOIN usuario ua ON ua.id_usuario = h.id_auditor
                LEFT JOIN usuario uq ON uq.id_usuario = h.id_usuario_accion
                WHERE h.id_solicitud = :id_solicitud
                ORDER BY h.fecha, h.id_historial;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]
