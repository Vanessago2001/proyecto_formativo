"""
Consultas de los reportes (M12).

Regla de oro: el alcance de los datos se decide aquí, en el SQL, y no en la
interfaz. Ocultar un reporte en el menú no protege nada si el endpoint devuelve
filas de más, así que cada consulta agrega su filtro según el rol:

- Una cuenta de empresa nunca ve filas de otra empresa: su `id_empresa` se
  resuelve por `user_empresa` y se inyecta como `:eid`.
- Un auditor ve solo lo propio (asignaciones, auditorías, disponibilidad y
  apelaciones): su `id_usuario` se inyecta como `:yo`.

Los roles de dirección y control no llevan filtro: su trabajo es ver todo.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name
from modules.solicitudes import estado_solicitud as estados
from modules.reportes import reportes_roles as roles_m12

EMPRESA = roles_m12.EMPRESA
AUDITOR = roles_m12.AUDITOR


class ReportesService:
    def __init__(self, db: AsyncSession, usuario: dict):
        self.db = db
        self.rol = _normalize_role_name(usuario.get("role_name"))
        self.id_usuario = usuario.get("id_usuario")
        self.id_empresa = None
        self.solo_yo = False

    async def ejecutar(self, codigo: str) -> list[dict]:
        datos = roles_m12.reporte_o_none(codigo)
        if datos is None:
            return []

        if datos["alcance_empresa"] and self.rol == EMPRESA:
            self.id_empresa = await self._empresa_del_usuario()
            if self.id_empresa is None:
                # Usuario empresa sin empresa asociada: no hay filas que ver.
                return []

        self.solo_yo = bool(datos["alcance_auditor"] and self.rol == AUDITOR)

        metodo = getattr(self, "_" + codigo.replace("-", "_"))
        resultado = await metodo()
        return [dict(fila) for fila in resultado]

    async def _empresa_del_usuario(self):
        resultado = await self.db.execute(text("""
            SELECT id_empresa
            FROM user_empresa
            WHERE id_usuario = :yo
              AND UPPER(TRIM(estado)) = 'ACTIVO'
            ORDER BY fecha_asociacion DESC NULLS LAST
            LIMIT 1;
        """), {"yo": self.id_usuario})
        fila = resultado.mappings().first()
        return fila["id_empresa"] if fila else None

    def _filtros(self, empresa: bool = True, yo: str = "u.id_usuario"):
        """Devuelve el fragmento WHERE extra y sus parámetros, según el rol."""
        condiciones = []
        params: dict = {}
        if empresa and self.id_empresa is not None:
            condiciones.append("AND e.id_empresa = :eid")
            params["eid"] = self.id_empresa
        if self.solo_yo:
            condiciones.append(f"AND {yo} = :yo")
            params["yo"] = self.id_usuario
        return " ".join(condiciones), params

    # ------------------------------------------------------------
    # 1. Estadístico de empresas
    # ------------------------------------------------------------
    async def _estadistico_empresas(self):
        resultado = await self.db.execute(text("""
            SELECT
                e.nombre AS empresa,
                e.nit,
                e.ciudad,
                COUNT(DISTINCT s.id_solicitud) AS solicitudes,
                COUNT(DISTINCT c.id_certificado) AS certificados_vigentes
            FROM empresa e
            LEFT JOIN solicitud s ON s.id_empresa = e.id_empresa
            LEFT JOIN certificado c
                   ON (c.id_solicitud = s.id_solicitud OR c.id_certificado = s.id_certificado)
                  AND c.fecha_vencimiento >= CURRENT_DATE
            GROUP BY e.id_empresa, e.nombre, e.nit, e.ciudad
            ORDER BY e.nombre;
        """))
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 2. Operativo de auditores
    # ------------------------------------------------------------
    async def _operativo_auditores(self):
        extra, params = self._filtros(empresa=False)
        resultado = await self.db.execute(text(f"""
            SELECT
                u.nombre AS auditor,
                COUNT(DISTINCT a_s.id) AS asignaciones,
                COUNT(DISTINCT a.id_auditoria) AS auditorias,
                COUNT(DISTINCT a.id_auditoria)
                    FILTER (WHERE a.fecha_fin IS NOT NULL) AS ejecutadas
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            LEFT JOIN auditores_solicitud a_s ON a_s.id_auditor = u.id_usuario
            LEFT JOIN auditoria a ON a.id_solicitud = a_s.id_solicitud
            WHERE LOWER(TRIM(r.nombre)) = 'auditor' {extra}
            GROUP BY u.id_usuario, u.nombre
            ORDER BY u.nombre;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 3. Solicitudes críticas
    # ------------------------------------------------------------
    async def _solicitudes_criticas(self):
        extra, params = self._filtros(empresa=True)
        params["dias"] = roles_m12.DIAS_SOLICITUD_CRITICA
        # Los estados salen del catalogo de M5: antes se enumeraban aqui las
        # grafias una por una y bastaba con que apareciera otra para que el
        # reporte dejara de ver esas solicitudes.
        params["radicada"] = estados.RADICADA
        params["en_revision"] = estados.EN_REVISION
        resultado = await self.db.execute(text(f"""
            SELECT
                s.numero_radicado,
                TRIM(s.estado) AS estado,
                s.fecha,
                (CURRENT_DATE - s.fecha::date) AS dias_abierta,
                e.nombre AS empresa,
                e.nit
            FROM solicitud s
            JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE s.estado IN (:radicada, :en_revision)
              AND s.fecha IS NOT NULL
              AND (CURRENT_DATE - s.fecha::date) > :dias {extra}
            ORDER BY dias_abierta DESC;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 4. Auditorías ejecutadas
    # ------------------------------------------------------------
    async def _auditorias_ejecutadas(self):
        extra, params = self._filtros(empresa=True, yo="a_s.id_auditor")
        resultado = await self.db.execute(text(f"""
            SELECT
                a.id_auditoria,
                s.numero_radicado,
                e.nombre AS empresa,
                TRIM(a.estado) AS estado,
                a.fecha_inicio,
                a.fecha_fin,
                STRING_AGG(DISTINCT u.nombre, ', ' ORDER BY u.nombre) AS auditores
            FROM auditoria a
            JOIN solicitud s ON s.id_solicitud = a.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN auditores_solicitud a_s ON a_s.id_solicitud = a.id_solicitud
            LEFT JOIN usuario u ON u.id_usuario = a_s.id_auditor
            WHERE a.fecha_fin IS NOT NULL {extra}
            GROUP BY a.id_auditoria, s.numero_radicado, e.nombre,
                     a.estado, a.fecha_inicio, a.fecha_fin
            ORDER BY a.fecha_fin DESC;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 5. Certificados vigentes
    # ------------------------------------------------------------
    async def _certificados_vigentes(self):
        extra, params = self._filtros(empresa=True)
        resultado = await self.db.execute(text(f"""
            SELECT
                c.codigo_verificacion,
                e.nombre AS empresa,
                e.nit,
                s.numero_radicado,
                c.fecha_emision,
                c.fecha_vencimiento,
                (c.fecha_vencimiento - CURRENT_DATE) AS dias_restantes
            FROM certificado c
            JOIN solicitud s
              ON s.id_solicitud = c.id_solicitud
              OR s.id_certificado = c.id_certificado
            JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE c.fecha_vencimiento IS NOT NULL
              AND c.fecha_vencimiento >= CURRENT_DATE {extra}
            ORDER BY c.fecha_vencimiento;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 6. Apelaciones y fallos
    # ------------------------------------------------------------
    async def _apelaciones_fallos(self):
        condiciones = []
        params: dict = {}
        if self.id_empresa is not None:
            condiciones.append("AND ap.id_empresa = :eid")
            params["eid"] = self.id_empresa
        if self.solo_yo:
            condiciones.append(
                "AND (ap.id_usuario_presenta = :yo OR ap.id_auditor_evaluador = :yo)"
            )
            params["yo"] = self.id_usuario
        extra = " ".join(condiciones)

        resultado = await self.db.execute(text(f"""
            SELECT
                ap.radicado,
                TRIM(ap.estado) AS estado,
                ap.fecha,
                ap.motivo,
                ap.fallo,
                ap.fecha_resolucion,
                e.nombre AS empresa,
                u_p.nombre AS presenta,
                u_r.nombre AS revisa
            FROM apelacion ap
            LEFT JOIN empresa e ON e.id_empresa = ap.id_empresa
            LEFT JOIN usuario u_p ON u_p.id_usuario = ap.id_usuario_presenta
            LEFT JOIN usuario u_r ON u_r.id_usuario = ap.id_usuario_revisa
            WHERE TRUE {extra}
            ORDER BY ap.fecha DESC NULLS LAST;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 7. Preventivo de conflictos
    # ------------------------------------------------------------
    async def _preventivo_conflictos(self):
        resultado = await self.db.execute(text("""
            SELECT
                ci.tipo_conflicto,
                TRIM(ci.estado) AS estado,
                ci.bloquea_asignacion,
                ci.fecha_declaracion,
                u.nombre AS auditor,
                e.nombre AS empresa,
                ci.descripcion
            FROM conflicto_interes ci
            LEFT JOIN usuario u ON u.id_usuario = ci.id_usuario
            LEFT JOIN empresa e ON e.id_empresa = ci.id_empresa
            WHERE ci.bloquea_asignacion = TRUE
               OR UPPER(TRIM(ci.estado)) IN ('PENDIENTE', 'ACTIVO')
            ORDER BY ci.fecha_declaracion DESC NULLS LAST;
        """))
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 8. Disponibilidad horaria
    # ------------------------------------------------------------
    async def _disponibilidad_horaria(self):
        """
        Una fila por auditor, identificado por su documento, con los días que
        tiene activos.

        Antes salía una fila por registro, así que un mismo auditor aparecía
        repetido cinco o seis veces, y además se mostraban los registros
        cancelados, que ya no valen.

        Los bloqueos de fecha van en su propia columna a propósito: están
        activos, pero significan lo contrario que un día disponible, y
        sumarlos a los demás haría leer el reporte al revés.
        """
        extra, params = self._filtros(empresa=False, yo="da.id_usuario")
        resultado = await self.db.execute(text(f"""
            WITH registros AS (
                SELECT
                    COALESCE(NULLIF(TRIM(u.num_doc), ''), 'Sin documento') AS documento,
                    NULLIF(TRIM(u.tipo_doc), '') AS tipo_documento,
                    u.nombre AS auditor,
                    TRIM(da.tipo_registro) AS tipo_registro,
                    da.dia_semana,
                    da.fecha_inicio,
                    da.hora_inicio,
                    CASE
                        WHEN da.dia_semana IS NOT NULL THEN
                            CASE da.dia_semana
                                WHEN 1 THEN 'Lunes'
                                WHEN 2 THEN 'Martes'
                                WHEN 3 THEN 'Miércoles'
                                WHEN 4 THEN 'Jueves'
                                WHEN 5 THEN 'Viernes'
                                WHEN 6 THEN 'Sábado'
                                WHEN 7 THEN 'Domingo'
                                ELSE 'Día ' || da.dia_semana
                            END
                        ELSE TO_CHAR(da.fecha_inicio, 'DD/MM/YYYY')
                    END
                    || CASE
                           WHEN da.hora_inicio IS NOT NULL AND da.hora_fin IS NOT NULL
                           THEN ' ' || TO_CHAR(da.hora_inicio, 'HH24:MI')
                                || '-' || TO_CHAR(da.hora_fin, 'HH24:MI')
                           ELSE ''
                       END AS dia
                FROM disponibilidad_auditor da
                JOIN usuario u ON u.id_usuario = da.id_usuario
                WHERE UPPER(TRIM(da.estado)) = 'ACTIVO' {extra}
            ),
            activas AS (
                -- Un mismo dia puede estar registrado varias veces (el auditor
                -- lo volvio a guardar). En el reporte basta con nombrarlo una.
                SELECT
                    documento, tipo_documento, auditor, tipo_registro, dia,
                    MIN(dia_semana) AS dia_semana,
                    MIN(fecha_inicio) AS fecha_inicio,
                    MIN(hora_inicio) AS hora_inicio
                FROM registros
                GROUP BY documento, tipo_documento, auditor, tipo_registro, dia
            )
            SELECT
                documento,
                tipo_documento,
                auditor,
                COUNT(*) FILTER (WHERE tipo_registro <> 'Bloqueo Fecha') AS dias_activos,
                STRING_AGG(dia, ', ' ORDER BY dia_semana NULLS LAST, fecha_inicio, hora_inicio)
                    FILTER (WHERE tipo_registro <> 'Bloqueo Fecha') AS dias_disponibles,
                STRING_AGG(dia, ', ' ORDER BY dia_semana NULLS LAST, fecha_inicio, hora_inicio)
                    FILTER (WHERE tipo_registro = 'Bloqueo Fecha') AS fechas_bloqueadas
            FROM activas
            GROUP BY documento, tipo_documento, auditor
            ORDER BY auditor;
        """), params)
        return resultado.mappings().all()

    # ------------------------------------------------------------
    # 9. Crítico de vencimiento
    # ------------------------------------------------------------
    async def _critico_vencimiento(self):
        extra, params = self._filtros(empresa=True)
        params["dias"] = roles_m12.DIAS_VENCIMIENTO_CRITICO
        resultado = await self.db.execute(text(f"""
            SELECT
                c.codigo_verificacion,
                e.nombre AS empresa,
                e.nit,
                s.numero_radicado,
                c.fecha_vencimiento,
                (c.fecha_vencimiento - CURRENT_DATE) AS dias_restantes
            FROM certificado c
            JOIN solicitud s
              ON s.id_solicitud = c.id_solicitud
              OR s.id_certificado = c.id_certificado
            JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE c.fecha_vencimiento IS NOT NULL
              AND (c.fecha_vencimiento - CURRENT_DATE) <= :dias {extra}
            ORDER BY c.fecha_vencimiento;
        """), params)
        return resultado.mappings().all()
