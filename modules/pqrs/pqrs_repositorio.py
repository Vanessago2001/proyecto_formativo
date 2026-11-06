"""
PQRS · acceso a datos (SQL nativo).

Solo consultas: ninguna regla de negocio vive aquí. El servicio
(pqrs_service.py) decide; este archivo lee y escribe las tablas `pqrs_caso*`
creadas por pqrs_bootstrap.py. Las pruebas sustituyen esta clase por una
versión en memoria con la misma interfaz.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COLUMNAS_CASO = """
    c.id_pqrs, c.radicado, c.tipo, c.estado, c.canal, c.asunto, c.descripcion,
    c.nombre_peticionario, c.tipo_documento, c.numero_documento, c.correo,
    c.telefono, c.empresa_nombre, c.nit, c.id_empresa, c.id_auditoria,
    c.acepta_tratamiento_datos, c.id_usuario_peticionario, c.id_usuario_radica,
    c.id_responsable, c.plazo_dias_habiles, c.fecha_radicacion, c.fecha_limite,
    c.respuesta, c.fecha_respuesta, c.fecha_cierre, c.veces_reabierta,
    c.fecha_actualizacion,
    COALESCE(r.nombre, r.correo) AS responsable
"""

# Columnas que el servicio puede cambiar con `actualizar`.
COLUMNAS_ACTUALIZABLES = frozenset({
    "estado", "id_responsable", "respuesta", "fecha_respuesta", "fecha_cierre",
    "veces_reabierta", "fecha_limite", "plazo_dias_habiles",
})

# Asignaciones del auditor que cuentan (mismo criterio que M7 y los reportes).
_AUDITORIAS_DEL_AUDITOR = """
    SELECT a.id_auditoria
    FROM auditoria a
    JOIN auditores_solicitud s ON s.id_solicitud = a.id_solicitud
    WHERE s.id_auditor = :id_usuario
      AND COALESCE(s.estado_asignacion, '') NOT IN ('Cancelada', 'Reasignado')
"""


def _id(valor) -> str | None:
    return None if valor is None else str(valor)


class PqrsRepositorio:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    # -- radicado y plazos --------------------------------------------------

    async def siguiente_consecutivo(self) -> int:
        resultado = await self.db.execute(text("SELECT nextval('pqrs_caso_radicado_seq');"))
        return int(resultado.scalar())

    async def plazos(self) -> list[dict]:
        resultado = await self.db.execute(text(
            "SELECT tipo, dias_habiles, dias_alerta, fecha_actualizacion FROM pqrs_plazo_tipo ORDER BY tipo;"
        ))
        return [dict(f) for f in resultado.mappings().all()]

    async def actualizar_plazo(self, tipo: str, dias: int, alerta: int, id_usuario) -> dict | None:
        resultado = await self.db.execute(
            text("""
                INSERT INTO pqrs_plazo_tipo (tipo, dias_habiles, dias_alerta, actualizado_por, fecha_actualizacion)
                VALUES (:tipo, :dias, :alerta, :id_usuario, CURRENT_TIMESTAMP)
                ON CONFLICT (tipo) DO UPDATE
                SET dias_habiles = EXCLUDED.dias_habiles,
                    dias_alerta = EXCLUDED.dias_alerta,
                    actualizado_por = EXCLUDED.actualizado_por,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                RETURNING tipo, dias_habiles, dias_alerta, fecha_actualizacion;
            """),
            {"tipo": tipo, "dias": dias, "alerta": alerta, "id_usuario": _id(id_usuario)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    # -- casos ---------------------------------------------------------------

    async def insertar(self, datos: dict) -> UUID:
        resultado = await self.db.execute(
            text("""
                INSERT INTO pqrs_caso (
                    radicado, tipo, estado, canal, asunto, descripcion,
                    nombre_peticionario, tipo_documento, numero_documento, correo,
                    telefono, empresa_nombre, nit, id_empresa, id_auditoria,
                    acepta_tratamiento_datos, id_usuario_peticionario, id_usuario_radica,
                    plazo_dias_habiles, fecha_radicacion, fecha_limite
                ) VALUES (
                    :radicado, :tipo, :estado, :canal, :asunto, :descripcion,
                    :nombre_peticionario, :tipo_documento, :numero_documento, :correo,
                    :telefono, :empresa_nombre, :nit, :id_empresa, :id_auditoria,
                    :acepta_tratamiento_datos, :id_usuario_peticionario, :id_usuario_radica,
                    :plazo_dias_habiles, :fecha_radicacion, :fecha_limite
                )
                RETURNING id_pqrs;
            """),
            {**datos, **{k: _id(datos.get(k)) for k in (
                "id_empresa", "id_auditoria", "id_usuario_peticionario", "id_usuario_radica")}},
        )
        return resultado.scalar()

    async def obtener(self, id_pqrs) -> dict | None:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CASO}
                FROM pqrs_caso c
                LEFT JOIN usuario r ON r.id_usuario = c.id_responsable
                WHERE c.id_pqrs = :id_pqrs;
            """),
            {"id_pqrs": _id(id_pqrs)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def obtener_por_radicado(self, radicado: str) -> dict | None:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CASO}
                FROM pqrs_caso c
                LEFT JOIN usuario r ON r.id_usuario = c.id_responsable
                WHERE c.radicado = :radicado;
            """),
            {"radicado": radicado},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def actualizar(self, id_pqrs, estado_esperado: str, campos: dict) -> bool:
        """
        Cambia los campos solo si la PQRS sigue en `estado_esperado`: dos
        gestores actuando a la vez no pueden pisarse (el segundo recibe False).
        """
        desconocidas = set(campos) - COLUMNAS_ACTUALIZABLES
        if desconocidas:
            raise ValueError(f"Columnas no actualizables: {sorted(desconocidas)}")
        asignaciones = ", ".join(f"{columna} = :{columna}" for columna in campos)
        parametros = {
            **{k: (_id(v) if k == "id_responsable" else v) for k, v in campos.items()},
            "id_pqrs": _id(id_pqrs),
            "estado_esperado": estado_esperado,
        }
        resultado = await self.db.execute(
            text(f"""
                UPDATE pqrs_caso
                SET {asignaciones}, fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id_pqrs = :id_pqrs AND estado = :estado_esperado
                RETURNING id_pqrs;
            """),
            parametros,
        )
        return resultado.scalar() is not None

    async def listar(self, alcance: dict, filtros: dict, limite: int = 500) -> list[dict]:
        condiciones: list[str] = []
        parametros: dict = {"limite": int(limite)}

        tipo_alcance = alcance.get("tipo")
        if tipo_alcance == "empresa":
            parametros["id_usuario"] = _id(alcance["id_usuario"])
            condiciones.append("""(
                c.id_usuario_peticionario = :id_usuario
                OR c.id_empresa IN (
                    SELECT ue.id_empresa FROM user_empresa ue
                    WHERE ue.id_usuario = :id_usuario AND ue.estado = 'Activo'
                )
            )""")
        elif tipo_alcance == "auditor":
            parametros["id_usuario"] = _id(alcance["id_usuario"])
            condiciones.append(f"""(
                c.id_responsable = :id_usuario
                OR c.id_auditoria IN ({_AUDITORIAS_DEL_AUDITOR})
            )""")
        elif tipo_alcance != "todas":
            raise ValueError("Alcance de consulta desconocido.")

        if filtros.get("estado"):
            condiciones.append("c.estado = :estado")
            parametros["estado"] = filtros["estado"]
        if filtros.get("tipo"):
            condiciones.append("c.tipo = :tipo")
            parametros["tipo"] = filtros["tipo"]
        if filtros.get("desde"):
            condiciones.append("(c.fecha_radicacion AT TIME ZONE 'America/Bogota')::date >= :desde")
            parametros["desde"] = filtros["desde"]
        if filtros.get("hasta"):
            condiciones.append("(c.fecha_radicacion AT TIME ZONE 'America/Bogota')::date <= :hasta")
            parametros["hasta"] = filtros["hasta"]
        if filtros.get("id_responsable"):
            condiciones.append("c.id_responsable = :id_responsable")
            parametros["id_responsable"] = _id(filtros["id_responsable"])
        if filtros.get("abiertas"):
            condiciones.append("c.estado NOT IN ('Respondida', 'Cerrada')")
        if filtros.get("q"):
            condiciones.append("""(
                c.radicado ILIKE :q OR c.asunto ILIKE :q OR c.nombre_peticionario ILIKE :q
                OR c.numero_documento ILIKE :q OR COALESCE(c.empresa_nombre, '') ILIKE :q
            )""")
            buscado = str(filtros["q"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parametros["q"] = f"%{buscado}%"

        donde = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CASO}
                FROM pqrs_caso c
                LEFT JOIN usuario r ON r.id_usuario = c.id_responsable
                {donde}
                ORDER BY c.fecha_radicacion DESC
                LIMIT :limite;
            """),
            parametros,
        )
        return [dict(f) for f in resultado.mappings().all()]

    # -- historial y adjuntos -------------------------------------------------

    async def registrar_historial(self, datos: dict) -> None:
        await self.db.execute(
            text("""
                INSERT INTO pqrs_caso_historial (
                    id_pqrs, accion, estado_anterior, estado_nuevo, comentario,
                    id_usuario, actor, visible_peticionario, es_peticionario
                ) VALUES (
                    :id_pqrs, :accion, :estado_anterior, :estado_nuevo, :comentario,
                    :id_usuario, :actor, :visible_peticionario, :es_peticionario
                );
            """),
            {**datos, "id_pqrs": _id(datos["id_pqrs"]), "id_usuario": _id(datos.get("id_usuario"))},
        )

    async def historial(self, id_pqrs, solo_visibles: bool = False) -> list[dict]:
        filtro = "AND h.visible_peticionario" if solo_visibles else ""
        resultado = await self.db.execute(
            text(f"""
                SELECT h.id_historial, h.accion, h.estado_anterior, h.estado_nuevo,
                       h.comentario, h.id_usuario, h.actor, h.visible_peticionario,
                       h.es_peticionario, h.fecha
                FROM pqrs_caso_historial h
                WHERE h.id_pqrs = :id_pqrs {filtro}
                ORDER BY h.fecha, h.id_historial;
            """),
            {"id_pqrs": _id(id_pqrs)},
        )
        return [dict(f) for f in resultado.mappings().all()]

    async def insertar_adjunto(self, datos: dict) -> dict:
        resultado = await self.db.execute(
            text("""
                INSERT INTO pqrs_caso_adjunto (
                    id_pqrs, nombre_archivo, ruta_archivo, tipo_mime, tamano_bytes,
                    hash_sha256, origen, id_usuario
                ) VALUES (
                    :id_pqrs, :nombre_archivo, :ruta_archivo, :tipo_mime, :tamano_bytes,
                    :hash_sha256, :origen, :id_usuario
                )
                RETURNING id_adjunto, id_pqrs, nombre_archivo, tipo_mime, tamano_bytes,
                          origen, fecha_subida;
            """),
            {**datos, "id_pqrs": _id(datos["id_pqrs"]), "id_usuario": _id(datos.get("id_usuario"))},
        )
        return dict(resultado.mappings().first())

    async def adjuntos(self, id_pqrs) -> list[dict]:
        resultado = await self.db.execute(
            text("""
                SELECT id_adjunto, id_pqrs, nombre_archivo, tipo_mime, tamano_bytes, origen, fecha_subida
                FROM pqrs_caso_adjunto
                WHERE id_pqrs = :id_pqrs
                ORDER BY fecha_subida;
            """),
            {"id_pqrs": _id(id_pqrs)},
        )
        return [dict(f) for f in resultado.mappings().all()]

    async def adjunto(self, id_pqrs, id_adjunto) -> dict | None:
        resultado = await self.db.execute(
            text("""
                SELECT id_adjunto, id_pqrs, nombre_archivo, ruta_archivo, tipo_mime, origen
                FROM pqrs_caso_adjunto
                WHERE id_pqrs = :id_pqrs AND id_adjunto = :id_adjunto;
            """),
            {"id_pqrs": _id(id_pqrs), "id_adjunto": _id(id_adjunto)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    # -- datos de otros módulos (solo lectura) -------------------------------

    async def empresas_de_usuario(self, id_usuario) -> set[str]:
        resultado = await self.db.execute(
            text("""
                SELECT id_empresa FROM user_empresa
                WHERE id_usuario = :id_usuario AND estado = 'Activo';
            """),
            {"id_usuario": _id(id_usuario)},
        )
        return {str(f[0]) for f in resultado.all()}

    async def empresa(self, id_empresa) -> dict | None:
        resultado = await self.db.execute(
            text("SELECT id_empresa, nombre, nit FROM empresa WHERE id_empresa = :id_empresa;"),
            {"id_empresa": _id(id_empresa)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def empresa_de_auditoria(self, id_auditoria) -> dict | None:
        resultado = await self.db.execute(
            text("""
                SELECT a.id_auditoria, s.id_empresa
                FROM auditoria a
                LEFT JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                WHERE a.id_auditoria = :id_auditoria;
            """),
            {"id_auditoria": _id(id_auditoria)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def auditor_vinculado(self, id_auditoria, id_usuario) -> bool:
        if id_auditoria is None:
            return False
        resultado = await self.db.execute(
            text(f"""
                SELECT EXISTS (
                    {_AUDITORIAS_DEL_AUDITOR}
                    AND a.id_auditoria = :id_auditoria
                );
            """),
            {"id_auditoria": _id(id_auditoria), "id_usuario": _id(id_usuario)},
        )
        return bool(resultado.scalar())

    async def usuario(self, id_usuario) -> dict | None:
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, u.nombre, u.correo, u.estado, r.nombre AS role_name
                FROM usuario u
                LEFT JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.id_usuario = :id_usuario;
            """),
            {"id_usuario": _id(id_usuario)},
        )
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def usuarios_internos_activos(self) -> list[dict]:
        """Administradores, auxiliares y auditores activos (candidatos a responsable)."""
        resultado = await self.db.execute(text("""
            SELECT u.id_usuario, u.nombre, u.correo, u.estado, r.nombre AS role_name
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE u.estado = 'Activo'
              AND LOWER(r.nombre) IN ('administrador', 'super administrador', 'auxiliar', 'auditor')
            ORDER BY r.nombre, u.nombre;
        """))
        return [dict(f) for f in resultado.mappings().all()]

