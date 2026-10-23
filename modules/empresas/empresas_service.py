import uuid

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
    # La consulta publica (M11) se movio a modules/consultas_p/.
    # ============================================================
