"""
REQ-AUD-001 — Asignación de Auditores.

La asignación relaciona auditor, solicitud y rol. Las fechas, la disponibilidad
por intervalo y los cruces horarios se validan al programar desde Agenda.
"""

import re
from datetime import date
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.filtros_ubicacion import condiciones_ubicacion_solicitud, patron_contiene, sql_comparable
from modules.solicitudes import estado_solicitud as estados
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

# Fragmentos SQL sobre el alias ``a`` (auditores_solicitud). Se comparan sin
# importar mayúsculas ni espacios: una asignación cancelada o reasignada no
# cuenta, sin importar cómo se haya escrito su estado.
SQL_ASIGNACION_ACTIVA = (
    "UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) IN "
    "('AGENDADA', 'PROGRAMADA', 'CONFIRMADO', 'CONFIRMADA', 'ASIGNADO', 'ASIGNADA', 'ACTIVO', 'ACTIVA')"
)
SQL_ROL_LIDER = (
    "LOWER(TRIM(COALESCE(a.especialidad, ''))) IN ('auditor líder', 'auditor lider')"
)
# Regla de equipo: una solicitud admite varios auditores (líder, experto
# técnico, auditor integral, observador) pero un solo auditor líder, y es el
# único rol obligatorio. Por eso el equipo queda "completo" en cuanto tiene un
# auditor líder activo: la solicitud deja de ofrecerse para asignar y los
# demás integrantes se suman desde Agenda al programar la visita.
SQL_SOLICITUD_CON_EQUIPO_COMPLETO = f"""EXISTS (
    SELECT 1
    FROM auditores_solicitud a
    WHERE a.id_solicitud = s.id_solicitud
      AND {SQL_ASIGNACION_ACTIVA}
      AND {SQL_ROL_LIDER}
)"""


# Conflicto de interés activo y bloqueante entre el auditor de la asignación
# (alias ``a``) y la empresa de su solicitud (alias ``s``). Un auditor no puede
# seguir asignado a una empresa con la que declaró conflicto.
SQL_CONFLICTO_ASIGNACION = """EXISTS (
    SELECT 1
    FROM conflicto_interes ci
    WHERE ci.id_usuario = a.id_auditor
      AND ci.id_empresa = s.id_empresa
      AND ci.bloquea_asignacion = TRUE
      AND UPPER(TRIM(COALESCE(ci.estado, ''))) = 'ACTIVO'
)"""

ESTADOS_VISITA_TERMINALES = (
    "CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO", "EJECUTADA", "EJECUTADO",
)
SQL_VISITA_NO_TERMINAL = (
    "UPPER(TRIM(COALESCE(pv.estado, ''))) NOT IN ("
    + ", ".join(f"'{e}'" for e in ESTADOS_VISITA_TERMINALES)
    + ")"
)
ACCION_RETIRO_CONFLICTO = "RETIRO_POR_CONFLICTO_INTERES"


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
        -- El conflicto de interés es de la persona, no de una postulación:
        -- los que se declaran después de aprobado el registro (pantalla
        -- "Conflictos registrados") quedan sin id_postulacion o enlazados a
        -- otra postulación, y aun así deben bloquear la asignación.
        EXISTS (
            SELECT 1
            FROM conflicto_interes ci
            WHERE ci.id_usuario = u.id_usuario
              AND ci.id_empresa = :id_empresa
              AND ci.bloquea_asignacion = TRUE
              AND UPPER(TRIM(COALESCE(ci.estado, ''))) = 'ACTIVO'
        ) AS conflicto_interes,
        EXISTS (
            SELECT 1
            FROM auditores_solicitud a
            WHERE a.id_solicitud = :id_solicitud
              AND a.id_auditor = u.id_usuario
              AND """ + SQL_ASIGNACION_ACTIVA + """
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
        departamento: str | None = None,
        pais: str | None = None,
    ) -> dict:
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        buscar = (buscar or "").strip() or None
        ciudad = (ciudad or "").strip() or None
        norma = (norma or "").strip() or None
        sector = (sector or "").strip() or None

        # El estado se compara contra el catalogo de M5: la tabla llego a
        # tener 'APROBADO' y 'Aprobada', y un literal exacto dejaba fuera a
        # las solicitudes escritas con la otra grafia.
        filtros = [
            f"s.estado = '{estados.APROBADA}'",
            "s.deleted_at IS NULL",
            # Las que ya tienen el equipo completo (auditor líder activo) no se
            # vuelven a ofrecer. Las que solo tienen asignaciones canceladas sí.
            "NOT " + SQL_SOLICITUD_CON_EQUIPO_COMPLETO,
        ]
        params: dict = {}
        if buscar:
            filtros.append(
                "(COALESCE(s.numero_radicado, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%' "
                "OR COALESCE(e.nombre, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%' "
                "OR COALESCE(n.codigo, '') ILIKE '%' || CAST(:buscar AS TEXT) || '%')"
            )
            params["buscar"] = buscar
        # Ubicación: sin distinguir mayúsculas ni tildes y por coincidencia
        # parcial. La ciudad puede ser la de la empresa o la de alguna sede
        # incluida en la solicitud; departamento y país solo existen en las sedes.
        filtros_lugar, params_lugar = condiciones_ubicacion_solicitud(ciudad, departamento, pais)
        filtros += filtros_lugar
        params.update(params_lugar)
        if desde:
            filtros.append("CAST(s.fecha AS DATE) >= :desde")
            params["desde"] = desde
        if hasta:
            filtros.append("CAST(s.fecha AS DATE) <= :hasta")
            params["hasta"] = hasta
        if norma:
            # Búsqueda parcial: "9001", "iso 9001" o "ISO-9001" encuentran la
            # norma ISO-9001 (se ignoran guiones, espacios y mayúsculas).
            filtros.append(
                "(regexp_replace(LOWER(COALESCE(n.codigo, '')), '[^a-z0-9]', '', 'g')"
                " LIKE '%' || :norma || '%'"
                " OR regexp_replace(LOWER(COALESCE(n.nombre, '')), '[^a-z0-9]', '', 'g')"
                " LIKE '%' || :norma || '%')"
            )
            params["norma"] = re.sub(r"[^a-z0-9]", "", norma.strip().lower())
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
                    (
                        SELECT COUNT(*)
                        FROM auditores_solicitud a
                        WHERE a.id_solicitud = s.id_solicitud
                          AND {SQL_ASIGNACION_ACTIVA}
                    ) AS auditores_asignados,
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

    async def sugerencias_ubicacion(self) -> dict:
        """Valores existentes (DISTINCT) para el autocompletado de los filtros."""
        consulta = text(
            """
            SELECT 'solicitudes' AS grupo, 'ciudades' AS campo, ciudad AS valor FROM empresa WHERE ciudad IS NOT NULL
            UNION SELECT 'solicitudes', 'ciudades', ciudad FROM sede_empresa WHERE ciudad IS NOT NULL
            UNION SELECT 'solicitudes', 'departamentos', departamento FROM sede_empresa WHERE departamento IS NOT NULL
            UNION SELECT 'solicitudes', 'paises', pais FROM sede_empresa WHERE pais IS NOT NULL
            UNION SELECT 'auditores', 'ciudades', ciudad_residencia FROM perfil_auditor WHERE ciudad_residencia IS NOT NULL
            UNION SELECT 'auditores', 'departamentos', departamento_residencia FROM perfil_auditor
                  WHERE departamento_residencia IS NOT NULL
            """
        )
        salida = {
            "solicitudes": {"ciudades": [], "departamentos": [], "paises": []},
            "auditores": {"ciudades": [], "departamentos": []},
        }
        for fila in (await self.db.execute(consulta)).mappings().all():
            valor = str(fila["valor"] or "").strip()
            if valor:
                salida[fila["grupo"]][fila["campo"]].append(valor)
        for grupo in salida.values():
            for campo, valores in grupo.items():
                grupo[campo] = sorted(set(valores), key=str.lower)
        return salida

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
        # La base guarda el canon 'Aprobada'; el literal 'APROBADO' bloqueaba toda asignación.
        if not estados.es(solicitud["estado"], estados.APROBADA):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se pueden asignar auditores a solicitudes en estado Aprobada.",
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
        departamento: str | None = None,
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
            # Patrones LIKE normalizados (sin tildes ni mayúsculas).
            "ciudad": patron_contiene(ciudad),
            "departamento": patron_contiene(departamento),
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
                OR """ + sql_comparable("ciudad_residencia") + """ LIKE CAST(:ciudad AS TEXT) ESCAPE '\\'
            )
              AND (
                CAST(:departamento AS TEXT) IS NULL
                OR """ + sql_comparable("departamento_residencia") + """ LIKE CAST(:departamento AS TEXT) ESCAPE '\\'
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

    async def motivos_competencia(self, id_auditor: UUID, solicitud: dict) -> list[str]:
        """Razones concretas por las que no hay competencia vigente en la norma."""
        norma = solicitud.get("norma_codigo") or solicitud.get("norma_nombre") or "de la solicitud"
        resultado = await self.db.execute(
            text(
                """
                SELECT ca.estado_validacion, ca.es_vigente, ca.fecha_inicio, ca.fecha_fin,
                       ca.codigo_sector_iaf
                FROM competencia_auditor ca
                WHERE ca.id_usuario = :id_auditor
                  AND ca.id_norma = :id_norma
                ORDER BY ca.fecha_fin DESC NULLS LAST
                """
            ),
            {"id_auditor": str(id_auditor), "id_norma": str(solicitud["id_norma"])},
        )
        filas = [dict(f) for f in resultado.mappings().all()]
        if not filas:
            return [f"No tiene ninguna competencia registrada en la norma {norma}."]
        hoy = date.today()
        motivos = []
        for fila in filas:
            sector = f" (sector IAF {fila['codigo_sector_iaf']})" if fila.get("codigo_sector_iaf") else ""
            inicio = fila.get("fecha_inicio")
            fin = fila.get("fecha_fin")
            inicio = inicio.date() if hasattr(inicio, "date") and callable(inicio.date) else inicio
            fin = fin.date() if hasattr(fin, "date") and callable(fin.date) else fin
            if (fila.get("estado_validacion") or "") != "Validado":
                motivos.append(
                    f"Su competencia en la norma {norma}{sector} no está validada "
                    f"(estado: {fila.get('estado_validacion') or 'sin validar'})."
                )
            elif fin and fin < hoy:
                motivos.append(f"Su competencia en la norma {norma}{sector} venció el {fin.strftime('%d/%m/%Y')}.")
            elif inicio and inicio > hoy:
                motivos.append(
                    f"Su competencia en la norma {norma}{sector} empieza a regir el {inicio.strftime('%d/%m/%Y')}."
                )
            elif not fila.get("es_vigente"):
                motivos.append(f"Su competencia en la norma {norma}{sector} está marcada como no vigente.")
        return motivos or [f"No tiene competencia vigente y validada en la norma {norma}."]

    async def elegibilidad(self, id_solicitud: UUID, id_auditor: UUID) -> dict:
        """Detalle para el modal "Asignar de todas formas": razones y si es forzable."""
        try:
            await self.validar_auditor(id_solicitud, id_auditor)
            return {"elegible": True, "forzable": False, "motivos": [], "bloqueante": None}
        except HTTPException as error:
            info = getattr(error, "elegibilidad", None)
            if info is None:
                return {"elegible": False, "forzable": False, "motivos": [str(error.detail)], "bloqueante": str(error.detail)}
            return info

    async def validar_auditor(
        self,
        id_solicitud: UUID,
        id_auditor: UUID,
        ignorar_ya_asignado: bool = False,
        forzar: bool = False,
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
            "nombre": fila.get("nombre"),
            "competencia_norma": competencia_norma,
            "conflicto_interes": conflicto,
            "ya_asignado": ya_asignado,
            "elegible": elegible,
            "forzado": False,
            "motivos": [],
        }
        if auditor["elegible"]:
            return auditor

        # Bloqueantes: nunca se pueden forzar.
        bloqueante = None
        if conflicto:
            bloqueante = (
                "Tiene un conflicto de interés activo con la empresa. Por imparcialidad no se "
                "puede asignar, ni siquiera de forma excepcional."
            )
        elif ya_asignado and not ignorar_ya_asignado:
            bloqueante = "Ya está asignado a esta solicitud."
        motivos = [] if competencia_norma else await self.motivos_competencia(id_auditor, solicitud)
        if bloqueante:
            motivos.append(bloqueante)
        info = {"elegible": False, "forzable": bloqueante is None, "motivos": motivos, "bloqueante": bloqueante}

        if bloqueante is None and forzar:
            # Solo falta la competencia: el Coordinador decidió asignarlo igual.
            auditor["forzado"] = True
            auditor["motivos"] = motivos
            return auditor

        error = HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El auditor no cumple las condiciones para ser asignado. " + " ".join(motivos)
                + ("" if bloqueante else " Si aun así desea asignarlo, use \"Asignar de todas formas\" con una justificación.")
            ),
        )
        error.elegibilidad = info
        raise error

    async def validar_equipo_incompleto(self, id_solicitud: UUID) -> None:
        """409 si la solicitud ya tiene su equipo completo (auditor líder activo).

        Así el backend no depende de que la pantalla oculte la solicitud.
        """
        resultado = await self.db.execute(
            text(
                f"""
                SELECT s.numero_radicado, u.nombre AS lider_nombre
                FROM auditores_solicitud a
                INNER JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                LEFT JOIN usuario u ON u.id_usuario = a.id_auditor
                WHERE a.id_solicitud = :id_solicitud
                  AND {SQL_ASIGNACION_ACTIVA}
                  AND {SQL_ROL_LIDER}
                LIMIT 1
                """
            ),
            {"id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()
        if fila:
            radicado = fila.get("numero_radicado") or "seleccionada"
            lider = fila.get("lider_nombre") or "ya registrado"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La solicitud {radicado} ya tiene su equipo asignado "
                    f"(auditor líder: {lider}). Para sumar auditores hágalo desde "
                    "Agenda al programar la visita, o cancele primero la asignación actual."
                ),
            )

    # ------------------------------------------------------------------
    # CREAR ASIGNACIÓN SIN FECHAS
    # ------------------------------------------------------------------
    async def asignar(self, data: AsignacionAuditorCrear, usuario: dict, origen_forzado: str = "Coordinador") -> dict:

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

        await self.validar_equipo_incompleto(data.id_solicitud)
        validado = await self.validar_auditor(data.id_solicitud, data.id_auditor, forzar=data.forzar)

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
            if validado.get("forzado"):
                # Trazabilidad: quién forzó, cuándo, por qué no era elegible y
                # la justificación (tabla existente historial_asignacion_auditor).
                await self.db.execute(
                    text(
                        """
                        INSERT INTO historial_asignacion_auditor (
                            id_historial, id_solicitud, id_auditor, accion, motivo,
                            estado_anterior, estado_nuevo, id_usuario_accion, fecha,
                            id_asignacion, origen
                        ) VALUES (
                            :id, :id_solicitud, :id_auditor, 'ASIGNACION_FORZADA', :motivo,
                            NULL, :estado_nuevo, :id_usuario, CURRENT_TIMESTAMP,
                            :id_asignacion, :origen
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "id_solicitud": str(data.id_solicitud),
                        "id_auditor": str(data.id_auditor),
                        "motivo": (
                            "Asignado sin cumplir la elegibilidad. Razones: "
                            + " ".join(validado.get("motivos") or [])
                            + " Justificación: " + (data.justificacion or "").strip()
                        ),
                        "estado_nuevo": ESTADO_ASIGNACION_INICIAL,
                        "id_usuario": str(usuario.get("id_usuario")) if usuario.get("id_usuario") else None,
                        "id_asignacion": str(asignacion["id"]),
                        "origen": origen_forzado[:60],
                    },
                )
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
            "forzado": bool(validado.get("forzado")),
            "mensaje": (
                "Auditor asignado de forma excepcional (no elegible); quedó registrado con su justificación. "
                if validado.get("forzado") else "Auditor asignado correctamente. "
            ) + "La fecha y el horario se definirán desde Agenda.",
        }

    # ------------------------------------------------------------------
    # LISTAR ASIGNACIONES
    # ------------------------------------------------------------------
    async def listar_asignaciones(
        self,
        id_solicitud: UUID | None = None,
        empresas: list[str] | None = None,
    ) -> list[dict]:
        """Lista las asignaciones. Con ``empresas`` solo las de esas empresas."""
        condiciones = []
        parametros: dict = {}
        if id_solicitud:
            condiciones.append("a.id_solicitud = :id_solicitud")
            parametros["id_solicitud"] = str(id_solicitud)
        if empresas is not None:
            if not empresas:
                return []
            condiciones.append("CAST(s.id_empresa AS TEXT) = ANY(:empresas)")
            parametros["empresas"] = empresas
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
                    u.correo AS auditor_correo,
                    -- Conflicto de interés activo con la empresa: la asignación
                    -- debe reasignarse (se marca en la pantalla).
                    {SQL_CONFLICTO_ASIGNACION} AS conflicto_interes
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
                      -- Una asignación cancelada no hereda la visita de otro
                      -- equipo (se mostraba como "Confirmada").
                      AND UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) NOT IN
                          ('CANCELADA', 'CANCELADO', 'REASIGNADO', 'REASIGNADA')
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

    async def cancelar_asignacion(
        self,
        id_asignacion: UUID,
        confirmar: bool = True,
        usuario: dict | None = None,
        motivo: str | None = None,
    ) -> dict:
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

        # Usa las columnas que ya existen en auditores_solicitud para dejar
        # quién canceló, cuándo y por qué.
        result = await self.db.execute(
            text(
                """
                UPDATE auditores_solicitud
                SET estado_asignacion = 'Cancelada',
                    fecha_cancelacion = CURRENT_TIMESTAMP,
                    usuario_cancela = COALESCE(:usuario_cancela, usuario_cancela),
                    motivo_cancelacion = COALESCE(:motivo, motivo_cancelacion)
                WHERE id = :id
                RETURNING id
                """
            ),
            {
                "id": str(id_asignacion),
                "usuario_cancela": str(usuario["id_usuario"]) if usuario and usuario.get("id_usuario") else None,
                "motivo": motivo,
            },
        )
        if not result.first():
            raise HTTPException(status_code=404, detail="La asignación no existe.")
        if confirmar:
            await self.db.commit()
        return {"mensaje": "Asignación cancelada correctamente."}

    # ------------------------------------------------------------
    # Conflicto de interés sobre asignaciones ya hechas
    # ------------------------------------------------------------

    async def asignaciones_activas_con_empresa(self, id_auditor, id_empresa) -> list[dict]:
        """Asignaciones activas del auditor en solicitudes de esa empresa."""
        resultado = await self.db.execute(
            text(f"""
                SELECT a.id, a.id_solicitud, s.numero_radicado, a.especialidad,
                       u.nombre AS auditor_nombre, e.nombre AS empresa_nombre
                FROM auditores_solicitud a
                INNER JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                INNER JOIN usuario u ON u.id_usuario = a.id_auditor
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                WHERE a.id_auditor = :id_auditor
                  AND s.id_empresa = :id_empresa
                  AND {SQL_ASIGNACION_ACTIVA}
                ORDER BY s.numero_radicado
            """),
            {"id_auditor": str(id_auditor), "id_empresa": str(id_empresa)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def avisar_conflicto_en_asignaciones(self, id_auditor, id_empresa) -> list[dict]:
        """Al registrar un conflicto activo, avisa al Coordinador si el auditor
        ya está asignado en solicitudes de esa empresa.

        Crea una notificación (tabla ``notificacion``) para cada Coordinador
        activo. No hace commit: lo hace quien registra el conflicto.
        """
        afectadas = await self.asignaciones_activas_con_empresa(id_auditor, id_empresa)
        if not afectadas:
            return []
        radicados = ", ".join(
            str(fila.get("numero_radicado") or fila["id_solicitud"]) for fila in afectadas
        )
        auditor = afectadas[0].get("auditor_nombre") or "Un auditor"
        empresa = afectadas[0].get("empresa_nombre") or "la empresa"
        mensaje = (
            f"Conflicto de interés: {auditor} tiene un conflicto activo con {empresa} "
            f"y sigue asignado en {radicados}. Debe reasignarse desde Asignación de auditores."
        )
        if len(mensaje) > 255:  # notificacion.mensaje es VARCHAR(255)
            mensaje = mensaje[:252].rstrip() + "..."
        await self.db.execute(
            text("""
                INSERT INTO notificacion (id_notificacion, id_usuario, asunto, mensaje, estado, fecha_envio)
                SELECT gen_random_uuid(), u.id_usuario, :asunto, :mensaje, 'Pendiente', CURRENT_DATE
                FROM usuario u
                INNER JOIN rol r ON r.id_rol = u.rol_id
                WHERE LOWER(TRIM(r.nombre)) = 'coordinador'
                  AND UPPER(TRIM(COALESCE(u.estado, ''))) = 'ACTIVO'
            """),
            {"asunto": "Conflicto de interés en asignaciones", "mensaje": mensaje},
        )
        return afectadas

    async def retirar_por_conflicto(
        self,
        id_asignacion: UUID,
        usuario: dict,
        motivo: str | None = None,
    ) -> dict:
        """Cancela la asignación de un auditor con conflicto de interés activo
        con la empresa, aunque la solicitud ya tenga visita programada.

        Si el auditor está en visitas no terminadas de la solicitud, lo quita
        de ellas con las reglas de Agenda: libera sus bloqueos de fecha de esa
        visita (con historial de disponibilidad), le notifica y recalcula el
        estado de la visita. La visita se conserva para agregar otro auditor
        desde Agenda. Queda registro en historial_asignacion_auditor.
        """
        from modules.agenda_auditor.agenda_service import AgendaAuditorService

        actor = str(usuario["id_usuario"]) if usuario and usuario.get("id_usuario") else None
        try:
            fila = (await self.db.execute(
                text(f"""
                    SELECT a.id, a.id_solicitud, a.id_auditor, a.estado_asignacion,
                           s.numero_radicado, e.nombre AS empresa_nombre,
                           {SQL_CONFLICTO_ASIGNACION} AS conflicto_interes,
                           {SQL_ASIGNACION_ACTIVA} AS activa
                    FROM auditores_solicitud a
                    INNER JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                    LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                    WHERE a.id = :id
                    FOR UPDATE OF a
                """),
                {"id": str(id_asignacion)},
            )).mappings().first()
            if not fila:
                raise HTTPException(status_code=404, detail="La asignación no existe.")
            if not fila["activa"]:
                raise HTTPException(status_code=409, detail="La asignación ya no está activa.")
            if not fila["conflicto_interes"]:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "El auditor no tiene un conflicto de interés activo con la empresa. "
                        "Use 'Cancelar asignación'."
                    ),
                )

            motivo_final = f"Conflicto de interés con {fila['empresa_nombre'] or 'la empresa'}."
            if motivo and motivo.strip():
                motivo_final += " " + motivo.strip()

            id_solicitud = str(fila["id_solicitud"])
            id_auditor = str(fila["id_auditor"])
            agenda = AgendaAuditorService(self.db)

            visitas = (await self.db.execute(
                text(f"""
                    SELECT d.id_detalle, d.id_programacion, pv.estado
                    FROM detalle_programacion_auditor d
                    INNER JOIN programacion_visita pv ON pv.id_programacion = d.id_programacion
                    WHERE pv.id_solicitud = :id_solicitud
                      AND d.id_usuario = :id_auditor
                      AND {SQL_VISITA_NO_TERMINAL}
                    FOR UPDATE OF d
                """),
                {"id_solicitud": id_solicitud, "id_auditor": id_auditor},
            )).mappings().all()

            visitas_sin_auditores = []
            bloqueos_liberados = 0
            for visita in visitas:
                id_programacion = str(visita["id_programacion"])
                await self.db.execute(
                    text("DELETE FROM detalle_programacion_auditor WHERE id_detalle = :id_detalle"),
                    {"id_detalle": str(visita["id_detalle"])},
                )
                # Misma regla que cancelar una visita en Agenda: los bloqueos
                # de fecha que originó la visita quedan liberados.
                liberados = (await self.db.execute(
                    text("""
                        UPDATE disponibilidad_auditor
                        SET estado = 'Cancelado'
                        WHERE id_programacion = :id_programacion
                          AND id_usuario = :id_auditor
                          AND UPPER(TRIM(COALESCE(estado, ''))) IN ('ACTIVO', 'ACTIVA')
                        RETURNING id_disponibilidad, id_usuario, fecha_inicio, fecha_fin, motivo
                    """),
                    {"id_programacion": id_programacion, "id_auditor": id_auditor},
                )).mappings().all()
                for bloqueo in liberados:
                    bloqueos_liberados += 1
                    await agenda._registrar_historial_disponibilidad(
                        {**dict(bloqueo), "tipo_registro": "Bloqueo Fecha", "estado": "Cancelado"},
                        "LIBERADA_POR_RETIRO_CONFLICTO",
                    )
                restantes = (await self.db.execute(
                    text("SELECT COUNT(*) FROM detalle_programacion_auditor WHERE id_programacion = :id"),
                    {"id": id_programacion},
                )).scalar() or 0
                if restantes:
                    nuevo_estado = await agenda._estado_final_programacion(id_programacion)
                    await self.db.execute(
                        text(f"""
                            UPDATE programacion_visita pv
                            SET estado = :estado
                            WHERE pv.id_programacion = :id
                              AND {SQL_VISITA_NO_TERMINAL}
                        """),
                        {"estado": nuevo_estado, "id": id_programacion},
                    )
                else:
                    # Igual que al desactivar un auditor: la visita se conserva
                    # para agregar otro auditor desde Agenda.
                    visitas_sin_auditores.append(id_programacion)
                await agenda._crear_notificacion(
                    id_programacion,
                    UUID(id_auditor),
                    "Retirado de la auditoría",
                    f"Fue retirado de la visita de {fila['numero_radicado'] or 'la solicitud'} "
                    "por conflicto de interés con la empresa.",
                )
                await self._registrar_retiro_conflicto(fila, motivo_final, actor, id_programacion, visita["estado"])

            await self.db.execute(
                text("""
                    UPDATE auditores_solicitud
                    SET estado_asignacion = 'Cancelada',
                        fecha_cancelacion = CURRENT_TIMESTAMP,
                        usuario_cancela = COALESCE(:usuario_cancela, usuario_cancela),
                        motivo_cancelacion = :motivo
                    WHERE id = :id
                """),
                {"id": str(id_asignacion), "usuario_cancela": actor, "motivo": motivo_final},
            )
            if not visitas:
                await self._registrar_retiro_conflicto(fila, motivo_final, actor, None, fila["estado_asignacion"])
            await self.db.commit()
        except HTTPException:
            await self.db.rollback()
            raise

        mensaje = "Asignación cancelada por conflicto de interés."
        if visitas:
            mensaje += f" El auditor fue retirado de {len(visitas)} visita(s)."
        if visitas_sin_auditores:
            mensaje += (
                " La visita quedó sin auditores: agregue otro auditor desde Agenda "
                "o cancele la visita."
            )
        return {
            "mensaje": mensaje,
            "visitas_afectadas": len(visitas),
            "visitas_sin_auditores": visitas_sin_auditores,
            "bloqueos_liberados": bloqueos_liberados,
        }

    async def _registrar_retiro_conflicto(self, fila, motivo, actor, id_programacion, estado_anterior) -> None:
        await self.db.execute(
            text("""
                INSERT INTO historial_asignacion_auditor (
                    id_historial, id_solicitud, id_auditor, accion, motivo,
                    estado_anterior, estado_nuevo, id_usuario_accion, fecha,
                    id_asignacion, id_programacion, origen
                ) VALUES (
                    gen_random_uuid(), :id_solicitud, :id_auditor, :accion, :motivo,
                    :estado_anterior, 'Cancelada', :id_usuario, CURRENT_TIMESTAMP,
                    :id_asignacion, :id_programacion, 'Coordinador'
                )
            """),
            {
                "id_solicitud": str(fila["id_solicitud"]),
                "id_auditor": str(fila["id_auditor"]),
                "accion": ACCION_RETIRO_CONFLICTO,
                "motivo": motivo,
                "estado_anterior": str(estado_anterior or ""),
                "id_usuario": actor,
                "id_asignacion": str(fila["id"]),
                "id_programacion": id_programacion,
            },
        )

    # ------------------------------------------------------------
    # Solicitudes de cambio de la empresa
    #
    # No usan tabla propia: cada solicitud es un registro de
    # historial_asignacion_auditor con accion SOLICITUD_CAMBIO_EMPRESA
    # (la razón va en `motivo`), y la decisión del administrador es otro
    # registro con accion RESPUESTA_CAMBIO_EMPRESA (estado_nuevo Aprobada o
    # Rechazada, la respuesta en `motivo`). El historial no se modifica:
    # una solicitud está pendiente mientras no tenga respuesta posterior.
    # ------------------------------------------------------------

    ACCION_SOLICITUD_CAMBIO = "SOLICITUD_CAMBIO_EMPRESA"
    ACCION_RESPUESTA_CAMBIO = "RESPUESTA_CAMBIO_EMPRESA"

    # Respuesta (si la hay) que corresponde a cada solicitud: la primera
    # posterior sobre la misma asignación. Solo puede haber una pendiente a la vez.
    _SQL_RESPUESTA = """
        LEFT JOIN LATERAL (
            SELECT h.estado_nuevo, h.motivo, h.fecha
            FROM historial_asignacion_auditor h
            WHERE h.accion = 'RESPUESTA_CAMBIO_EMPRESA'
              AND h.id_asignacion = r.id_asignacion
              AND h.fecha >= r.fecha
            ORDER BY h.fecha ASC
            LIMIT 1
        ) resp ON TRUE
    """

    async def empresas_del_usuario(self, usuario: dict) -> list[str]:
        """Empresas activas a las que está vinculado el usuario."""
        resultado = await self.db.execute(
            text("""
                SELECT id_empresa
                FROM user_empresa
                WHERE id_usuario = :id_usuario
                  AND estado = 'Activo'
            """),
            {"id_usuario": str(usuario.get("id_usuario"))},
        )
        return [str(fila["id_empresa"]) for fila in resultado.mappings().all()]

    async def _hay_solicitud_pendiente(self, id_asignacion) -> bool:
        fila = (await self.db.execute(
            text(f"""
                SELECT 1
                FROM historial_asignacion_auditor r
                {self._SQL_RESPUESTA}
                WHERE r.accion = 'SOLICITUD_CAMBIO_EMPRESA'
                  AND r.id_asignacion = :id
                  AND resp.estado_nuevo IS NULL
                LIMIT 1
            """),
            {"id": str(id_asignacion)},
        )).first()
        return fila is not None

    async def solicitar_cambio(self, id_asignacion: UUID, motivo: str, usuario: dict) -> dict:
        """La empresa pide cambiar un auditor asignado a una de sus solicitudes."""
        motivo = (motivo or "").strip()
        if len(motivo) < 30:
            raise HTTPException(
                status_code=422,
                detail="Explique la razón del cambio con al menos 30 caracteres.",
            )

        fila = (await self.db.execute(
            text("""
                SELECT a.id, a.id_solicitud, a.id_auditor, a.estado_asignacion, s.id_empresa
                FROM auditores_solicitud a
                INNER JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                WHERE a.id = :id
                FOR UPDATE OF a
            """),
            {"id": str(id_asignacion)},
        )).mappings().first()
        empresas = await self.empresas_del_usuario(usuario)
        # Misma respuesta si no existe o es de otra empresa: no se revela nada.
        if not fila or str(fila["id_empresa"]) not in empresas:
            raise HTTPException(status_code=404, detail="La asignación no existe.")
        if (fila["estado_asignacion"] or "").strip().lower() in ("cancelada", "cancelado"):
            raise HTTPException(status_code=409, detail="La asignación ya está cancelada.")
        if await self._hay_solicitud_pendiente(id_asignacion):
            raise HTTPException(
                status_code=409,
                detail="Ya hay una solicitud de cambio pendiente para este auditor.",
            )

        id_nueva = uuid4()
        await self.db.execute(
            text("""
                INSERT INTO historial_asignacion_auditor (
                    id_historial, id_solicitud, id_auditor, accion, motivo,
                    estado_anterior, estado_nuevo, id_usuario_accion, fecha,
                    id_asignacion, origen
                ) VALUES (
                    :id, :id_solicitud, :id_auditor, 'SOLICITUD_CAMBIO_EMPRESA', :motivo,
                    :estado_anterior, 'Pendiente', :id_usuario, CURRENT_TIMESTAMP,
                    :id_asignacion, 'Empresa'
                )
            """),
            {
                "id": str(id_nueva),
                "id_solicitud": str(fila["id_solicitud"]),
                "id_auditor": str(fila["id_auditor"]),
                "motivo": motivo,
                "estado_anterior": fila["estado_asignacion"],
                "id_usuario": str(usuario["id_usuario"]),
                "id_asignacion": str(id_asignacion),
            },
        )
        await self.db.commit()
        return {
            "id_solicitud_cambio": id_nueva,
            "estado": "Pendiente",
            "mensaje": "Solicitud de cambio enviada. El Coordinador la revisará.",
        }

    async def listar_solicitudes_cambio(
        self,
        empresas: list[str] | None = None,
        estado: str | None = None,
    ) -> list[dict]:
        """Con ``empresas`` solo las de esas empresas (vista de la empresa)."""
        condiciones = ["r.accion = 'SOLICITUD_CAMBIO_EMPRESA'"]
        parametros: dict = {}
        if empresas is not None:
            if not empresas:
                return []
            condiciones.append("CAST(s.id_empresa AS TEXT) = ANY(:empresas)")
            parametros["empresas"] = empresas
        if estado:
            condiciones.append("COALESCE(resp.estado_nuevo, 'Pendiente') = :estado")
            parametros["estado"] = estado
        resultado = await self.db.execute(
            text(f"""
                SELECT
                    r.id_historial AS id_solicitud_cambio,
                    r.id_asignacion,
                    r.id_solicitud,
                    r.motivo,
                    COALESCE(resp.estado_nuevo, 'Pendiente') AS estado,
                    resp.motivo AS respuesta,
                    r.fecha AS fecha_solicitud,
                    resp.fecha AS fecha_respuesta,
                    s.numero_radicado,
                    e.nombre AS empresa_nombre,
                    u.nombre AS auditor_nombre,
                    a.especialidad AS rol_auditor,
                    a.estado_asignacion,
                    sol.nombre AS solicitado_por_nombre
                FROM historial_asignacion_auditor r
                INNER JOIN auditores_solicitud a ON a.id = r.id_asignacion
                INNER JOIN solicitud s ON s.id_solicitud = r.id_solicitud
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN usuario u ON u.id_usuario = a.id_auditor
                LEFT JOIN usuario sol ON sol.id_usuario = r.id_usuario_accion
                {self._SQL_RESPUESTA}
                WHERE {" AND ".join(condiciones)}
                ORDER BY (resp.estado_nuevo IS NULL) DESC, r.fecha DESC
            """),
            parametros,
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def resolver_solicitud_cambio(
        self,
        id_solicitud_cambio: UUID,
        aprobar: bool,
        respuesta: str,
        usuario: dict,
    ) -> dict:
        """El administrador aprueba (cancela la asignación) o rechaza la solicitud."""
        respuesta = (respuesta or "").strip()
        if len(respuesta) < 10:
            raise HTTPException(
                status_code=422,
                detail="Escriba una respuesta para la empresa de al menos 10 caracteres.",
            )

        fila = (await self.db.execute(
            text(f"""
                SELECT r.id_asignacion, r.id_solicitud, r.id_auditor, resp.estado_nuevo AS resuelta
                FROM historial_asignacion_auditor r
                {self._SQL_RESPUESTA}
                WHERE r.id_historial = :id
                  AND r.accion = 'SOLICITUD_CAMBIO_EMPRESA'
            """),
            {"id": str(id_solicitud_cambio)},
        )).mappings().first()
        if not fila:
            raise HTTPException(status_code=404, detail="La solicitud de cambio no existe.")

        # Bloquea la asignación para que dos administradores no la resuelvan a la vez.
        await self.db.execute(
            text("SELECT 1 FROM auditores_solicitud WHERE id = :id FOR UPDATE"),
            {"id": str(fila["id_asignacion"])},
        )
        if fila["resuelta"] is not None:
            raise HTTPException(status_code=409, detail="La solicitud de cambio ya fue resuelta.")

        if aprobar:
            # Si la visita ya está programada, cancelar_asignacion responde 409
            # y la solicitud queda pendiente hasta que se cancele la programación.
            await self.cancelar_asignacion(
                fila["id_asignacion"],
                confirmar=False,
                usuario=usuario,
                motivo="Cambio solicitado por la empresa. " + respuesta,
            )

        nuevo_estado = "Aprobada" if aprobar else "Rechazada"
        await self.db.execute(
            text("""
                INSERT INTO historial_asignacion_auditor (
                    id_historial, id_solicitud, id_auditor, accion, motivo,
                    estado_anterior, estado_nuevo, id_usuario_accion, fecha,
                    id_asignacion, origen
                ) VALUES (
                    gen_random_uuid(), :id_solicitud, :id_auditor, 'RESPUESTA_CAMBIO_EMPRESA', :respuesta,
                    'Pendiente', :estado, :id_usuario, CURRENT_TIMESTAMP,
                    :id_asignacion, 'Coordinador'
                )
            """),
            {
                "id_solicitud": str(fila["id_solicitud"]),
                "id_auditor": str(fila["id_auditor"]) if fila["id_auditor"] else None,
                "respuesta": respuesta,
                "estado": nuevo_estado,
                "id_usuario": str(usuario["id_usuario"]),
                "id_asignacion": str(fila["id_asignacion"]),
            },
        )
        await self.db.commit()
        return {
            "estado": nuevo_estado,
            "mensaje": (
                "Solicitud aprobada: la asignación quedó cancelada."
                if aprobar
                else "Solicitud rechazada."
            ),
        }
