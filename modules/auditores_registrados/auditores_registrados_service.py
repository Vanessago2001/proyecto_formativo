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

from core import almacen_archivos

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


async def _resolver_archivo_compartido(url: str | None, db) -> Path | None:
    """Como ``_resolver_archivo``; si el archivo se subió en otro computador, lo trae de la base."""
    ruta = _resolver_archivo(url)
    if ruta is not None or not url:
        return ruta
    clave = almacen_archivos.normalizar(url)
    if clave is None or not clave.startswith("uploads/"):
        return None
    await almacen_archivos.ruta_local(clave, db=db, disco=RAIZ_UPLOADS / clave[len("uploads/"):])
    return _resolver_archivo(url)


async def _completar_disponibles_en_base(db, faltantes: list[tuple[dict, str, str]]) -> None:
    """Marca como disponibles los archivos que no están en este disco pero sí en la base.

    ``faltantes``: (item, campo con la URL, campo "disponible"). Una sola consulta.
    """
    if not faltantes:
        return
    en_base = await almacen_archivos.tamanos([item.get(campo) for item, campo, _ in faltantes], db=db)
    for item, campo, marca in faltantes:
        clave = almacen_archivos.normalizar(item.get(campo))
        if clave in en_base:
            item[marca] = True
            item["formato"] = Path(clave).suffix.lstrip(".").upper()
            item["tamano"] = en_base[clave]


def _decorar_archivo(item: dict[str, Any], campo: str = "url_archivo") -> dict[str, Any]:
    info = _info_archivo(item.get(campo))
    item["archivo_disponible"] = info["disponible"]
    item["formato"] = info["formato"]
    item["tamano"] = info["tamano"]
    return item


def clasificar_estado_registro(
    estado_auditor: str | None, estado_postulacion: str | None
) -> dict[str, str]:
    """Estado del auditor en el registro (no el de su cuenta Activo/Inactivo).

    Devuelve ``estado_registro`` (Aprobado, Postulante, Rechazado, Cancelado o
    Sin postulación) y ``estado_registro_detalle`` con el matiz que ve el
    Coordinador en la insignia.
    """
    auditor = str(estado_auditor or "").strip().lower()
    postulacion = str(estado_postulacion or "").strip().lower()
    if auditor in ("activo", "aprobado", "aprobada"):
        return {"estado_registro": "Aprobado", "estado_registro_detalle": "Auditor aprobado"}
    if not postulacion:
        return {"estado_registro": "Sin postulación", "estado_registro_detalle": "No ha iniciado su postulación"}
    if postulacion in ("aprobado", "aprobada"):
        return {
            "estado_registro": "Aprobado",
            "estado_registro_detalle": f"Postulación aprobada; estado de auditor: {estado_auditor or 'sin dato'}",
        }
    if postulacion in ("rechazado", "rechazada"):
        return {"estado_registro": "Rechazado", "estado_registro_detalle": "Última postulación rechazada"}
    if postulacion in ("cancelado", "cancelada"):
        return {"estado_registro": "Cancelado", "estado_registro_detalle": "Última postulación cancelada"}
    if postulacion == "borrador":
        return {"estado_registro": "Postulante", "estado_registro_detalle": "Borrador sin enviar"}
    return {
        "estado_registro": "Postulante",
        "estado_registro_detalle": f"Postulación {estado_postulacion}",
    }


# ----------------------------------------------------------------------
# ACTIVAR AUDITOR (postulación aprobada, estado de auditor sin activar)
#
# Caso real (18/11/2026): la postulación vigente quedó Aprobado pero
# usuario.estado_auditor quedó en 'Postulante' (un error ya corregido degradaba
# al auditor al rechazar un documento de una postulación vieja). Sin
# estado_auditor = 'Activo' no cuenta como auditor aprobado
# (consultar_acceso_auditor / CTE_AUDITORES) y el Banco no deja re-aprobar una
# postulación final, así que el Coordinador lo activa con un motivo.
# ----------------------------------------------------------------------

# Postulación vigente: la más reciente que no está cancelada (mismo orden que
# consultar_acceso_auditor). Se usa como LEFT JOIN LATERAL con alias "vig".
SQL_POSTULACION_VIGENTE = """
    LEFT JOIN LATERAL (
        SELECT pv.id_postulacion, pv.estado
        FROM postulacion_auditor pv
        WHERE pv.id_usuario = u.id_usuario
          AND LOWER(TRIM(COALESCE(pv.estado, ''))) NOT IN ('cancelado', 'cancelada')
        ORDER BY pv.fecha_postulacion DESC NULLS LAST,
                 pv.fecha_revision DESC NULLS LAST
        LIMIT 1
    ) vig ON TRUE
"""

# Permiso delegado que necesita el Auxiliar: es "Aprobar auditor en el
# sistema" (catálogo de permisos_auxiliar); activar completa esa aprobación.
PERMISO_ACTIVAR_AUDITOR = "AUD-013"


def motivo_no_activable(
    rol: str | None,
    estado_usuario: str | None,
    estado_auditor: str | None,
    estado_postulacion_vigente: str | None,
) -> str | None:
    """None si el auditor se puede activar; si no, el motivo para el 409."""
    if str(rol or "").strip().lower() != "auditor":
        return "El usuario no tiene el rol Auditor."
    if str(estado_usuario or "").strip().lower() != "activo":
        return (
            "La cuenta del usuario no está activa. Reactive primero la cuenta "
            "y luego active al auditor."
        )
    if str(estado_postulacion_vigente or "").strip().lower() not in ("aprobado", "aprobada"):
        vigente = estado_postulacion_vigente or "sin postulación"
        return (
            "La postulación vigente del auditor no está aprobada "
            f"(estado: {vigente}). Apruébela en Banco de auditores."
        )
    if str(estado_auditor or "").strip().lower() == "activo":
        return "El auditor ya está activo."
    return None


def requiere_activacion(
    rol: str | None,
    estado_usuario: str | None,
    estado_auditor: str | None,
    estado_postulacion_vigente: str | None,
) -> bool:
    """True cuando la pantalla debe ofrecer el botón "Activar auditor"."""
    return motivo_no_activable(rol, estado_usuario, estado_auditor, estado_postulacion_vigente) is None


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
                ) AS total_certificaciones,
                ult.estado AS estado_postulacion,
                rev.id_postulacion AS id_postulacion,
                rev.estado AS estado_postulacion_revisar,
                vig.estado AS estado_postulacion_vigente
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
            -- Última postulación (incluye Borrador) para saber si es
            -- postulante, aprobado o rechazado.
            LEFT JOIN LATERAL (
                SELECT pa.estado
                FROM postulacion_auditor pa
                WHERE pa.id_usuario = u.id_usuario
                ORDER BY pa.fecha_postulacion DESC NULLS LAST,
                         pa.fecha_revision DESC NULLS LAST
                LIMIT 1
            ) ult ON TRUE
            -- Última postulación enviada (el Banco no revisa borradores):
            -- es la que abre "Revisar solicitud".
            LEFT JOIN LATERAL (
                SELECT pa.id_postulacion, pa.estado
                FROM postulacion_auditor pa
                WHERE pa.id_usuario = u.id_usuario
                  AND LOWER(TRIM(COALESCE(pa.estado, ''))) <> 'borrador'
                ORDER BY pa.fecha_postulacion DESC NULLS LAST,
                         pa.fecha_revision DESC NULLS LAST
                LIMIT 1
            ) rev ON TRUE
            -- Postulación vigente (la más reciente no cancelada): decide si
            -- se ofrece "Activar auditor".
        """ + SQL_POSTULACION_VIGENTE + """
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
        auditores = []
        for fila in resultado.mappings().all():
            auditor = dict(fila)
            auditor.update(clasificar_estado_registro(
                auditor.get("estado_auditor"), auditor.get("estado_postulacion")
            ))
            auditor["pendiente_activacion"] = requiere_activacion(
                "Auditor", auditor.get("estado"), auditor.get("estado_auditor"),
                auditor.get("estado_postulacion_vigente"),
            )
            auditores.append(auditor)
        return auditores

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
                    ) AS fecha_primera_postulacion,
                    vig.estado AS estado_postulacion_vigente
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
                """ + SQL_POSTULACION_VIGENTE + """
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
        detalle.update(clasificar_estado_registro(
            detalle.get("estado_auditor"), detalle.get("estado_postulacion")
        ))
        detalle["pendiente_activacion"] = requiere_activacion(
            detalle.get("rol"), detalle.get("estado"), detalle.get("estado_auditor"),
            detalle.get("estado_postulacion_vigente"),
        )

        detalle["documentos"] = await self._documentos(id_usuario)
        detalle["conflictos"] = await self._conflictos(id_usuario)
        detalle["certificaciones"] = await self._certificaciones(id_usuario)
        detalle["competencias"] = await self._competencias(id_usuario)
        detalle["titulos"] = await self._titulos(id_usuario)
        detalle["experiencia_laboral"] = await self._experiencia_laboral(id_usuario)
        detalle["experiencia_auditoria"] = await self._experiencia_auditoria(id_usuario)
        detalle["postulaciones"] = await self._postulaciones(id_usuario)

        # Archivos subidos en otro computador: disponibles si están en la base compartida.
        faltantes = [(detalle, "foto_url", "disponible")] if detalle.get("foto_url") and not detalle.get("disponible") else []
        faltantes += [
            (item, "url_archivo", "archivo_disponible")
            for item in (*detalle["documentos"], *detalle["certificaciones"])
            if item.get("url_archivo") and not item.get("archivo_disponible")
        ]
        await _completar_disponibles_en_base(self.db, faltantes)

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
                FOR UPDATE OF u
                """
                # PostgreSQL no permite bloquear el lado opcional de un LEFT
                # JOIN (rol): sin "OF u" la consulta fallaba y no se podía
                # inactivar ni reactivar ningún auditor.
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
        # Sin este commit el cambio (y el retiro de asignaciones) se perdia al
        # cerrar la sesion: get_db no confirma la transaccion por su cuenta.
        # Afectaba al PATCH de este modulo y a PUT /users/{id} con cuentas de
        # rol Auditor (p. ej. auditortest@gmail.com en "Control de usuarios").
        await self.db.commit()

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

    async def activar_auditor(
        self,
        id_usuario: UUID,
        motivo: str,
        id_usuario_actor: UUID,
    ) -> dict[str, Any]:
        """Pone usuario.estado_auditor = 'Activo' si la postulación vigente está aprobada.

        Reglas (409 con el motivo si no se cumplen): rol Auditor, cuenta
        'Activo', postulación vigente (la más reciente no cancelada) Aprobado
        o Aprobada y estado de auditor distinto de 'Activo'. Deja el motivo
        en historial_postulacion_auditor y notifica al auditor.
        """
        motivo = (motivo or "").strip()
        resultado = await self.db.execute(
            text(
                """
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.estado,
                    u.estado_auditor,
                    r.nombre AS rol,
                    vig.id_postulacion AS id_postulacion_vigente,
                    vig.estado AS estado_postulacion_vigente
                FROM usuario u
                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id
                """ + SQL_POSTULACION_VIGENTE + """
                WHERE u.id_usuario = :id_usuario
                LIMIT 1
                FOR UPDATE OF u
                """
            ),
            {"id_usuario": id_usuario},
        )
        auditor = resultado.mappings().first()
        if auditor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado.",
            )

        motivo_rechazo = motivo_no_activable(
            auditor["rol"],
            auditor["estado"],
            auditor["estado_auditor"],
            auditor["estado_postulacion_vigente"],
        )
        if motivo_rechazo:
            await self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=motivo_rechazo)

        estado_auditor_anterior = auditor["estado_auditor"] or "sin dato"
        actualizado = await self.db.execute(
            text(
                """
                UPDATE usuario
                SET estado_auditor = 'Activo'
                WHERE id_usuario = :id_usuario
                  AND estado_auditor IS DISTINCT FROM 'Activo'
                RETURNING id_usuario
                """
            ),
            {"id_usuario": id_usuario},
        )
        if actualizado.mappings().first() is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El auditor ya está activo.",
            )

        # Historial de la postulación vigente: la postulación sigue Aprobado;
        # lo que cambia es el estado del auditor, y eso queda en la observación
        # junto con quién (id_usuario_administrador), cuándo y el motivo.
        estado_postulacion = auditor["estado_postulacion_vigente"]
        await self.db.execute(
            text(
                """
                INSERT INTO historial_postulacion_auditor (
                    id_historial,
                    id_postulacion,
                    id_usuario_auditor,
                    id_usuario_administrador,
                    estado_anterior,
                    estado_nuevo,
                    observaciones,
                    fecha_cambio
                )
                VALUES (
                    gen_random_uuid(),
                    :id_postulacion,
                    :id_usuario_auditor,
                    :id_usuario_administrador,
                    :estado_anterior,
                    :estado_nuevo,
                    :observaciones,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "id_postulacion": auditor["id_postulacion_vigente"],
                "id_usuario_auditor": id_usuario,
                "id_usuario_administrador": id_usuario_actor,
                "estado_anterior": estado_postulacion,
                "estado_nuevo": estado_postulacion,
                "observaciones": (
                    f"Activación del auditor (estado de auditor: {estado_auditor_anterior} -> Activo). "
                    f"Motivo: {motivo}"
                ),
            },
        )

        # Notificación al auditor, como las aprobaciones del Banco
        # (notificacion.mensaje es VARCHAR(255)).
        mensaje = (
            "Su registro como auditor quedó activo: ya puede consultar y gestionar "
            f"sus visitas asignadas. Observaciones del coordinador: {motivo}"
        )
        if len(mensaje) > 255:
            mensaje = mensaje[:252].rstrip() + "..."
        await self.db.execute(
            text(
                """
                INSERT INTO notificacion (
                    id_notificacion,
                    id_usuario,
                    asunto,
                    mensaje,
                    estado,
                    fecha_envio
                )
                VALUES (
                    gen_random_uuid(),
                    :id_usuario,
                    :asunto,
                    :mensaje,
                    'Pendiente',
                    CURRENT_DATE
                )
                """
            ),
            {
                "id_usuario": id_usuario,
                "asunto": "Auditor activado",
                "mensaje": mensaje,
            },
        )
        await self.db.commit()

        return {
            "mensaje": "Auditor activado correctamente.",
            "id_usuario": auditor["id_usuario"],
            "nombre": auditor["nombre"],
            "estado_auditor_anterior": auditor["estado_auditor"],
            "estado_auditor": "Activo",
            "id_postulacion": auditor["id_postulacion_vigente"],
            "estado_postulacion": estado_postulacion,
            "estado_registro": "Aprobado",
            "notificacion_creada": True,
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

        ruta = await _resolver_archivo_compartido(fila["url_archivo"], self.db)
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

        ruta = await _resolver_archivo_compartido(fila["url_archivo"], self.db)
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
        ruta = await _resolver_archivo_compartido(fila["foto_url"] if fila else None, self.db)
        if ruta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El auditor no tiene una fotografía disponible.",
            )
        return ruta, ruta.name
