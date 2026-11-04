"""Consultas y operaciones del módulo administrativo de auditores registrados.

Toda la información se obtiene de las tablas existentes del sistema. No se
crean tablas nuevas: el estado de acceso del auditor vive en ``usuario.estado``
y el resto de la hoja de vida se reparte entre ``perfil_auditor``,
``documento_auditor``, ``conflicto_interes``, ``certificacion_auditor``,
``competencia_auditor``, ``titulo_academico``, ``experiencia_laboral`` y
``experiencia_auditoria``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
RAIZ_UPLOADS = (RAIZ_PROYECTO / "uploads").resolve()


def _resolver_archivo(url: str | None) -> Path | None:
    """Convierte una URL interna de ``/uploads/...`` en una ruta segura."""

    if not url:
        return None

    limpio = unquote(str(url).split("?", 1)[0].strip())
    if not limpio:
        return None

    if limpio.startswith("/uploads/"):
        relativo = limpio[len("/uploads/") :]
    elif limpio.startswith("uploads/"):
        relativo = limpio[len("uploads/") :]
    else:
        return None

    candidato = (RAIZ_UPLOADS / relativo).resolve()
    try:
        candidato.relative_to(RAIZ_UPLOADS)
    except ValueError:
        return None

    return candidato if candidato.is_file() else None


def _info_archivo(url: str | None) -> dict[str, Any]:
    ruta = _resolver_archivo(url)
    if ruta is None:
        return {"disponible": False, "formato": "", "tamano": 0}

    try:
        tamano = ruta.stat().st_size
    except OSError:
        tamano = 0

    return {
        "disponible": True,
        "formato": ruta.suffix.lstrip(".").upper(),
        "tamano": tamano,
    }


def _decorar_archivo(item: dict[str, Any], campo: str = "url_archivo") -> dict[str, Any]:
    info = _info_archivo(item.get(campo))
    item["archivo_disponible"] = info["disponible"]
    item["formato"] = info["formato"]
    item["tamano"] = info["tamano"]
    return item


class AuditoresRegistradosService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # LISTADO
    # ------------------------------------------------------------------
    async def listar(
        self,
        busqueda: str | None = None,
        estado: str | None = None,
    ) -> list[dict[str, Any]]:
        consulta = """
            SELECT
                u.id_usuario,
                u.nombre,
                u.correo,
                u.tipo_doc,
                u.num_doc,
                u.estado,
                u.estado_auditor,
                u.ultimo_inicio_sesion,
                p.foto_url,
                p.ciudad_residencia,
                p.departamento_residencia,
                p.modalidad_preferida,
                p.resumen_profesional,
                (
                    SELECT COUNT(*)
                    FROM documento_auditor d
                    WHERE d.id_usuario = u.id_usuario
                ) AS total_documentos,
                (
                    SELECT COUNT(*)
                    FROM conflicto_interes c
                    WHERE c.id_usuario = u.id_usuario
                ) AS total_conflictos,
                (
                    SELECT COUNT(*)
                    FROM certificacion_auditor ca
                    WHERE ca.id_usuario = u.id_usuario
                ) AS total_certificaciones
            FROM usuario u
            INNER JOIN rol r
                ON r.id_rol = u.rol_id
            LEFT JOIN LATERAL (
                SELECT
                    p.foto_url,
                    p.ciudad_residencia,
                    p.departamento_residencia,
                    p.modalidad_preferida,
                    p.resumen_profesional
                FROM perfil_auditor p
                WHERE p.id_usuario = u.id_usuario
                ORDER BY
                    (COALESCE(NULLIF(TRIM(p.foto_url), ''), '') <> '') DESC,
                    p.id_perfil DESC
                LIMIT 1
            ) p ON TRUE
            WHERE LOWER(TRIM(r.nombre)) = 'auditor'
        """
        parametros: dict[str, Any] = {}

        if busqueda and busqueda.strip():
            consulta += """
                AND (
                    LOWER(COALESCE(u.nombre, '')) LIKE LOWER(:busqueda)
                    OR LOWER(COALESCE(u.tipo_doc, '')) LIKE LOWER(:busqueda)
                    OR LOWER(COALESCE(u.num_doc, '')) LIKE LOWER(:busqueda)
                    OR LOWER(COALESCE(u.correo, '')) LIKE LOWER(:busqueda)
                )
            """
            parametros["busqueda"] = f"%{busqueda.strip()}%"

        if estado and estado.strip():
            consulta += " AND LOWER(COALESCE(u.estado, '')) = LOWER(:estado)"
            parametros["estado"] = estado.strip()

        consulta += " ORDER BY LOWER(COALESCE(u.nombre, '')) ASC, u.num_doc ASC"

        resultado = await self.db.execute(text(consulta), parametros)
        return [dict(fila) for fila in resultado.mappings().all()]

    # ------------------------------------------------------------------
    # HOJA DE VIDA
    # ------------------------------------------------------------------
    async def obtener(self, id_usuario: UUID) -> dict[str, Any]:
        base = await self.db.execute(
            text(
                """
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.correo,
                    u.tipo_doc,
                    u.num_doc,
                    u.estado,
                    u.estado_auditor,
                    u.ultimo_inicio_sesion,
                    r.nombre AS rol,
                    p.id_perfil,
                    p.foto_url,
                    p.ciudad_residencia,
                    p.departamento_residencia,
                    p.modalidad_preferida,
                    p.resumen_profesional,
                    p.calificacion_promedio,
                    p.id_postulacion AS id_postulacion_perfil,
                    pa.id_postulacion,
                    pa.estado AS estado_postulacion,
                    pa.fecha_postulacion,
                    pa.fecha_revision,
                    pa.fecha_aprobacion,
                    pa.fecha_rechazo,
                    pa.motivo_rechazo,
                    (
                        SELECT MIN(pa2.fecha_postulacion)
                        FROM postulacion_auditor pa2
                        WHERE pa2.id_usuario = u.id_usuario
                    ) AS fecha_primera_postulacion
                FROM usuario u
                INNER JOIN rol r
                    ON r.id_rol = u.rol_id
                LEFT JOIN LATERAL (
                    SELECT
                        p.id_perfil,
                        p.foto_url,
                        p.ciudad_residencia,
                        p.departamento_residencia,
                        p.modalidad_preferida,
                        p.resumen_profesional,
                        p.calificacion_promedio,
                        p.id_postulacion
                    FROM perfil_auditor p
                    WHERE p.id_usuario = u.id_usuario
                    ORDER BY
                        (COALESCE(NULLIF(TRIM(p.foto_url), ''), '') <> '') DESC,
                        p.id_perfil DESC
                    LIMIT 1
                ) p ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        pa.id_postulacion,
                        pa.estado,
                        pa.fecha_postulacion,
                        pa.fecha_revision,
                        pa.fecha_aprobacion,
                        pa.fecha_rechazo,
                        pa.motivo_rechazo
                    FROM postulacion_auditor pa
                    WHERE pa.id_usuario = u.id_usuario
                    ORDER BY
                        COALESCE(
                            pa.fecha_aprobacion,
                            pa.fecha_rechazo,
                            pa.fecha_revision,
                            pa.fecha_postulacion
                        ) DESC NULLS LAST
                    LIMIT 1
                ) pa ON TRUE
                WHERE LOWER(TRIM(r.nombre)) = 'auditor'
                  AND u.id_usuario = :id_usuario
                LIMIT 1
                """
            ),
            {"id_usuario": id_usuario},
        )
        auditor = base.mappings().first()
        if auditor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Auditor no encontrado.",
            )

        detalle = dict(auditor)
        detalle.update(_info_archivo(detalle.get("foto_url")))

        detalle["documentos"] = await self._documentos(id_usuario)
        detalle["conflictos"] = await self._conflictos(id_usuario)
        detalle["certificaciones"] = await self._certificaciones(id_usuario)
        detalle["competencias"] = await self._competencias(id_usuario)
        detalle["titulos"] = await self._titulos(id_usuario)
        detalle["experiencia_laboral"] = await self._experiencia_laboral(id_usuario)
        detalle["experiencia_auditoria"] = await self._experiencia_auditoria(id_usuario)
        detalle["postulaciones"] = await self._postulaciones(id_usuario)

        detalle["resumen"] = {
            "documentos": len(detalle["documentos"]),
            "conflictos": len(detalle["conflictos"]),
            "certificaciones": len(detalle["certificaciones"]),
            "competencias": len(detalle["competencias"]),
            "titulos": len(detalle["titulos"]),
            "experiencia_laboral": len(detalle["experiencia_laboral"]),
            "experiencia_auditoria": len(detalle["experiencia_auditoria"]),
        }
        return detalle

    async def _documentos(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    id_documento,
                    id_postulacion,
                    nombre_archivo,
                    tipo_documento,
                    categoria_documento,
                    url_archivo,
                    fecha_subida,
                    estado_revision,
                    observacion_revision,
                    id_titulo,
                    id_experiencia_laboral,
                    id_experiencia_auditoria
                FROM documento_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY
                    LOWER(COALESCE(categoria_documento, '')) ASC,
                    fecha_subida DESC NULLS LAST,
                    LOWER(nombre_archivo) ASC
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [_decorar_archivo(dict(fila)) for fila in resultado.mappings().all()]

    async def _conflictos(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    c.id_conflicto,
                    c.id_empresa,
                    e.nombre AS empresa,
                    e.nit AS empresa_nit,
                    c.tipo_conflicto,
                    c.descripcion,
                    c.bloquea_asignacion,
                    c.fecha_declaracion,
                    c.estado,
                    c.id_postulacion
                FROM conflicto_interes c
                LEFT JOIN empresa e
                    ON e.id_empresa = c.id_empresa
                WHERE c.id_usuario = :id_usuario
                ORDER BY c.fecha_declaracion DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _certificaciones(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    ca.id_certificacion,
                    ca.id_norma,
                    ca.tipo_certificacion,
                    ca.nombre_archivo,
                    ca.url_archivo,
                    ca.descripcion,
                    ca.fecha_registro,
                    ca.estado,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version
                FROM certificacion_auditor ca
                LEFT JOIN norma n
                    ON n.id_norma = ca.id_norma
                WHERE ca.id_usuario = :id_usuario
                ORDER BY ca.fecha_registro DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [_decorar_archivo(dict(fila)) for fila in resultado.mappings().all()]

    async def _competencias(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    co.id_competencia,
                    co.tipo_competencia,
                    co.id_norma,
                    co.codigo_sector_iaf,
                    co.titulo_institucion,
                    co.descripcion,
                    co.fecha_inicio,
                    co.fecha_fin,
                    co.es_vigente,
                    co.estado_validacion,
                    co.observacion_validacion,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version
                FROM competencia_auditor co
                LEFT JOIN norma n
                    ON n.id_norma = co.id_norma
                WHERE co.id_usuario = :id_usuario
                ORDER BY
                    co.es_vigente DESC,
                    co.fecha_fin DESC NULLS LAST,
                    LOWER(COALESCE(co.titulo_institucion, '')) ASC
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _titulos(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    id_titulo,
                    nivel,
                    titulo,
                    institucion,
                    fecha_grado,
                    estado_validacion,
                    observacion_validacion,
                    created_at
                FROM titulo_academico
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_grado DESC NULLS LAST, created_at DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _experiencia_laboral(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    id_experiencia,
                    empresa,
                    cargo,
                    fecha_inicio,
                    fecha_fin,
                    descripcion,
                    estado_validacion,
                    observacion_validacion
                FROM experiencia_laboral
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_inicio DESC NULLS LAST, created_at DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _experiencia_auditoria(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    id_experiencia,
                    organizacion,
                    rol_auditoria,
                    tipo_auditoria,
                    fecha_inicio,
                    fecha_fin,
                    descripcion,
                    estado_validacion,
                    observacion_validacion
                FROM experiencia_auditoria
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_inicio DESC NULLS LAST, created_at DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _postulaciones(self, id_usuario: UUID) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    id_postulacion,
                    estado,
                    fecha_postulacion,
                    fecha_revision,
                    fecha_aprobacion,
                    fecha_rechazo,
                    motivo_rechazo
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC NULLS LAST
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ------------------------------------------------------------------
    # ESTADO DE LA CUENTA
    # ------------------------------------------------------------------
    async def cambiar_estado(
        self,
        id_usuario: UUID,
        nuevo_estado: str,
        id_usuario_actor: UUID | None = None,
    ) -> dict[str, Any]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.estado,
                    r.nombre AS rol
                FROM usuario u
                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id
                WHERE u.id_usuario = :id_usuario
                LIMIT 1
                FOR UPDATE
                """
            ),
            {"id_usuario": id_usuario},
        )
        auditor = resultado.mappings().first()
        if auditor is None or (auditor["rol"] or "").strip().lower() != "auditor":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Auditor no encontrado.",
            )

        actual = (auditor["estado"] or "").strip().capitalize()
        if actual == nuevo_estado:
            mensaje = (
                "El auditor ya se encuentra inactivo."
                if nuevo_estado == "Inactivo"
                else "El auditor ya se encuentra activo."
            )
            return {
                "id_usuario": auditor["id_usuario"],
                "nombre": auditor["nombre"],
                "estado": actual,
                "mensaje": mensaje,
                "sin_cambios": True,
                "retiros": self._resumen_retiro_vacio(),
            }

        if nuevo_estado not in ("Activo", "Inactivo"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El estado solicitado no es valido.",
            )

        retiros: dict[str, Any] = self._resumen_retiro_vacio()
        if nuevo_estado == "Inactivo":
            retiros = await self._retirar_asignaciones_por_desactivacion(
                id_usuario,
                id_usuario_actor,
            )

        await self.db.execute(
            text("UPDATE usuario SET estado = :estado WHERE id_usuario = :id_usuario"),
            {"estado": nuevo_estado, "id_usuario": id_usuario},
        )

        mensaje = (
            "Auditor inactivado correctamente."
            if nuevo_estado == "Inactivo"
            else "Auditor reactivado correctamente."
        )
        if nuevo_estado == "Inactivo" and retiros.get("retiros_realizados", 0) > 0:
            mensaje += (
                f" Se retiraron {retiros['retiros_realizados']} asignacion(es) "
                f"de auditorias futuras."
            )
        if retiros.get("en_curso"):
            mensaje += (
                f" {len(retiros['en_curso'])} auditoria(s) en curso quedaron "
                "para revision manual."
            )

        return {
            "id_usuario": auditor["id_usuario"],
            "nombre": auditor["nombre"],
            "estado": nuevo_estado,
            "mensaje": mensaje,
            "sin_cambios": False,
            "retiros": retiros,
        }

    @staticmethod
    def _resumen_retiro_vacio() -> dict[str, Any]:
        return {
            "retiros_realizados": 0,
            "asignaciones_canceladas": 0,
            "detalles_eliminados": 0,
            "visitas_afectadas": [],
            "en_curso": [],
            "terminales": [],
            "sin_programacion": [],
        }

    async def previsualizar_desactivacion(self, id_usuario: UUID) -> dict[str, Any]:
        clasificacion = await self._clasificar_asignaciones(id_usuario)
        return {
            "id_usuario": id_usuario,
            "futuras": clasificacion["futuras"],
            "en_curso": clasificacion["en_curso"],
            "terminales": clasificacion["terminales"],
            "sin_programacion": clasificacion["sin_programacion"],
            "totales": {
                "futuras": len(clasificacion["futuras"]),
                "en_curso": len(clasificacion["en_curso"]),
                "terminales": len(clasificacion["terminales"]),
                "sin_programacion": len(clasificacion["sin_programacion"]),
            },
        }

    async def consultar_historial_asignaciones(
        self, id_usuario: UUID
    ) -> list[dict[str, Any]]:
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    h.id_historial,
                    h.id_solicitud,
                    h.id_auditor,
                    h.accion,
                    h.motivo,
                    h.estado_anterior,
                    h.estado_nuevo,
                    h.id_usuario_accion,
                    h.fecha,
                    h.id_asignacion,
                    h.id_programacion,
                    s.numero_radicado,
                    p.estado AS estado_programacion,
                    p.fecha_inicio AS fecha_inicio_programacion,
                    p.fecha_fin AS fecha_fin_programacion,
                    se.nombre_sede,
                    e.nombre AS empresa_nombre
                FROM historial_asignacion_auditor h
                LEFT JOIN solicitud s
                    ON s.id_solicitud = h.id_solicitud
                LEFT JOIN programacion_visita p
                    ON p.id_programacion = h.id_programacion
                LEFT JOIN sede_empresa se
                    ON se.id_sede = p.id_sede
                LEFT JOIN empresa e
                    ON e.id_empresa = p.id_empresa
                WHERE h.id_auditor = :id_usuario
                ORDER BY h.fecha DESC, h.id_historial DESC
                """
            ),
            {"id_usuario": id_usuario},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _clasificar_asignaciones(self, id_usuario: UUID) -> dict[str, Any]:
        ahora = datetime.now()
        terminales = {"CANCELADA", "CANCELADO", "EJECUTADA", "EJECUTADO", "FINALIZADA", "FINALIZADO"}

        futuras_result = await self.db.execute(
            text(
                """
                SELECT
                    d.id_detalle,
                    d.id_programacion,
                    d.id_usuario,
                    p.id_solicitud,
                    p.estado AS estado_programacion,
                    p.fecha_inicio,
                    p.fecha_fin,
                    s.numero_radicado,
                    e.nombre AS empresa_nombre,
                    se.nombre_sede,
                    (
                        SELECT COUNT(*)
                        FROM detalle_programacion_auditor dt
                        WHERE dt.id_programacion = p.id_programacion
                    ) AS auditores_total
                FROM detalle_programacion_auditor d
                INNER JOIN programacion_visita p
                    ON p.id_programacion = d.id_programacion
                LEFT JOIN solicitud s
                    ON s.id_solicitud = p.id_solicitud
                LEFT JOIN empresa e
                    ON e.id_empresa = s.id_empresa
                LEFT JOIN sede_empresa se
                    ON se.id_sede = p.id_sede
                WHERE d.id_usuario = :id_usuario
                ORDER BY p.fecha_inicio
                """
            ),
            {"id_usuario": id_usuario},
        )
        filas = [dict(fila) for fila in futuras_result.mappings().all()]

        futuras: list[dict[str, Any]] = []
        en_curso: list[dict[str, Any]] = []
        terminales_lista: list[dict[str, Any]] = []
        for fila in filas:
            estado = str(fila.get("estado_programacion") or "").strip().upper()
            inicio = fila.get("fecha_inicio")
            fin = fila.get("fecha_fin")
            if estado in terminales or (fin is not None and fin < ahora):
                terminales_lista.append(fila)
            elif inicio is not None and inicio > ahora:
                futuras.append(fila)
            elif inicio is not None and fin is not None and inicio <= ahora <= fin:
                en_curso.append(fila)
            else:
                terminales_lista.append(fila)

        asignaciones_result = await self.db.execute(
            text(
                """
                SELECT
                    a.id,
                    a.id_solicitud,
                    a.estado_asignacion,
                    s.numero_radicado
                FROM auditores_solicitud a
                LEFT JOIN solicitud s
                    ON s.id_solicitud = a.id_solicitud
                WHERE a.id_auditor = :id_usuario
                  AND UPPER(TRIM(COALESCE(a.estado_asignacion, ''))) IN
                      ('PROPUESTO', 'ASIGNADO', 'AGENDADA', 'PROGRAMADA', 'CONFIRMADO')
                ORDER BY a.id
                """
            ),
            {"id_usuario": id_usuario},
        )
        asignaciones = [dict(fila) for fila in asignaciones_result.mappings().all()]

        ids_con_futura = {str(fila["id_solicitud"]) for fila in futuras}
        sin_programacion = [
            fila for fila in asignaciones
            if str(fila["id_solicitud"]) not in ids_con_futura
        ]

        return {
            "futuras": futuras,
            "en_curso": en_curso,
            "terminales": terminales_lista,
            "sin_programacion": sin_programacion,
        }

    async def _retirar_asignaciones_por_desactivacion(
        self, id_usuario: UUID, id_usuario_actor: UUID | None
    ) -> dict[str, Any]:
        clasificacion = await self._clasificar_asignaciones(id_usuario)
        futuras = clasificacion["futuras"]
        en_curso = clasificacion["en_curso"]
        terminales = clasificacion["terminales"]
        sin_programacion = clasificacion["sin_programacion"]

        motivo = "Auditor retirado por desactivacion de su cuenta."
        estados_activos = (
            "PROPUESTO", "ASIGNADO", "AGENDADA", "PROGRAMADA", "CONFIRMADO"
        )

        resultado_update = await self.db.execute(
            text(
                """
                UPDATE auditores_solicitud
                SET estado_asignacion = 'Cancelada',
                    fecha_cancelacion = CURRENT_TIMESTAMP,
                    motivo_cancelacion = :motivo,
                    usuario_cancela = :actor
                WHERE id_auditor = :id_usuario
                  AND UPPER(TRIM(COALESCE(estado_asignacion, ''))) IN
                      ('PROPUESTO', 'ASIGNADO', 'AGENDADA', 'PROGRAMADA', 'CONFIRMADO')
                RETURNING id, id_solicitud, estado_asignacion
                """
            ),
            {
                "id_usuario": id_usuario,
                "motivo": motivo,
                "actor": str(id_usuario_actor) if id_usuario_actor else None,
            },
        )
        asignaciones_actualizadas = [
            dict(fila) for fila in resultado_update.mappings().all()
        ]

        mapa_asignacion = {
            str(fila["id_solicitud"]): fila["id"] for fila in asignaciones_actualizadas
        }

        visitas_afectadas: list[str] = []
        detalles_eliminados = 0
        for fila in futuras:
            id_detalle = fila["id_detalle"]
            id_programacion = fila["id_programacion"]
            id_solicitud = fila["id_solicitud"]

            resultado_delete = await self.db.execute(
                text(
                    """
                    DELETE FROM detalle_programacion_auditor
                    WHERE id_detalle = :id_detalle
                    RETURNING id_detalle, id_programacion, id_usuario
                    """
                ),
                {"id_detalle": id_detalle},
            )
            if resultado_delete.first():
                detalles_eliminados += 1

            if str(id_programacion) not in visitas_afectadas:
                visitas_afectadas.append(str(id_programacion))

            id_asignacion = mapa_asignacion.get(str(id_solicitud))
            await self.db.execute(
                text(
                    """
                    INSERT INTO historial_asignacion_auditor (
                        id_historial,
                        id_solicitud,
                        id_auditor,
                        accion,
                        motivo,
                        estado_anterior,
                        estado_nuevo,
                        id_usuario_accion,
                        fecha,
                        id_asignacion,
                        id_programacion
                    ) VALUES (
                        gen_random_uuid(),
                        :id_solicitud,
                        :id_auditor,
                        'RETIRO_POR_DESACTIVACION_CUENTA',
                        :motivo,
                        :estado_anterior,
                        'Cancelada',
                        :id_usuario_accion,
                        CURRENT_TIMESTAMP,
                        :id_asignacion,
                        :id_programacion
                    )
                    """
                ),
                {
                    "id_solicitud": id_solicitud,
                    "id_auditor": id_usuario,
                    "motivo": motivo,
                    "estado_anterior": str(fila.get("estado_programacion") or ""),
                    "id_usuario_accion": str(id_usuario_actor) if id_usuario_actor else None,
                    "id_asignacion": str(id_asignacion) if id_asignacion else None,
                    "id_programacion": str(id_programacion) if id_programacion else None,
                },
            )

            await self._recalcular_estado_visita(id_programacion)

        for fila in sin_programacion:
            await self.db.execute(
                text(
                    """
                    INSERT INTO historial_asignacion_auditor (
                        id_historial,
                        id_solicitud,
                        id_auditor,
                        accion,
                        motivo,
                        estado_anterior,
                        estado_nuevo,
                        id_usuario_accion,
                        fecha,
                        id_asignacion,
                        id_programacion
                    ) VALUES (
                        gen_random_uuid(),
                        :id_solicitud,
                        :id_auditor,
                        'RETIRO_POR_DESACTIVACION_CUENTA',
                        :motivo,
                        :estado_anterior,
                        'Cancelada',
                        :id_usuario_accion,
                        CURRENT_TIMESTAMP,
                        :id_asignacion,
                        NULL
                    )
                    """
                ),
                {
                    "id_solicitud": fila["id_solicitud"],
                    "id_auditor": id_usuario,
                    "motivo": motivo,
                    "estado_anterior": str(fila.get("estado_asignacion") or ""),
                    "id_usuario_accion": str(id_usuario_actor) if id_usuario_actor else None,
                    "id_asignacion": str(fila["id"]),
                },
            )

        return {
            "retiros_realizados": len(futuras) + len(sin_programacion),
            "asignaciones_canceladas": len(asignaciones_actualizadas),
            "detalles_eliminados": detalles_eliminados,
            "visitas_afectadas": visitas_afectadas,
            "en_curso": en_curso,
            "terminales": terminales,
            "sin_programacion": sin_programacion,
        }

    async def _recalcular_estado_visita(self, id_programacion: UUID) -> None:
        total_result = await self.db.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM detalle_programacion_auditor
                WHERE id_programacion = :id_programacion
                """
            ),
            {"id_programacion": id_programacion},
        )
        total = int(total_result.scalar() or 0)

        if total == 0:
            # Se conserva la visita para permitir agregar un nuevo auditor
            # mediante el flujo de reasignacion, sin cancelarla automaticamente.
            return

        pendientes_result = await self.db.execute(
            text(
                """
                SELECT COUNT(*) AS pendientes
                FROM detalle_programacion_auditor
                WHERE id_programacion = :id_programacion
                  AND COALESCE(confirmado, FALSE) = FALSE
                """
            ),
            {"id_programacion": id_programacion},
        )
        pendientes = int(pendientes_result.scalar() or 0)
        nuevo_estado = "Confirmada" if pendientes == 0 else "Programada"

        await self.db.execute(
            text(
                """
                UPDATE programacion_visita
                SET estado = :estado
                WHERE id_programacion = :id_programacion
                  AND UPPER(TRIM(COALESCE(estado, ''))) NOT IN
                      ('CANCELADA', 'CANCELADO', 'EJECUTADA', 'EJECUTADO',
                       'FINALIZADA', 'FINALIZADO')
                """
            ),
            {"estado": nuevo_estado, "id_programacion": id_programacion},
        )

    # ------------------------------------------------------------------
    # ARCHIVOS
    # ------------------------------------------------------------------
    async def ruta_documento(self, id_usuario: UUID, id_documento: UUID) -> tuple[Path, str]:
        resultado = await self.db.execute(
            text(
                """
                SELECT url_archivo, nombre_archivo
                FROM documento_auditor
                WHERE id_documento = :id_documento
                  AND id_usuario = :id_usuario
                LIMIT 1
                """
            ),
            {"id_documento": id_documento, "id_usuario": id_usuario},
        )
        fila = resultado.mappings().first()
        if fila is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Documento no encontrado para este auditor.",
            )

        ruta = _resolver_archivo(fila["url_archivo"])
        if ruta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo del documento no está disponible.",
            )
        return ruta, fila["nombre_archivo"] or ruta.name

    async def ruta_certificacion(
        self,
        id_usuario: UUID,
        id_certificacion: UUID,
    ) -> tuple[Path, str]:
        resultado = await self.db.execute(
            text(
                """
                SELECT url_archivo, nombre_archivo
                FROM certificacion_auditor
                WHERE id_certificacion = :id_certificacion
                  AND id_usuario = :id_usuario
                LIMIT 1
                """
            ),
            {"id_certificacion": id_certificacion, "id_usuario": id_usuario},
        )
        fila = resultado.mappings().first()
        if fila is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificación no encontrada para este auditor.",
            )

        ruta = _resolver_archivo(fila["url_archivo"])
        if ruta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo de la certificación no está disponible.",
            )
        return ruta, fila["nombre_archivo"] or ruta.name

    async def ruta_foto(self, id_usuario: UUID) -> tuple[Path, str]:
        resultado = await self.db.execute(
            text(
                """
                SELECT foto_url
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                  AND COALESCE(NULLIF(TRIM(foto_url), ''), '') <> ''
                ORDER BY id_perfil DESC
                LIMIT 1
                """
            ),
            {"id_usuario": id_usuario},
        )
        fila = resultado.mappings().first()
        ruta = _resolver_archivo(fila["foto_url"] if fila else None)
        if ruta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El auditor no tiene una fotografía disponible.",
            )
        return ruta, ruta.name
