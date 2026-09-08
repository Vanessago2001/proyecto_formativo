from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class EmpresasService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_empresas(self) -> list[dict]:
        result = await self.db.execute(text("""
            SELECT id_empresa, nombre, nit, ciudad, direccion, correo
            FROM empresa
            ORDER BY nombre ASC;
        """))
        return [dict(row) for row in result.mappings().all()]

    async def consulta_publica(self, codigo: str = "", nit: str = "") -> list[dict]:
        codigo = (codigo or "").strip()
        nit = (nit or "").strip()
        if not codigo and not nit:
            return []

        condiciones = []
        params: dict = {}
        if codigo:
            condiciones.append(
                "(s.numero_radicado ILIKE '%' || TRIM(:codigo) || '%'"
                " OR c.codigo_verificacion ILIKE '%' || TRIM(:codigo) || '%')"
            )
            params["codigo"] = codigo
        if nit:
            condiciones.append(
                "(REPLACE(REPLACE(REPLACE(TRIM(e.nit), '.', ''), '-', ''), ' ', '')"
                " = REPLACE(REPLACE(REPLACE(TRIM(:nit), '.', ''), '-', ''), ' ', '')"
                " OR TRIM(e.nit) ILIKE '%' || TRIM(:nit) || '%'"
                " OR TRIM(e.nombre) ILIKE '%' || TRIM(:nit) || '%')"
            )
            params["nit"] = nit

        where = " AND ".join(condiciones)
        result = await self.db.execute(text(f"""
            SELECT
                s.id_solicitud,
                s.numero_radicado,
                s.estado AS estado_tramite,
                s.fecha AS fecha_tramite,
                s.alcance_certificacion,
                e.id_empresa,
                e.nombre AS empresa,
                e.nit,
                e.ciudad,
                e.direccion,
                e.correo,
                n.codigo AS norma_codigo,
                n.nombre AS norma_nombre,
                n.version AS norma_version,
                c.codigo_verificacion,
                TRIM(c.estado_certificado) AS cert_estado,
                c.fecha_emision AS cert_emision,
                c.fecha_vencimiento AS cert_vence,
                c.url_certificado
            FROM solicitud s
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            LEFT JOIN certificado c
              ON c.id_solicitud = s.id_solicitud
              OR c.id_certificado = s.id_certificado
            WHERE {where}
            ORDER BY s.fecha DESC NULLS LAST
            LIMIT 20;
        """), params)
        filas = [dict(r) for r in result.mappings().all()]

        hoy = date.today()
        resultados: list[dict] = []
        for f in filas:
            vence = f.get("cert_vence")
            vigente = bool(f.get("codigo_verificacion")) and vence is not None and vence >= hoy
            estado_tramite = (f.get("estado_tramite") or "").strip()
            if vigente:
                estado_general = "CERTIFICADA"
                mensaje = (
                    f"Certificado vigente (código: {f.get('codigo_verificacion')}). "
                    f"Vence el {vence}."
                )
            else:
                estado_general = f"EN TRAMITE - {estado_tramite}" if estado_tramite else "EN TRAMITE"
                mensaje = (
                    f"Tramite en curso (estado: {estado_tramite}). "
                    "Aun no se ha emitido certificado."
                )
            norma_partes = [f.get("norma_codigo"), f.get("norma_nombre"), f.get("norma_version")]
            f["norma_completa"] = " ".join([p for p in norma_partes if p]).strip() or "--"
            f["vigente"] = vigente
            f["estado_general"] = estado_general
            f["mensaje"] = mensaje
            resultados.append(f)

        if not resultados and nit:
            emp = await self.db.execute(text("""
                SELECT id_empresa, nombre AS empresa, nit, ciudad, direccion, correo
                FROM empresa
                WHERE
                    REPLACE(REPLACE(REPLACE(TRIM(nit), '.', ''), '-', ''), ' ', '')
                        = REPLACE(REPLACE(REPLACE(TRIM(:nit), '.', ''), '-', ''), ' ', '')
                    OR TRIM(nit) ILIKE '%' || TRIM(:nit) || '%'
                    OR TRIM(nombre) ILIKE '%' || TRIM(:nit) || '%'
                ORDER BY nombre ASC
                LIMIT 5;
            """), {"nit": nit})
            for row in emp.mappings().all():
                e = dict(row)
                e.update({
                    "id_solicitud": None,
                    "numero_radicado": None,
                    "estado_tramite": None,
                    "fecha_tramite": None,
                    "alcance_certificacion": None,
                    "norma_codigo": None,
                    "norma_nombre": None,
                    "norma_version": None,
                    "norma_completa": "--",
                    "codigo_verificacion": None,
                    "cert_estado": None,
                    "cert_emision": None,
                    "cert_vence": None,
                    "url_certificado": None,
                    "vigente": False,
                    "estado_general": "REGISTRADA",
                    "mensaje": "Empresa registrada. Aun no tiene trámites radicados.",
                })
                resultados.append(e)

        return resultados

    async def buscar_por_nit(self, nit: str) -> list[dict]:
        nit_limpio = (nit or "").strip()
        if not nit_limpio:
            return []
        result = await self.db.execute(text("""
            SELECT id_empresa, nombre, nit, ciudad, direccion, correo
            FROM empresa
            WHERE
                REPLACE(REPLACE(REPLACE(TRIM(nit), '.', ''), '-', ''), ' ', '')
                    = REPLACE(REPLACE(REPLACE(TRIM(:nit), '.', ''), '-', ''), ' ', '')
                OR TRIM(nit) ILIKE '%' || TRIM(:nit) || '%'
            ORDER BY nombre ASC;
        """), {"nit": nit_limpio})
        empresas = [dict(row) for row in result.mappings().all()]

        for emp in empresas:
            eid = emp.get("id_empresa")

            certs = await self.db.execute(text("""
                SELECT
                    c.codigo_verificacion,
                    TRIM(c.estado_certificado) AS estado,
                    c.fecha_emision,
                    c.fecha_vencimiento,
                    c.url_certificado
                FROM certificado c
                JOIN solicitud s
                  ON s.id_solicitud = c.id_solicitud
                  OR s.id_certificado = c.id_certificado
                WHERE s.id_empresa = :eid
                  AND (c.fecha_vencimiento IS NULL OR c.fecha_vencimiento >= CURRENT_DATE)
                ORDER BY c.fecha_emision DESC NULLS LAST;
            """), {"eid": eid})
            certificados = [dict(r) for r in certs.mappings().all()]

            hist = await self.db.execute(text("""
                SELECT
                    c.codigo_verificacion,
                    TRIM(c.estado_certificado) AS estado,
                    c.fecha_emision,
                    c.fecha_vencimiento,
                    c.url_certificado
                FROM certificado c
                JOIN solicitud s
                  ON s.id_solicitud = c.id_solicitud
                  OR s.id_certificado = c.id_certificado
                WHERE s.id_empresa = :eid
                ORDER BY c.fecha_emision DESC NULLS LAST;
            """), {"eid": eid})
            historial_certificados = [dict(r) for r in hist.mappings().all()]
            total_certificados = len(historial_certificados)

            tot_sol = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM solicitud WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_solicitudes = tot_sol.mappings().first()["total"]

            tot_sedes = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM sede_empresa WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_sedes = tot_sedes.mappings().first()["total"]

            tot_docs = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM documento_empresa WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_documentos = tot_docs.mappings().first()["total"]

            ult = await self.db.execute(text("""
                SELECT
                    s.numero_radicado,
                    s.estado,
                    s.fecha,
                    s.alcance_certificacion,
                    s.numero_empleados,
                    s.numero_sedes,
                    s.persona_contacto,
                    s.fecha_radicacion,
                    n.nombre AS norma
                FROM solicitud s
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_empresa = :eid
                ORDER BY s.fecha DESC NULLS LAST, s.fecha_creacion DESC NULLS LAST
                LIMIT 1;
            """), {"eid": eid})
            ultima = ult.mappings().first()

            sols = await self.db.execute(text("""
                SELECT
                    s.numero_radicado,
                    s.estado,
                    s.fecha,
                    s.fecha_radicacion,
                    n.nombre AS norma
                FROM solicitud s
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_empresa = :eid
                ORDER BY s.fecha DESC NULLS LAST, s.fecha_creacion DESC NULLS LAST
                LIMIT 10;
            """), {"eid": eid})
            solicitudes = [dict(r) for r in sols.mappings().all()]

            emp["certificada"] = len(certificados) > 0
            emp["total_certificados"] = total_certificados
            emp["certificados_vigentes"] = len(certificados)
            emp["total_solicitudes"] = total_solicitudes
            emp["total_sedes"] = total_sedes
            emp["total_documentos"] = total_documentos
            emp["certificados"] = certificados
            emp["certificados_historial"] = historial_certificados
            emp["solicitudes"] = solicitudes
            emp["ultima_solicitud"] = dict(ultima) if ultima else None

        return empresas
