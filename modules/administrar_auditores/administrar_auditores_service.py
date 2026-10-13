from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AdministrarAuditoresService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================
    # BANCO DE AUDITORES
    # LISTAR SOLICITUDES
    # ========================================================

    async def listar_solicitudes(
        self,
        estado: str | None = None,
    ):
        """
        Lista las postulaciones de auditores para el administrador.

        Permite filtrar por estado:
            - Enviado
            - En Revisión
            - Correcciones
            - Aprobado
            - Rechazado
            - Cancelado

        Si no se envía estado, devuelve todas.
        """

        consulta = """
            SELECT
                pa.id_postulacion,
                pa.id_usuario,
                pa.estado AS estado_postulacion,
                pa.fecha_postulacion,
                pa.fecha_revision,

                u.nombre,
                u.correo,
                u.tipo_doc,
                u.num_doc,
                u.estado AS estado_usuario,
                u.estado_auditor,

                r.nombre AS rol

            FROM postulacion_auditor pa

            INNER JOIN usuario u
                ON u.id_usuario = pa.id_usuario

            LEFT JOIN rol r
                ON r.id_rol = u.rol_id

            WHERE 1 = 1
        """

        parametros = {}

        # ----------------------------------------------------
        # FILTRO POR ESTADO
        # ----------------------------------------------------

        if estado:
            consulta += """
                AND LOWER(pa.estado) = LOWER(:estado)
            """

            parametros["estado"] = estado.strip()

        # ----------------------------------------------------
        # ORDEN
        # ----------------------------------------------------

        consulta += """
            ORDER BY
                pa.fecha_postulacion DESC
        """

        result = await self.db.execute(
            text(consulta),
            parametros,
        )

        solicitudes = result.mappings().all()

        # ----------------------------------------------------
        # RESPUESTA
        # ----------------------------------------------------

        return [
            {
                "id_postulacion": solicitud["id_postulacion"],
                "id_usuario": solicitud["id_usuario"],
                "nombre": solicitud["nombre"],
                "correo": solicitud["correo"],
                "tipo_doc": solicitud["tipo_doc"],
                "num_doc": solicitud["num_doc"],
                "estado_usuario": solicitud["estado_usuario"],
                "estado_auditor": solicitud["estado_auditor"],
                "rol": solicitud["rol"],
                "estado_postulacion": solicitud["estado_postulacion"],
                "fecha_postulacion": solicitud["fecha_postulacion"],
                "fecha_revision": solicitud["fecha_revision"],
            }
            for solicitud in solicitudes
        ]

    # ========================================================
    # DETALLE DE UNA SOLICITUD
    # ========================================================

    async def obtener_solicitud(
        self,
        id_postulacion: UUID,
    ):
        """
        Obtiene toda la información necesaria para que
        el administrador revise una postulación.
        """

        # ----------------------------------------------------
        # DATOS DE LA POSTULACIÓN
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    pa.id_postulacion,
                    pa.id_usuario,
                    pa.estado AS estado_postulacion,
                    pa.observaciones_tecnicas,
                    pa.fecha_postulacion,
                    pa.fecha_revision,

                    u.nombre,
                    u.correo,
                    u.tipo_doc,
                    u.num_doc,
                    u.estado AS estado_usuario,
                    u.estado_auditor,

                    r.nombre AS rol

                FROM postulacion_auditor pa

                INNER JOIN usuario u
                    ON u.id_usuario = pa.id_usuario

                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id

                WHERE pa.id_postulacion = :id_postulacion

                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        solicitud = result.mappings().first()

        if not solicitud:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación.",
            )

        # ----------------------------------------------------
        # PERFIL
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    ciudad_residencia,
                    departamento_residencia,
                    modalidad_preferida,
                    foto_url,
                    resumen_profesional,
                    calificacion_promedio
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": solicitud["id_usuario"],
            },
        )

        perfil = result.mappings().first()

        # ----------------------------------------------------
        # COMPETENCIAS
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    id_competencia,
                    id_norma,
                    tipo_competencia,
                    codigo_sector_iaf,
                    titulo_institucion,
                    descripcion,
                    fecha_inicio,
                    fecha_fin,
                    es_vigente,
                    estado_validacion
                FROM competencia_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_inicio DESC
            """),
            {
                "id_usuario": solicitud["id_usuario"],
            },
        )

        competencias = result.mappings().all()

        # ----------------------------------------------------
        # CONFLICTOS DE INTERÉS
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    id_conflicto,
                    id_empresa,
                    tipo_conflicto,
                    descripcion,
                    bloquea_asignacion,
                    fecha_declaracion,
                    estado
                FROM conflicto_interes
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_declaracion DESC
            """),
            {
                "id_usuario": solicitud["id_usuario"],
            },
        )

        conflictos = result.mappings().all()

        # ----------------------------------------------------
        # DOCUMENTOS
        #
        # IMPORTANTE:
        # Estos sí están relacionados directamente con
        # id_postulacion.
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    id_documento,
                    id_postulacion,
                    id_usuario,
                    nombre_archivo,
                    tipo_documento,
                    url_archivo,
                    fecha_subida,
                    estado_revision
                FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
                ORDER BY fecha_subida DESC
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        documentos = result.mappings().all()

        # ----------------------------------------------------
        # RESPUESTA
        # ----------------------------------------------------

        return {
            "id_postulacion": solicitud["id_postulacion"],
            "id_usuario": solicitud["id_usuario"],

            "nombre": solicitud["nombre"],
            "correo": solicitud["correo"],
            "tipo_doc": solicitud["tipo_doc"],
            "num_doc": solicitud["num_doc"],

            "estado_usuario": solicitud["estado_usuario"],
            "estado_auditor": solicitud["estado_auditor"],
            "rol": solicitud["rol"],

            "estado_postulacion": solicitud["estado_postulacion"],
            "observaciones_tecnicas": (
                solicitud["observaciones_tecnicas"]
                or ""
            ),
            "fecha_postulacion": solicitud["fecha_postulacion"],
            "fecha_revision": solicitud["fecha_revision"],

            "perfil": (
                dict(perfil)
                if perfil
                else None
            ),

            "competencias": [
                dict(item)
                for item in competencias
            ],

            "conflictos": [
                dict(item)
                for item in conflictos
            ],

            "documentos": [
                dict(item)
                for item in documentos
            ],
        }


    # ========================================================
    # CAMBIAR ESTADO DE UNA POSTULACIÓN
    # ========================================================

    async def cambiar_estado(
        self,
        id_postulacion: UUID,
        nuevo_estado: str,
        observaciones: str | None,
        id_usuario_actor: UUID,
    ):
        """
        Cambia el estado de una postulación de auditor y registra
        la acción realizada por el administrador.

        Tablas utilizadas:
            - postulacion_auditor
            - historial_postulacion_auditor
            - usuario

        IMPORTANTE:
        No se utiliza historial_estado porque esa tabla pertenece
        al flujo de solicitudes y su FK apunta a solicitud.id_solicitud.
        Para el Banco de Auditores el historial correcto es
        historial_postulacion_auditor.
        """

        # =====================================================
        # 1. VALIDAR Y BLOQUEAR LA POSTULACIÓN
        # =====================================================

        resultado = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_revision
                FROM postulacion_auditor
                WHERE id_postulacion = :id_postulacion
                FOR UPDATE
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        postulacion = resultado.mappings().first()

        if postulacion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La postulación no existe.",
            )

        estado_anterior = postulacion["estado"]
        id_usuario_auditor = postulacion["id_usuario"]

        # =====================================================
        # 2. VALIDAR ADMINISTRADOR
        # =====================================================
        # historial_postulacion_auditor.id_usuario_administrador
        # tiene FK hacia usuario.id_usuario.

        resultado = await self.db.execute(
            text("""
                SELECT id_usuario
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario_actor,
            },
        )

        if resultado.first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El usuario administrador indicado no existe.",
            )

        # =====================================================
        # 3. VALIDAR AUDITOR
        # =====================================================
        # historial_postulacion_auditor.id_usuario_auditor
        # también tiene FK hacia usuario.id_usuario.

        resultado = await self.db.execute(
            text("""
                SELECT id_usuario
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario_auditor,
            },
        )

        if resultado.first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El usuario asociado a la postulación no existe.",
            )

        # =====================================================
        # 4. NORMALIZAR OBSERVACIONES
        # =====================================================

        observaciones_limpias = (
            observaciones.strip()
            if observaciones is not None
            else None
        )

        # =====================================================
        # 5. ACTUALIZAR POSTULACIÓN
        # =====================================================

        await self.db.execute(
            text("""
                UPDATE postulacion_auditor
                SET
                    estado = :nuevo_estado,
                    fecha_revision = CURRENT_TIMESTAMP
                WHERE id_postulacion = :id_postulacion
            """),
            {
                "nuevo_estado": nuevo_estado,
                "id_postulacion": id_postulacion,
            },
        )

        # =====================================================
        # 6. REGISTRAR HISTORIAL
        # =====================================================
        # Aquí queda guardado EXACTAMENTE qué administrador
        # realizó el cambio.

        await self.db.execute(
            text("""
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
            """),
            {
                "id_postulacion": id_postulacion,
                "id_usuario_auditor": id_usuario_auditor,
                "id_usuario_administrador": id_usuario_actor,
                "estado_anterior": estado_anterior,
                "estado_nuevo": nuevo_estado,
                "observaciones": observaciones_limpias,
            },
        )

        # =====================================================
        # 7. CONFIRMAR TODO EN UNA SOLA TRANSACCIÓN
        # =====================================================

        try:
            await self.db.commit()

        except Exception:
            await self.db.rollback()
            raise

        # =====================================================
        # 8. DEVOLVER RESULTADO
        # =====================================================

        resultado = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_revision
                FROM postulacion_auditor
                WHERE id_postulacion = :id_postulacion
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        actualizada = resultado.mappings().first()

        return {
            "ok": True,
            "mensaje": "La postulación fue actualizada correctamente.",
            "id_postulacion": str(actualizada["id_postulacion"]),
            "id_usuario_auditor": str(actualizada["id_usuario"]),
            "id_usuario_administrador": str(id_usuario_actor),
            "estado_anterior": estado_anterior,
            "estado_nuevo": actualizada["estado"],
            "observaciones": observaciones_limpias,
            "fecha_revision": (
                actualizada["fecha_revision"].isoformat()
                if actualizada["fecha_revision"]
                else None
            ),
        }


    # obtener_historial_postulacion_auditor
    
    async def obtener_historial(
        self,
        id_postulacion: UUID,
    ):
        result = await self.db.execute(
            text(
                """
                SELECT
                    h.id_historial,
                    h.id_postulacion,

                    h.id_usuario_auditor,
                    auditor.nombre AS nombre_auditor,
                    auditor.correo AS correo_auditor,

                    h.id_usuario_administrador,
                    administrador.nombre AS nombre_administrador,
                    administrador.correo AS correo_administrador,

                    h.estado_anterior,
                    h.estado_nuevo,
                    h.observaciones,
                    h.fecha_cambio

                FROM historial_postulacion_auditor h

                INNER JOIN usuario auditor
                    ON auditor.id_usuario = h.id_usuario_auditor

                INNER JOIN usuario administrador
                    ON administrador.id_usuario = h.id_usuario_administrador

                WHERE h.id_postulacion = :id_postulacion

                ORDER BY h.fecha_cambio DESC
                """
            ),
            {
                "id_postulacion": id_postulacion,
            },
        )

        historial = result.mappings().all()

        return [
            {
                "id_historial": item["id_historial"],
                "id_postulacion": item["id_postulacion"],

                "id_usuario_auditor": item["id_usuario_auditor"],
                "nombre_auditor": item["nombre_auditor"],
                "correo_auditor": item["correo_auditor"],

                "id_usuario_administrador": (
                    item["id_usuario_administrador"]
                ),
                "nombre_administrador": (
                    item["nombre_administrador"]
                ),
                "correo_administrador": (
                    item["correo_administrador"]
                ),

                "estado_anterior": item["estado_anterior"],
                "estado_nuevo": item["estado_nuevo"],
                "observaciones": item["observaciones"],
                "fecha_cambio": item["fecha_cambio"],
            }
            for item in historial
        ]