import uuid
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name

# La tabla real de sedes es `sede_empresa`: solo admite los estados 'Activa' e
# 'Inactiva' (restricción chk_estado_sede) y el país no puede quedar vacío.
ESTADOS_SEDE = {"activa": "Activa", "activo": "Activa", "inactiva": "Inactiva", "inactivo": "Inactiva"}
PAIS_POR_DEFECTO = "Colombia"

# Estados de la empresa (columna creada por empresas_bootstrap.py).
ESTADO_EMPRESA_ACTIVA = "Activa"
ESTADO_EMPRESA_INACTIVA = "Inactiva"

# Ubicación de una sede: solo se indica al registrarla. Si está mal, la sede
# se inactiva y se registra otra (misma regla que las sedes de M5).
UBICACION_FIJA_SEDE = ("ciudad", "departamento", "pais")

COLUMNAS_EMPRESA = "id_empresa, nombre, nit, ciudad, direccion, correo, estado"
COLUMNAS_CONTACTO = "id_contacto, id_sede, nombre, cargo, telefono, correo, fecha_registro"


def _normalizar_estado_sede(estado: str | None) -> str:
    return ESTADOS_SEDE.get((estado or "").strip().lower(), "Activa")


class EmpresasService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_empresas(self) -> list[dict]:
        result = await self.db.execute(text(f"""
            SELECT {COLUMNAS_EMPRESA}
            FROM empresa
            ORDER BY nombre ASC;
        """))
        return [dict(row) for row in result.mappings().all()]

    async def create_empresa(self, data: dict, id_usuario: str | None = None) -> dict:
        # empresa.id_empresa es UUID sin valor por defecto: hay que generarlo.
        query = text(f"""
            INSERT INTO empresa (id_empresa, nombre, nit, ciudad, direccion, correo)
            VALUES (gen_random_uuid(), :nombre, :nit, :ciudad, :direccion, :correo)
            RETURNING {COLUMNAS_EMPRESA};
        """)
        result = await self.db.execute(query, data)
        empresa = dict(result.mappings().first())

        # Una cuenta de empresa queda vinculada a la empresa que registra.
        if id_usuario:
            await self.db.execute(
                text("""
                    INSERT INTO user_empresa (id_usuario, id_empresa, estado)
                    VALUES (:id_usuario, :id_empresa, 'Activo')
                    ON CONFLICT (id_usuario, id_empresa) DO NOTHING;
                """),
                {"id_usuario": id_usuario, "id_empresa": str(empresa["id_empresa"])},
            )

        await self.db.commit()
        return empresa

    async def get_empresas_de_usuario(self, id_usuario: str) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT e.id_empresa, e.nombre, e.nit, e.ciudad, e.direccion, e.correo, e.estado
                FROM empresa e
                JOIN user_empresa ue ON ue.id_empresa = e.id_empresa
                WHERE ue.id_usuario = :id_usuario
                  AND ue.estado = 'Activo'
                ORDER BY e.nombre ASC;
            """),
            {"id_usuario": id_usuario},
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_empresa_by_id(self, id_empresa: str) -> dict:
        query = text(f"""
            SELECT {COLUMNAS_EMPRESA}
            FROM empresa
            WHERE id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        row = result.mappings().first()
        return dict(row) if row else None

    async def update_empresa(self, id_empresa: str, data: dict) -> dict:
        query = text(f"""
            UPDATE empresa
            SET nombre = :nombre, nit = :nit, ciudad = :ciudad, direccion = :direccion, correo = :correo
            WHERE id_empresa = :id_empresa
            RETURNING {COLUMNAS_EMPRESA};
        """)
        data["id_empresa"] = id_empresa
        result = await self.db.execute(query, data)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_usuarios_by_empresa(self, id_empresa: str) -> list[dict]:
        query = text("""
            SELECT u.* FROM usuario u
            JOIN user_empresa ue ON u.id_usuario = ue.id_usuario
            WHERE ue.id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_historial_solicitudes_by_empresa(self, id_empresa: str) -> list[dict]:
        query = text("""
            SELECT * FROM solicitud WHERE id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_sedes_by_empresa(self, id_empresa: str) -> list[dict]:
        query = text("""
            SELECT id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                   es_principal, estado, fecha_registro
            FROM sede_empresa
            WHERE id_empresa = :id_empresa
            ORDER BY es_principal DESC, nombre_sede ASC;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    async def get_sede_by_id(self, id_empresa: str, id_sede: str) -> dict | None:
        query = text("""
            SELECT id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                   es_principal, estado, fecha_registro
            FROM sede_empresa
            WHERE id_empresa = :id_empresa
              AND id_sede = :id_sede;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa, "id_sede": id_sede})
        row = result.mappings().first()
        return dict(row) if row else None

    async def create_sede(self, id_empresa: str, data: dict) -> dict | None:
        empresa = await self.get_empresa_by_id(id_empresa)
        if not empresa:
            return None

        payload = {
            "id_empresa": id_empresa,
            "nombre_sede": data.get("nombre_sede"),
            "direccion": data.get("direccion"),
            "ciudad": data.get("ciudad"),
            "departamento": data.get("departamento"),
            "pais": data.get("pais") or PAIS_POR_DEFECTO,
            "es_principal": data.get("es_principal", False),
            "estado": _normalizar_estado_sede(data.get("estado")),
        }

        insert_sede = text("""
            INSERT INTO sede_empresa (
                id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                es_principal, estado, fecha_registro
            )
            VALUES (
                :id_empresa, :nombre_sede, :direccion, :ciudad, :departamento, :pais,
                :es_principal, :estado, CURRENT_TIMESTAMP
            )
            RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                      es_principal, estado, fecha_registro;
        """)
        result = await self.db.execute(insert_sede, payload)
        sede_row = result.mappings().first()
        if not sede_row:
            await self.db.rollback()
            return None

        await self.db.commit()
        return dict(sede_row)

    async def update_sede(self, id_empresa: str, id_sede: str, data: dict) -> dict | None:
        current = await self.get_sede_by_id(id_empresa, id_sede)
        if not current:
            return None

        cambiados = [
            campo
            for campo in UBICACION_FIJA_SEDE
            if data.get(campo) not in (None, "") and data.get(campo) != current.get(campo)
        ]
        if cambiados:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Ciudad, departamento y país no se pueden cambiar: inactive la "
                    "sede y registre otra."
                ),
            )

        payload = {
            "id_empresa": id_empresa,
            "id_sede": id_sede,
            "nombre_sede": data.get("nombre_sede", current.get("nombre_sede")),
            "direccion": data.get("direccion", current.get("direccion")),
            "ciudad": data.get("ciudad", current.get("ciudad")),
            "departamento": data.get("departamento", current.get("departamento")),
            "pais": data.get("pais", current.get("pais")) or PAIS_POR_DEFECTO,
            "es_principal": data.get("es_principal", current.get("es_principal")),
            "estado": _normalizar_estado_sede(data.get("estado", current.get("estado"))),
        }

        query = text("""
            UPDATE sede_empresa
            SET nombre_sede = :nombre_sede,
                direccion = :direccion,
                ciudad = :ciudad,
                departamento = :departamento,
                pais = :pais,
                es_principal = :es_principal,
                estado = :estado
            WHERE id_empresa = :id_empresa
              AND id_sede = :id_sede
            RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                      es_principal, estado, fecha_registro;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def delete_sede(self, id_empresa: str, id_sede: str) -> dict | None:
        existing = await self.get_sede_by_id(id_empresa, id_sede)
        if not existing:
            return None

        await self._exigir_sede_sin_uso(id_sede)

        result = await self.db.execute(
            text("""
                DELETE FROM sede_empresa
                WHERE id_empresa = :id_empresa
                  AND id_sede = :id_sede
                RETURNING id_sede, id_empresa, nombre_sede, direccion, ciudad, departamento, pais,
                          es_principal, estado, fecha_registro;
            """),
            {"id_empresa": id_empresa, "id_sede": id_sede},
        )
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    # ============================================================
    # ESTADO DE LA EMPRESA (EMP-006 / EMP-007 / EMP-008)
    # ============================================================
    # 'Activa' <-> 'Suspendida' se cambia con EMP-006. 'Inactiva' es la baja:
    # se entra con EMP-007 y solo se sale reactivando (EMP-008).

    async def _empresa_o_404(self, id_empresa: str) -> dict:
        empresa = await self.get_empresa_by_id(id_empresa)
        if not empresa:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
        return empresa

    async def _guardar_estado(self, id_empresa: str, estado: str) -> dict:
        result = await self.db.execute(
            text(f"""
                UPDATE empresa SET estado = :estado
                WHERE id_empresa = :id_empresa
                RETURNING {COLUMNAS_EMPRESA};
            """),
            {"estado": estado, "id_empresa": id_empresa},
        )
        await self.db.commit()
        return dict(result.mappings().first())

    async def validar_accion(self, codigo: str, id_empresa: str, datos: dict) -> str:
        """
        Comprueba que una acción se pueda ejecutar y devuelve su descripción.

        Se usa al ejecutarla y también al registrarla como pendiente de
        aprobación (REQ), para no guardar solicitudes que fallarían.
        """
        conflicto = lambda mensaje: HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mensaje)

        if codigo in ("EMP-006", "EMP-007", "EMP-008"):
            empresa = await self._empresa_o_404(id_empresa)
            actual = empresa.get("estado") or ESTADO_EMPRESA_ACTIVA
            nombre = empresa.get("nombre") or "la empresa"

            if codigo == "EMP-006":
                if actual == ESTADO_EMPRESA_INACTIVA:
                    raise conflicto("La empresa está inactiva: primero debe reactivarse.")
                if actual == datos["estado"]:
                    raise conflicto(f"La empresa ya está en estado '{datos['estado']}'.")
                return f"Cambiar el estado de {nombre} a {datos['estado']}"

            if codigo == "EMP-007":
                if actual == ESTADO_EMPRESA_INACTIVA:
                    raise conflicto("La empresa ya está inactiva.")
                return f"Inactivar {nombre}"

            if actual != ESTADO_EMPRESA_INACTIVA:
                raise conflicto("Solo se reactiva una empresa inactiva.")
            return f"Reactivar {nombre}"

        if codigo == "EMP-023":
            sede = await self._sede_o_404(id_empresa, datos["id_sede"])
            await self._exigir_sede_sin_uso(datos["id_sede"])
            return f"Eliminar la sede {sede.get('nombre_sede')}"

        if codigo == "EMP-029":
            sede = await self._sede_o_404(id_empresa, datos["id_sede"])
            contacto = await self._contacto_o_404(datos["id_sede"], datos["id_contacto"])
            return f"Eliminar el contacto {contacto.get('nombre')} de la sede {sede.get('nombre_sede')}"

        raise ValueError(f"Acción sin validación definida: {codigo}")

    async def cambiar_estado(self, id_empresa: str, estado: str) -> dict:
        await self.validar_accion("EMP-006", id_empresa, {"estado": estado})
        return await self._guardar_estado(id_empresa, estado)

    async def inactivar(self, id_empresa: str) -> dict:
        await self.validar_accion("EMP-007", id_empresa, {})
        return await self._guardar_estado(id_empresa, ESTADO_EMPRESA_INACTIVA)

    async def reactivar(self, id_empresa: str) -> dict:
        await self.validar_accion("EMP-008", id_empresa, {})
        return await self._guardar_estado(id_empresa, ESTADO_EMPRESA_ACTIVA)

    async def _exigir_sede_sin_uso(self, id_sede: str) -> None:
        # Borrar la sede eliminaría en cascada sus vínculos con solicitudes
        # (solicitud_sede), incluidas las ya radicadas: en ese caso se inactiva.
        en_uso = await self.db.execute(
            text("SELECT COUNT(*) FROM solicitud_sede WHERE id_sede = :id_sede;"),
            {"id_sede": id_sede},
        )
        if en_uso.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La sede está incluida en solicitudes de certificación: "
                    "inactívela en lugar de eliminarla."
                ),
            )

    # ============================================================
    # ACCESO DE LAS CUENTAS DE EMPRESA
    # ============================================================

    async def exigir_acceso(self, usuario: dict, id_empresa: str) -> None:
        """
        Una cuenta de rol Empresa solo accede a las empresas a las que está
        vinculada en `user_empresa`. Si pide otra se responde 404, igual que
        en M5, para no revelar que existe. Los demás roles no se restringen.
        """
        if _normalize_role_name(usuario.get("role_name")) != "empresa":
            return

        no_encontrada = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
        try:
            uuid.UUID(str(id_empresa))
        except ValueError:
            raise no_encontrada

        result = await self.db.execute(
            text("""
                SELECT id_user_empresa
                FROM user_empresa
                WHERE id_usuario = :id_usuario
                  AND id_empresa = :id_empresa
                  AND estado = 'Activo';
            """),
            {"id_usuario": str(usuario.get("id_usuario")), "id_empresa": str(id_empresa)},
        )
        if not result.mappings().first():
            raise no_encontrada

    # ============================================================
    # CONTACTOS DE SEDE (EMP-027 / EMP-028 / EMP-029)
    # ============================================================

    async def _sede_o_404(self, id_empresa: str, id_sede: str) -> dict:
        sede = await self.get_sede_by_id(id_empresa, id_sede)
        if not sede:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada")
        return sede

    async def _contacto_o_404(self, id_sede: str, id_contacto: str) -> dict:
        result = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CONTACTO}
                FROM contacto_sede
                WHERE id_contacto = :id_contacto
                  AND id_sede = :id_sede;
            """),
            {"id_contacto": id_contacto, "id_sede": id_sede},
        )
        contacto = result.mappings().first()
        if not contacto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El contacto no existe en esta sede.",
            )
        return dict(contacto)

    async def get_contactos(self, id_empresa: str, id_sede: str) -> list[dict]:
        await self._sede_o_404(id_empresa, id_sede)
        result = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CONTACTO}
                FROM contacto_sede
                WHERE id_sede = :id_sede
                ORDER BY nombre ASC;
            """),
            {"id_sede": id_sede},
        )
        return [dict(row) for row in result.mappings().all()]

    async def create_contacto(self, id_empresa: str, id_sede: str, data: dict) -> dict:
        await self._sede_o_404(id_empresa, id_sede)
        result = await self.db.execute(
            text(f"""
                INSERT INTO contacto_sede (id_sede, nombre, cargo, telefono, correo)
                VALUES (:id_sede, :nombre, :cargo, :telefono, :correo)
                RETURNING {COLUMNAS_CONTACTO};
            """),
            {
                "id_sede": id_sede,
                "nombre": data.get("nombre"),
                "cargo": data.get("cargo"),
                "telefono": data.get("telefono"),
                "correo": data.get("correo"),
            },
        )
        await self.db.commit()
        return dict(result.mappings().first())

    async def update_contacto(self, id_empresa: str, id_sede: str, id_contacto: str, data: dict) -> dict:
        await self._sede_o_404(id_empresa, id_sede)
        actual = await self._contacto_o_404(id_sede, id_contacto)

        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se recibió ningún campo para actualizar.",
            )

        payload = {
            "id_contacto": id_contacto,
            # El nombre es obligatorio: si llega vacío se conserva el actual.
            "nombre": data.get("nombre") or actual.get("nombre"),
            "cargo": data.get("cargo", actual.get("cargo")),
            "telefono": data.get("telefono", actual.get("telefono")),
            "correo": data.get("correo", actual.get("correo")),
        }
        result = await self.db.execute(
            text(f"""
                UPDATE contacto_sede
                SET nombre = :nombre, cargo = :cargo, telefono = :telefono, correo = :correo
                WHERE id_contacto = :id_contacto
                RETURNING {COLUMNAS_CONTACTO};
            """),
            payload,
        )
        await self.db.commit()
        return dict(result.mappings().first())

    async def delete_contacto(self, id_empresa: str, id_sede: str, id_contacto: str) -> dict:
        await self._sede_o_404(id_empresa, id_sede)
        contacto = await self._contacto_o_404(id_sede, id_contacto)
        await self.db.execute(
            text("DELETE FROM contacto_sede WHERE id_contacto = :id_contacto;"),
            {"id_contacto": id_contacto},
        )
        await self.db.commit()
        return contacto

    async def get_documentos_by_empresa(self, id_empresa: str) -> list[dict]:
        query = text("""
            SELECT * FROM documento_empresa WHERE id_empresa = :id_empresa;
        """)
        result = await self.db.execute(query, {"id_empresa": id_empresa})
        return [dict(row) for row in result.mappings().all()]

    # ============================================================
    # CONSULTA PUBLICA (M11)
    # ============================================================
    # Metodos que usan los endpoints publicos del portal. Se perdieron al
    # integrar los modulos de empresa y apelaciones; se restauran tal cual
    # estaban en el commit 353ea89.

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
