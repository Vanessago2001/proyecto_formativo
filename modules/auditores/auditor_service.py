from datetime import datetime
from uuid import UUID, uuid4

import os
import shutil
from pathlib import Path
from fastapi import HTTPException, status, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from core.security import hash_password

from modules.auditores.auditor_schema import (
    IniciarRegistroAuditor,
    PerfilAuditorCrear,
    CompetenciaAuditorCrear,
    ConflictoInteresCrear,
    TituloAcademicoCrear,
    ExperienciaLaboralCrear,
    ExperienciaAuditoriaCrear,
)

from reportlab.lib import colors
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

class AuditorService:
    


    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================
    # DOCUMENTOS DE SOPORTE
    # ========================================================

    DIRECTORIO_DOCUMENTOS = Path("uploads/auditores")
    DIRECTORIO_FOTOS_PERFIL = Path("uploads/auditores/perfiles")

    EXTENSIONES_PERMITIDAS = {
        ".pdf",
        ".doc",
        ".docx",
        ".jpg",
        ".jpeg",
        ".png",
    }

    EXTENSIONES_FOTO_PERFIL = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
    #  obtener_documentos, adjuntar_documento, reemplazar_documento, eliminar_documento

    # async def _obtener_o_crear_postulacion_borrador(
    #     self,
    #     id_usuario: UUID,
    # ):
    #     """
    #     Obtiene el Borrador actual.

    #     Si la última postulación fue Cancelado o Rechazado,
    #     crea una nueva postulación Borrador y limpia los datos
    #     del formulario anterior.

    #     Si existe una postulación Enviado, En Revisión o Aprobado,
    #     no permite crear otra.
    #     """

    #     result = await self.db.execute(
    #         text("""
    #             SELECT
    #                 id_postulacion,
    #                 id_usuario,
    #                 estado
    #             FROM postulacion_auditor
    #             WHERE id_usuario = :id_usuario
    #             ORDER BY fecha_postulacion DESC
    #             LIMIT 1
    #         """),
    #         {
    #             "id_usuario": id_usuario,
    #         },
    #     )

    #     ultima = result.mappings().first()

    #     # --------------------------------------------------------
    #     # YA EXISTE UN BORRADOR
    #     # --------------------------------------------------------
    #     # No borrar nada.
    #     # El usuario continúa trabajando sobre el mismo borrador.
    #     # --------------------------------------------------------

    #     if ultima and ultima["estado"] == "Borrador":
    #         return ultima

    #     # --------------------------------------------------------
    #     # NO PERMITIR OTRA POSTULACIÓN SI HAY UNA ACTIVA
    #     # --------------------------------------------------------

    #     if ultima and ultima["estado"] in (
    #         "Enviado",
    #         "En Revisión",
    #         "Aprobado",
    #     ):
    #         raise HTTPException(
    #             status_code=status.HTTP_409_CONFLICT,
    #             detail=(
    #                 "El auditor ya tiene una postulación activa "
    #                 f"en estado '{ultima['estado']}'."
    #             ),
    #         )

    #     # --------------------------------------------------------
    #     # CANCELADO / RECHAZADO
    #     # --------------------------------------------------------
    #     # Como las tablas de perfil, competencia y conflicto
    #     # actualmente están relacionadas únicamente por id_usuario,
    #     # debemos eliminar los datos del formulario anterior ANTES
    #     # de crear el nuevo borrador.
    #     #
    #     # Los documentos NO se eliminan porque pertenecen a su
    #     # respectiva postulación mediante id_postulacion.
    #     # --------------------------------------------------------

    #     if ultima and ultima["estado"] in (
    #         "Cancelado",
    #         "Rechazado",
    #     ):
    #         await self.db.execute(
    #             text("""
    #                 DELETE FROM conflicto_interes
    #                 WHERE id_usuario = :id_usuario
    #             """),
    #             {
    #                 "id_usuario": id_usuario,
    #             },
    #         )

    #         await self.db.execute(
    #             text("""
    #                 DELETE FROM competencia_auditor
    #                 WHERE id_usuario = :id_usuario
    #             """),
    #             {
    #                 "id_usuario": id_usuario,
    #             },
    #         )

    #         await self.db.execute(
    #             text("""
    #                 DELETE FROM perfil_auditor
    #                 WHERE id_usuario = :id_usuario
    #             """),
    #             {
    #                 "id_usuario": id_usuario,
    #             },
    #         )

    #     # --------------------------------------------------------
    #     # CREAR NUEVO BORRADOR
    #     # --------------------------------------------------------

    #     result = await self.db.execute(
    #         text("""
    #             INSERT INTO postulacion_auditor (
    #                 id_usuario,
    #                 estado,
    #                 observaciones_tecnicas,
    #                 fecha_postulacion,
    #                 fecha_revision
    #             )
    #             VALUES (
    #                 :id_usuario,
    #                 'Borrador',
    #                 '',
    #                 CURRENT_TIMESTAMP,
    #                 NULL
    #             )
    #             RETURNING
    #                 id_postulacion,
    #                 id_usuario,
    #                 estado
    #         """),
    #         {
    #             "id_usuario": id_usuario,
    #         },
    #     )

    #     postulacion = result.mappings().first()

    #     if not postulacion:
    #         await self.db.rollback()

    #         raise HTTPException(
    #             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #             detail="No fue posible crear el borrador de la postulación.",
    #         )

    #     await self.db.commit()

    #     return postulacion

    async def _obtener_o_crear_postulacion_borrador(
        self,
        id_usuario: UUID,
    ):
        # ========================================================
        # BUSCAR ÚLTIMA POSTULACIÓN
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_postulacion,
                    fecha_revision,
                    observaciones_tecnicas
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        ultima = result.mappings().first()

        # ========================================================
        # NO EXISTE
        # ========================================================

        if not ultima:

            result = await self.db.execute(
                text("""
                    INSERT INTO postulacion_auditor (
                        id_usuario,
                        estado,
                        observaciones_tecnicas,
                        fecha_postulacion,
                        fecha_revision
                    )
                    VALUES (
                        :id_usuario,
                        'Borrador',
                        '',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    RETURNING
                        id_postulacion,
                        id_usuario,
                        estado,
                        fecha_postulacion,
                        fecha_revision,
                        observaciones_tecnicas
                """),
                {
                    "id_usuario": id_usuario,
                },
            )

            postulacion = result.mappings().first()

            if not postulacion:
                await self.db.rollback()

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No fue posible crear el borrador.",
                )

            await self.db.commit()

            return postulacion

        # ========================================================
        # BORRADOR
        # ========================================================

        if ultima["estado"] == "Borrador":

            return ultima

        # ========================================================
        # CORRECCIONES
        #
        # REUTILIZAR LA MISMA POSTULACIÓN
        #
        # NO INSERTAR NADA
        # ========================================================

        if ultima["estado"] == "Correcciones":

            return ultima

        # ========================================================
        # POSTULACIÓN ACTIVA
        # ========================================================

        if ultima["estado"] in (
            "Enviado",
            "En Revisión",
            "Aprobado",
        ):

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El auditor ya tiene una postulación activa "
                    f"en estado '{ultima['estado']}'."
                ),
            )

        # ========================================================
        # RECHAZADO / CANCELADO
        #
        # AQUÍ SÍ SE PUEDE CREAR UNA NUEVA POSTULACIÓN
        # ========================================================

        if ultima["estado"] in (
            "Cancelado",
            "Rechazado",
        ):

            result = await self.db.execute(
                text("""
                    INSERT INTO postulacion_auditor (
                        id_usuario,
                        estado,
                        observaciones_tecnicas,
                        fecha_postulacion,
                        fecha_revision
                    )
                    VALUES (
                        :id_usuario,
                        'Borrador',
                        '',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    RETURNING
                        id_postulacion,
                        id_usuario,
                        estado,
                        fecha_postulacion,
                        fecha_revision,
                        observaciones_tecnicas
                """),
                {
                    "id_usuario": id_usuario,
                },
            )

            postulacion = result.mappings().first()

            if not postulacion:
                await self.db.rollback()

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No fue posible crear el nuevo borrador.",
                )

            await self.db.commit()

            return postulacion

        # ========================================================
        # ESTADO NO CONTEMPLADO
        # ========================================================

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El estado '{ultima['estado']}' "
                "no permite editar la postulación."
            ),
        )
    
  
  
    # primer obtener_borrador
        
    async def obtener_borrador(
        self,
        id_usuario: UUID,
    ):
        # ========================================================
        # USUARIO
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_usuario,
                    nombre,
                    tipo_doc,
                    num_doc,
                    correo,
                    estado,
                    estado_auditor
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario auditor.",
            )

        # ========================================================
        # BUSCAR LA ÚLTIMA POSTULACIÓN
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_postulacion,
                    fecha_revision,
                    observaciones_tecnicas
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        ultima = result.mappings().first()

        # ========================================================
        # DETERMINAR POSTULACIÓN ACTUAL
        # ========================================================

        if ultima:

            estado = ultima["estado"]

            # ----------------------------------------------------
            # BORRADOR
            # ----------------------------------------------------
            #
            # Se reutiliza.
            # ----------------------------------------------------

            if estado == "Borrador":

                postulacion = ultima

            # ----------------------------------------------------
            # CORRECCIONES
            # ----------------------------------------------------
            #
            # MUY IMPORTANTE:
            #
            # Correcciones NO crea otro borrador.
            #
            # Se reutiliza exactamente la misma postulación.
            # ----------------------------------------------------

            elif estado == "Correcciones":

                postulacion = ultima

            # ----------------------------------------------------
            # POSTULACIONES ACTIVAS NO EDITABLES
            # ----------------------------------------------------

            elif estado in (
                "Enviado",
                "En Revisión",
                "Aprobado",
            ):

                # La consulta del registro es de solo lectura.
                # Permitimos cargar la información para que el auditor
                # pueda consultar sus documentos y foto, pero los
                # endpoints de modificación siguen protegidos por
                # _verificar_usuario_borrador().
                postulacion = ultima

            # ----------------------------------------------------
            # RECHAZADO / CANCELADO
            # ----------------------------------------------------
            #
            # En estos casos sí se permite iniciar una NUEVA
            # postulación.
            # ----------------------------------------------------

            elif estado in (
                "Cancelado",
                "Rechazado",
            ):
                # Un rechazo/cancelación es histórico y NO se convierte
                # automáticamente en borrador. La nueva postulación se
                # crea únicamente mediante crear_nueva_postulacion().
                postulacion = ultima

            else:

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"El estado '{estado}' no permite "
                        "editar la postulación."
                    ),
                )

        # ========================================================
        # NO EXISTE NINGUNA POSTULACIÓN
        # ========================================================

        else:

            result = await self.db.execute(
                text("""
                    INSERT INTO postulacion_auditor (
                        id_usuario,
                        estado,
                        observaciones_tecnicas,
                        fecha_postulacion,
                        fecha_revision
                    )
                    VALUES (
                        :id_usuario,
                        'Borrador',
                        '',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    RETURNING
                        id_postulacion,
                        id_usuario,
                        estado,
                        fecha_postulacion,
                        fecha_revision,
                        observaciones_tecnicas
            """),
                {
                    "id_usuario": id_usuario,
                },
            )

            postulacion = result.mappings().first()

            if not postulacion:
                await self.db.rollback()

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No fue posible crear el borrador.",
                )

            await self.db.commit()

        # ========================================================
        # PERFIL
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    ciudad_residencia,
                    departamento_residencia,
                    modalidad_preferida,
                    foto_url,
                    resumen_profesional
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        perfil = result.mappings().first()

        # ========================================================
        # COMPETENCIAS
        # ========================================================

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
                    es_vigente
                FROM competencia_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_inicio DESC
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        competencias = result.mappings().all()

        # ========================================================
        # CONFLICTOS
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_conflicto,
                    id_empresa,
                    tipo_conflicto,
                    descripcion,
                    bloquea_asignacion
                FROM conflicto_interes
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_declaracion DESC
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        conflictos = result.mappings().all()

        # ========================================================
        # DOCUMENTOS
        #
        # IMPORTANTE:
        # Buscar por id_postulacion.
        #
        # No buscar solamente por estado = Borrador porque
        # ahora Correcciones también es editable.
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    d.id_documento,
                    d.id_postulacion,
                    d.nombre_archivo,
                    d.tipo_documento,
                    d.url_archivo,
                    d.fecha_subida,
                    d.estado_revision,
                    d.categoria_documento,
                    d.id_titulo,
                    d.id_experiencia_laboral,
                    d.id_experiencia_auditoria,
                    d.observacion_revision,
                    d.revisado_por,
                    d.fecha_revision
                FROM documento_auditor d
                WHERE d.id_postulacion = :id_postulacion
                ORDER BY d.fecha_subida DESC
            """),
            {
                "id_postulacion": postulacion["id_postulacion"],
            },
        )

        documentos = result.mappings().all()

        # ========================================================
        # RESPUESTA
        # ========================================================

        return {
            "id_usuario": usuario["id_usuario"],
            "id_postulacion": postulacion["id_postulacion"],

            "estado": postulacion["estado"],

            "estado_auditor": usuario["estado_auditor"],

            "nombre": usuario["nombre"],
            "tipo_doc": usuario["tipo_doc"],
            "num_doc": usuario["num_doc"],
            "correo": usuario["correo"],

            "observaciones_tecnicas": (
                postulacion["observaciones_tecnicas"]
                or ""
            ),

            "fecha_postulacion": postulacion["fecha_postulacion"],
            "fecha_revision": postulacion["fecha_revision"],

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

            "documento_url_soporte": None,
        }

        
    # obtener_documentos, adjuntar_documento, reemplazar_documento, eliminar_documento

    async def obtener_documentos(
        self,
        id_usuario: UUID,
    ):
        result = await self.db.execute(
            text("""
                SELECT
                    d.id_documento,
                    d.id_postulacion,
                    d.nombre_archivo,
                    d.tipo_documento,
                    d.url_archivo,
                    d.fecha_subida,
                    d.estado_revision,
                    d.categoria_documento,
                    d.id_titulo,
                    d.id_experiencia_laboral,
                    d.id_experiencia_auditoria,
                    d.observacion_revision,
                    d.revisado_por,
                    d.fecha_revision
                FROM documento_auditor d
                INNER JOIN postulacion_auditor p
                    ON p.id_postulacion = d.id_postulacion
                WHERE p.id_usuario = :id_usuario
                AND p.estado IN ('Borrador', 'Correcciones', 'Enviado', 'En Revisión', 'Aprobado')
                ORDER BY d.fecha_subida DESC
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        return [
            dict(documento)
            for documento in result.mappings().all()
        ]

    # ajustar_documento, reemplazar_documento y eliminar_documento
    async def adjuntar_documento(
        self,
        id_usuario: UUID,
        tipo_documento: str,
        archivo: UploadFile,
        categoria_documento: str = "Soporte",
        id_titulo: UUID | None = None,
        id_experiencia_laboral: UUID | None = None,
        id_experiencia_auditoria: UUID | None = None,
    ):
        await self._verificar_usuario_borrador(id_usuario)

        tipo_documento = tipo_documento.strip()

        tipos_permitidos = {
            "Hoja de Vida",
            "Título",
            "Certificado ISO",
            "Experiencia laboral",
            "Experiencia en auditoría",
            "Soporte",
            "Foto Profesional",
            "Soporte experiencia laboral",
            "Soporte experiencia auditoría",
            "Otro",
        }

        if tipo_documento not in tipos_permitidos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El tipo de documento no es válido.",
            )

        if not archivo.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe seleccionar un archivo.",
            )

        extension = Path(archivo.filename).suffix.lower()

        if extension not in self.EXTENSIONES_PERMITIDAS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Tipo de archivo no permitido. "
                    "Solo se permiten PDF, DOC, DOCX, JPG, JPEG y PNG."
                ),
            )

        # Crear/reutilizar Borrador
        postulacion = await self._obtener_o_crear_postulacion_borrador(
            id_usuario
        )

        id_postulacion = postulacion["id_postulacion"]

        # Los documentos ya aprobados no pueden reemplazarse desde el portal.
        result = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
                  AND tipo_documento = :tipo_documento
                  AND estado_revision = 'Aprobado'
            """),
            {"id_postulacion": id_postulacion, "tipo_documento": tipo_documento},
        )
        if result.scalar() and result.scalar() > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe una versión aprobada de este documento.",
            )

        # Si el auditor vuelve a adjuntar el mismo tipo, se reemplazan solo
        # los archivos pendientes/rechazados mas antiguos del mismo intento.
        await self.db.execute(
            text("""
                DELETE FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
                  AND tipo_documento = :tipo_documento
                  AND estado_revision = 'Pendiente'
            """),
            {"id_postulacion": id_postulacion, "tipo_documento": tipo_documento},
        )

        self.DIRECTORIO_DOCUMENTOS.mkdir(
            parents=True,
            exist_ok=True,
        )

        nombre_fisico = (
            f"{id_postulacion}_{uuid4()}{extension}"
        )

        ruta_archivo = (
            self.DIRECTORIO_DOCUMENTOS / nombre_fisico
        )

        try:
            with ruta_archivo.open("wb") as buffer:
                shutil.copyfileobj(
                    archivo.file,
                    buffer,
                )
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible guardar el archivo.",
            ) from error

        url_archivo = (
            f"/uploads/auditores/{nombre_fisico}"
        )

        try:
            result = await self.db.execute(
                text("""
                    INSERT INTO documento_auditor (
                        id_usuario,
                        id_postulacion,
                        nombre_archivo,
                        tipo_documento,
                        url_archivo,
                        fecha_subida,
                        estado_revision,
                        categoria_documento,
                        id_titulo,
                        id_experiencia_laboral,
                        id_experiencia_auditoria
                    )
                    VALUES (
                        :id_usuario,
                        :id_postulacion,
                        :nombre_archivo,
                        :tipo_documento,
                        :url_archivo,
                        CURRENT_TIMESTAMP,
                        'Pendiente',
                        :categoria_documento,
                        :id_titulo,
                        :id_experiencia_laboral,
                        :id_experiencia_auditoria
                    )
                    RETURNING
                        id_documento,
                        id_postulacion,
                        nombre_archivo,
                        tipo_documento,
                        url_archivo,
                        fecha_subida,
                        estado_revision
                """),
                {
                    "id_usuario": id_usuario,
                    "id_postulacion": id_postulacion,
                    "nombre_archivo": archivo.filename,
                    "tipo_documento": tipo_documento,
                    "url_archivo": url_archivo,
                    "categoria_documento": categoria_documento.strip() or "Soporte",
                    "id_titulo": id_titulo,
                    "id_experiencia_laboral": id_experiencia_laboral,
                    "id_experiencia_auditoria": id_experiencia_auditoria,
                },
            )

            documento = result.mappings().first()

            await self.db.commit()

        except Exception as error:
            await self.db.rollback()

            if ruta_archivo.exists():
                try:
                    ruta_archivo.unlink()
                except OSError:
                    pass

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible registrar el documento.",
            ) from error

        return {
            "mensaje": "Documento adjuntado correctamente.",
            "id_postulacion": id_postulacion,
            "documento": dict(documento),
        }

    # replace_documento, eliminar_documento
    async def reemplazar_documento(
        self,
        id_usuario: UUID,
        id_documento: UUID,
        archivo: UploadFile,
    ):
        """
        Reemplaza solamente el archivo seleccionado.
        Los demás documentos permanecen intactos.
        """

        await self._verificar_usuario_borrador(id_usuario)

        if not archivo.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe seleccionar un archivo.",
            )

        extension = Path(
            archivo.filename
        ).suffix.lower()

        if extension not in self.EXTENSIONES_PERMITIDAS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Tipo de archivo no permitido. "
                    "Solo se permiten PDF, DOC, DOCX, JPG, JPEG y PNG."
                ),
            )

        # ----------------------------------------------------
        # Buscar documento del Borrador
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    d.id_documento,
                    d.id_postulacion,
                    d.nombre_archivo,
                    d.tipo_documento,
                    d.url_archivo
                FROM documento_auditor d
                INNER JOIN postulacion_auditor p
                    ON p.id_postulacion = d.id_postulacion
                WHERE d.id_documento = :id_documento
                  AND d.id_usuario = :id_usuario
                  AND p.estado IN ('Borrador', 'Correcciones')
                  AND (p.estado = 'Borrador' OR d.estado_revision = 'Rechazado')
                LIMIT 1
            """),
            {
                "id_documento": id_documento,
                "id_usuario": id_usuario,
            },
        )

        documento_actual = result.mappings().first()

        if not documento_actual:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "El documento no existe, "
                    "no pertenece al auditor "
                    "o la postulación ya fue enviada."
                ),
            )

        # ----------------------------------------------------
        # Guardar nuevo archivo
        # ----------------------------------------------------

        self.DIRECTORIO_DOCUMENTOS.mkdir(
            parents=True,
            exist_ok=True,
        )

        nombre_fisico = (
            f"{documento_actual['id_postulacion']}_"
            f"{uuid4()}"
            f"{extension}"
        )

        nueva_ruta = (
            self.DIRECTORIO_DOCUMENTOS /
            nombre_fisico
        )

        with nueva_ruta.open("wb") as buffer:
            shutil.copyfileobj(
                archivo.file,
                buffer,
            )

        nueva_url = (
            f"/uploads/auditores/{nombre_fisico}"
        )

        try:

            result = await self.db.execute(
                text("""
                    UPDATE documento_auditor
                    SET
                        nombre_archivo = :nombre_archivo,
                        url_archivo = :url_archivo,
                        fecha_subida = CURRENT_TIMESTAMP,
                        estado_revision = 'Pendiente',
                        observacion_revision = '',
                        revisado_por = NULL,
                        fecha_revision = NULL
                    WHERE id_documento = :id_documento
                      AND id_usuario = :id_usuario
                    RETURNING
                        id_documento,
                        id_postulacion,
                        nombre_archivo,
                        tipo_documento,
                        url_archivo,
                        fecha_subida,
                        estado_revision
                """),
                {
                    "id_documento": id_documento,
                    "id_usuario": id_usuario,
                    "nombre_archivo": archivo.filename,
                    "url_archivo": nueva_url,
                },
            )

            documento = result.mappings().first()

            await self.db.commit()

        except Exception as error:

            await self.db.rollback()

            if nueva_ruta.exists():
                try:
                    nueva_ruta.unlink()
                except OSError:
                    pass

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible reemplazar el documento.",
            ) from error

        # ----------------------------------------------------
        # Eliminar archivo anterior
        # ----------------------------------------------------

        url_anterior = documento_actual["url_archivo"]

        if url_anterior:
            ruta_anterior = Path(
                url_anterior.lstrip("/")
            )

            if ruta_anterior.exists():
                try:
                    ruta_anterior.unlink()
                except OSError:
                    pass

        return {
            "mensaje": "Documento reemplazado correctamente.",
            "documento": dict(documento),
        }


    async def eliminar_documento(
        self,
        id_usuario: UUID,
        id_documento: UUID,
    ):
        """
        Elimina únicamente el documento seleccionado.
        """

        await self._verificar_usuario_borrador(id_usuario)

        result = await self.db.execute(
            text("""
                SELECT
                    d.id_documento,
                    d.url_archivo
                FROM documento_auditor d
                INNER JOIN postulacion_auditor p
                    ON p.id_postulacion = d.id_postulacion
                WHERE d.id_documento = :id_documento
                  AND d.id_usuario = :id_usuario
                  AND p.estado IN ('Borrador', 'Correcciones')
                  AND (p.estado = 'Borrador' OR d.estado_revision = 'Rechazado')
                LIMIT 1
            """),
            {
                "id_documento": id_documento,
                "id_usuario": id_usuario,
            },
        )

        documento = result.mappings().first()

        if not documento:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "El documento no existe, "
                    "no pertenece al auditor "
                    "o la postulación ya fue enviada."
                ),
            )

        await self.db.execute(
            text("""
                DELETE FROM documento_auditor
                WHERE id_documento = :id_documento
                  AND id_usuario = :id_usuario
            """),
            {
                "id_documento": id_documento,
                "id_usuario": id_usuario,
            },
        )

        await self.db.commit()

        # ----------------------------------------------------
        # Eliminar archivo físico
        # ----------------------------------------------------

        url_archivo = documento["url_archivo"]

        if url_archivo:

            ruta = Path(
                url_archivo.lstrip("/")
            )

            if ruta.exists():
                try:
                    ruta.unlink()
                except OSError:
                    pass

        return {
            "id_documento": id_documento,
            "mensaje": "Documento eliminado correctamente.",
        }
    # ========================================================
    # UTILIDAD
    # ========================================================

    async def _verificar_usuario_activo(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT id_usuario, estado
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        usuario = result.mappings().first()
        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario auditor.",
            )
        if str(usuario["estado"] or "").strip().upper() != "ACTIVO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El usuario no está activo.",
            )
        return usuario

    async def _verificar_usuario_borrador(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT
                    id_usuario,
                    nombre,
                    correo,
                    estado,
                    estado_auditor,
                    tipo_doc,
                    num_doc
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario auditor.",
            )

        if usuario["estado_auditor"] not in (
            "BORRADOR",
            "Postulante",
            "Pendiente",
            "PENDIENTE",
            "Enviado",
            "Enviada",
            "Enviado por Corrección",
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El registro ya no se encuentra disponible "
                    "para edición."
                ),
            )

        return usuario

    async def _obtener_postulacion_activa(self, id_usuario: UUID):
        result = await self.db.execute(
            text('''\n                SELECT id_postulacion\n                FROM postulacion_auditor\n                WHERE id_usuario = :id_usuario\n                  AND estado IN ('Borrador', 'Correcciones', 'Enviado')\n                ORDER BY fecha_postulacion DESC\n                LIMIT 1\n            '''),
            {"id_usuario": id_usuario},
        )
        return result.scalar()

        return usuario

    # ========================================================
    # INICIAR REGISTRO
    # ========================================================

    async def iniciar_registro(
        self,
        data: IniciarRegistroAuditor,
    ):

        nombre = data.nombre.strip()
        tipo_doc = data.tipo_doc.strip()
        num_doc = data.num_doc.strip()
        correo = data.correo.strip().lower()

        # ----------------------------------------------------
        # Verificar correo
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT id_usuario
                FROM usuario
                WHERE LOWER(correo) = LOWER(:correo)
                LIMIT 1
            """),
            {
                "correo": correo,
            },
        )

        if result.mappings().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El correo electrónico ya está registrado.",
            )

        # ----------------------------------------------------
        # Verificar documento
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT id_usuario
                FROM usuario
                WHERE tipo_doc = :tipo_doc
                  AND num_doc = :num_doc
                LIMIT 1
            """),
            {
                "tipo_doc": tipo_doc,
                "num_doc": num_doc,
            },
        )

        if result.mappings().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El documento de identidad ya está registrado.",
            )

        # ----------------------------------------------------
        # Buscar rol Auditor
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT id_rol
                FROM rol
                WHERE LOWER(nombre) = LOWER('Auditor')
                LIMIT 1
            """)
        )

        rol = result.mappings().first()

        if not rol:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No existe el rol Auditor en el sistema.",
            )

        # ----------------------------------------------------
        # Crear usuario
        #
        # NO se crea postulacion_auditor aquí.
        # ----------------------------------------------------

        password_hash = hash_password(data.password)

        result = await self.db.execute(
            text("""
                INSERT INTO usuario (
                    nombre,
                    correo,
                    contrasena,
                    estado,
                    tipo_doc,
                    num_doc,
                    estado_auditor,
                    rol_id
                )
                VALUES (
                    :nombre,
                    :correo,
                    :contrasena,
                    'Activo',
                    :tipo_doc,
                    :num_doc,
                    'BORRADOR',
                    :rol_id
                )
                RETURNING id_usuario
            """),
            {
                "nombre": nombre,
                "correo": correo,
                "contrasena": password_hash,
                "tipo_doc": tipo_doc,
                "num_doc": num_doc,
                "rol_id": rol["id_rol"],
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            await self.db.rollback()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible crear el usuario.",
            )

        await self.db.commit()

        return {
            "id_usuario": usuario["id_usuario"],
            "estado": "Activo",
            "estado_auditor": "BORRADOR",
            "mensaje": (
                "Registro de auditor iniciado correctamente. "
                "Puede continuar diligenciando el formulario."
            ),
        }

    # ========================================================
    # FOTO DE PERFIL
    # ========================================================

    async def subir_foto_perfil(
        self,
        id_usuario: UUID,
        archivo: UploadFile,
    ):
        await self._verificar_usuario_activo(id_usuario)

        if not archivo.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe seleccionar una foto de perfil.",
            )

        extension = Path(archivo.filename).suffix.lower()
        if extension not in self.EXTENSIONES_FOTO_PERFIL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de foto no permitido. Use JPG, JPEG, PNG o WEBP.",
            )

        contenido = await archivo.read()
        if len(contenido) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La foto de perfil no puede superar 5 MB.",
            )

        self.DIRECTORIO_FOTOS_PERFIL.mkdir(parents=True, exist_ok=True)
        nombre_fisico = f"{id_usuario}_{uuid4()}{extension}"
        ruta_nueva = self.DIRECTORIO_FOTOS_PERFIL / nombre_fisico
        url_nueva = f"/uploads/auditores/perfiles/{nombre_fisico}"

        result = await self.db.execute(
            text("""
                SELECT foto_url
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        perfil = result.mappings().first()
        foto_anterior = perfil["foto_url"] if perfil else None

        try:
            ruta_nueva.write_bytes(contenido)

            if perfil:
                await self.db.execute(
                    text("""
                        UPDATE perfil_auditor
                        SET foto_url = :foto_url
                        WHERE id_usuario = :id_usuario
                    """),
                    {
                        "id_usuario": id_usuario,
                        "foto_url": url_nueva,
                    },
                )
            else:
                await self.db.execute(
                    text("""
                        INSERT INTO perfil_auditor (
                            id_usuario,
                            foto_url,
                            calificacion_promedio
                        )
                        VALUES (
                            :id_usuario,
                            :foto_url,
                            0
                        )
                    """),
                    {
                        "id_usuario": id_usuario,
                        "foto_url": url_nueva,
                    },
                )

            await self.db.commit()
        except Exception as error:
            await self.db.rollback()
            if ruta_nueva.exists():
                try:
                    ruta_nueva.unlink()
                except OSError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible guardar la foto de perfil.",
            ) from error

        if foto_anterior and foto_anterior.startswith("/uploads/auditores/perfiles/"):
            ruta_anterior = Path(foto_anterior.lstrip("/"))
            if ruta_anterior.exists() and ruta_anterior != ruta_nueva:
                try:
                    ruta_anterior.unlink()
                except OSError:
                    pass

        return {
            "mensaje": "Foto de perfil cargada correctamente.",
            "foto_url": url_nueva,
        }

    async def eliminar_foto_perfil(self, id_usuario: UUID):
        await self._verificar_usuario_activo(id_usuario)

        result = await self.db.execute(
            text("""
                SELECT foto_url
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        perfil = result.mappings().first()

        if not perfil or not perfil["foto_url"]:
            return {
                "mensaje": "El auditor no tiene una foto de perfil cargada.",
                "foto_url": None,
            }

        foto_url = perfil["foto_url"]

        await self.db.execute(
            text("""
                UPDATE perfil_auditor
                SET foto_url = NULL
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )
        await self.db.commit()

        if foto_url.startswith("/uploads/auditores/perfiles/"):
            ruta = Path(foto_url.lstrip("/"))
            if ruta.exists():
                try:
                    ruta.unlink()
                except OSError:
                    pass

        return {
            "mensaje": "Foto de perfil eliminada correctamente.",
            "foto_url": None,
        }

    # ========================================================
    # CONFLICTO - DECLARAR QUE NO EXISTE
    # ========================================================

    async def declarar_sin_conflicto(self, id_usuario: UUID):
        """
        Registra la decisión de que el auditor NO tiene conflicto.

        La pantalla actual maneja una sola declaración de conflicto, por lo
        que al elegir "No" se eliminan todos los conflictos previamente
        registrados para evitar que queden filas antiguas visibles en el
        administrador.
        """
        await self._verificar_usuario_borrador(id_usuario)

        await self.db.execute(
            text("""
                DELETE FROM conflicto_interes
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )
        await self.db.commit()

        return {
            "sin_conflicto": True,
            "tiene_conflicto": False,
            "mensaje": "Se registró correctamente la declaración de que no existe ningún conflicto de interés.",
        }

    # ========================================================
    # PERFIL
    # ========================================================

    async def guardar_perfil(
        self,
        id_usuario: UUID,
        data: PerfilAuditorCrear,
    ):

        # El perfil puede editarse también por auditores ya aprobados (Activo).
        # Solo verificamos que el usuario exista y esté activo.
        result = await self.db.execute(
            text("""
                SELECT id_usuario, estado
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        usuario = result.mappings().first()
        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario auditor.",
            )
        if str(usuario["estado"] or "").strip().upper() != "ACTIVO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El usuario no está activo.",
            )

        id_postulacion = await self._obtener_postulacion_activa(id_usuario)

        result = await self.db.execute(
            text("""
                SELECT id_perfil
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                  AND (
                        (CAST(:id_postulacion AS UUID) IS NOT NULL AND id_postulacion = CAST(:id_postulacion AS UUID))
                        OR
                        (CAST(:id_postulacion AS UUID) IS NULL AND id_postulacion IS NULL)
                  )
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
                "id_postulacion": id_postulacion,
            },
        )

        perfil = result.mappings().first()

        if perfil:

            await self.db.execute(
                text("""
                    UPDATE perfil_auditor
                    SET
                        ciudad_residencia = :ciudad_residencia,
                        departamento_residencia = :departamento_residencia,
                        modalidad_preferida = :modalidad_preferida,
                        foto_url = :foto_url,
                        resumen_profesional = :resumen_profesional
                    WHERE id_perfil = :id_perfil
                """),
                {
                    "id_perfil": perfil["id_perfil"],
                    "ciudad_residencia": data.ciudad_residencia,
                    "departamento_residencia": data.departamento_residencia,
                    "modalidad_preferida": data.modalidad_preferida,
                    "foto_url": data.foto_url,
                    "resumen_profesional": data.resumen_profesional,
                },
            )

        else:

            await self.db.execute(
                text("""
                    INSERT INTO perfil_auditor (
                        id_usuario,
                        foto_url,
                        ciudad_residencia,
                        departamento_residencia,
                        modalidad_preferida,
                        resumen_profesional,
                        calificacion_promedio,
                        id_postulacion
                    )
                    VALUES (
                        :id_usuario,
                        :foto_url,
                        :ciudad_residencia,
                        :departamento_residencia,
                        :modalidad_preferida,
                        :resumen_profesional,
                        0,
                        :id_postulacion
                    )
                """),
                {
                    "id_usuario": id_usuario,
                    "foto_url": data.foto_url,
                    "ciudad_residencia": data.ciudad_residencia,
                    "departamento_residencia": data.departamento_residencia,
                    "modalidad_preferida": data.modalidad_preferida,
                    "resumen_profesional": data.resumen_profesional,
                    "id_postulacion": id_postulacion,
                },
            )

        if (data.nombre or "").strip():
            await self.db.execute(
                text("""
                    UPDATE usuario
                    SET nombre = :nombre
                    WHERE id_usuario = :id_usuario
                """),
                {
                    "nombre": data.nombre.strip(),
                    "id_usuario": id_usuario,
                },
            )

        await self.db.commit()

        return {
            "mensaje": "Perfil del auditor guardado correctamente."
        }

    # ========================================================
    # COMPETENCIA - CREAR
    # ========================================================

    async def crear_competencia(
        self,
        id_usuario: UUID,
        data: CompetenciaAuditorCrear,
    ):

        await self._verificar_usuario_borrador(id_usuario)

        tipo_valido = {
            "Norma ISO",
            "Sector IAF",
            "Experiencia Laboral",
            "Estudio",
            "Curso",
        }

        if data.tipo_competencia not in tipo_valido:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Tipo de competencia no válido. "
                    "Use: Norma ISO, Sector IAF, "
                    "Experiencia Laboral, Estudio o Curso."
                ),
            )

        id_postulacion = await self._obtener_postulacion_activa(id_usuario)

        if id_postulacion is None:
            postulacion = await self._obtener_o_crear_postulacion_borrador(
                id_usuario
            )
            id_postulacion = postulacion["id_postulacion"]

        result = await self.db.execute(
            text("""
                INSERT INTO competencia_auditor (
                    id_usuario,
                    tipo_competencia,
                    id_norma,
                    codigo_sector_iaf,
                    titulo_institucion,
                    descripcion,
                    fecha_inicio,
                    fecha_fin,
                    es_vigente,
                    estado_validacion,
                    id_postulacion
                )
                VALUES (
                    :id_usuario,
                    :tipo_competencia,
                    :id_norma,
                    :codigo_sector_iaf,
                    :titulo_institucion,
                    :descripcion,
                    :fecha_inicio,
                    :fecha_fin,
                    :es_vigente,
                    'Pendiente',
                    :id_postulacion
                )
                RETURNING id_competencia
            """),
            {
                "id_usuario": id_usuario,
                "tipo_competencia": data.tipo_competencia,
                "id_norma": data.id_norma,
                "codigo_sector_iaf": data.codigo_sector_iaf,
                "titulo_institucion": data.titulo_institucion,
                "descripcion": data.descripcion,
                "fecha_inicio": data.fecha_inicio,
                "fecha_fin": data.fecha_fin,
                "es_vigente": data.es_vigente,
                "id_postulacion": id_postulacion,
            },
        )

        try:
            competencia = result.mappings().first()
            await self.db.commit()
        except Exception as error:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No fue posible registrar la competencia: {error}",
            ) from error

        return {
            "id_competencia": competencia["id_competencia"],
            "mensaje": "Competencia registrada correctamente.",
        }

    # ========================================================

    async def eliminar_competencia(self, id_usuario: UUID, id_competencia: UUID):
        await self._verificar_usuario_borrador(id_usuario)

        result = await self.db.execute(
            text("""
                DELETE FROM competencia_auditor
                WHERE id_competencia = :id_competencia
                  AND id_usuario = :id_usuario
                  AND COALESCE(estado_validacion, 'Pendiente') <> 'Aprobado'
                RETURNING id_competencia
            """),
            {
                "id_competencia": id_competencia,
                "id_usuario": id_usuario,
            },
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La competencia no existe, no pertenece al auditor o ya fue aprobada.",
            )
        await self.db.commit()
        return {"mensaje": "Competencia eliminada correctamente."}

    async def consultar_catalogo_competencias(self):
        result = await self.db.execute(
            text("""
                SELECT
                    id_norma,
                    codigo,
                    nombre,
                    version
                FROM norma
                ORDER BY codigo ASC
            """)
        )
        return [dict(row) for row in result.mappings().all()]

    async def consultar_sectores_iaf(self):
        result = await self.db.execute(
            text("""
                SELECT DISTINCT codigo_sector_iaf
                FROM competencia_auditor
                WHERE codigo_sector_iaf IS NOT NULL
                  AND TRIM(codigo_sector_iaf) <> ''
                ORDER BY codigo_sector_iaf
            """)
        )
        return [dict(row) for row in result.mappings().all()]


    async def registrar_curso_complementario(
        self,
        id_usuario: UUID,
        data: CompetenciaAuditorCrear,
    ):
        data.tipo_competencia = "Curso"
        return await self.crear_competencia(
            id_usuario=id_usuario,
            data=data,
        )

    async def registrar_certificacion(
        self,
        id_usuario: UUID,
        data: CompetenciaAuditorCrear,
    ):
        data.tipo_competencia = "Certificaci\u00f3n vigente"
        return await self.crear_competencia(
            id_usuario=id_usuario,
            data=data,
        )


    async def listar_competencias(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT
                    ca.id_competencia,
                    ca.tipo_competencia,
                    ca.id_norma,
                    ca.codigo_sector_iaf,
                    ca.titulo_institucion,
                    ca.descripcion,
                    ca.fecha_inicio,
                    ca.fecha_fin,
                    ca.es_vigente,
                    ca.estado_validacion,
                    ca.observacion_validacion,
                    n.nombre AS norma_nombre,
                    n.codigo AS norma_codigo,
                    n.version AS norma_version
                FROM competencia_auditor ca
                LEFT JOIN norma n
                    ON n.id_norma = ca.id_norma
                WHERE ca.id_usuario = :id_usuario
                ORDER BY ca.fecha_inicio DESC
            """),
            {"id_usuario": id_usuario},
        )
        return [dict(row) for row in result.mappings().all()]

    async def consultar_historial_academico(
        self,
        id_usuario: UUID,
    ):
        titulos = await self.listar_titulos_academicos(
            id_usuario=id_usuario
        )
        competencias = await self.listar_competencias(
            id_usuario=id_usuario
        )

        historial = sorted(
            [
                {
                    "categoria": "Título académico",
                    **titulo,
                }
                for titulo in titulos
            ]
            + [
                {
                    "categoria": "Competencia / curso / certificación",
                    **competencia,
                }
                for competencia in competencias
            ],
            key=lambda item: str(
                item.get("fecha_grado")
                or item.get("fecha_inicio")
                or ""
            ),
            reverse=True,
        )

        return {
            "id_usuario": id_usuario,
            "registros": historial,
            "totales": {
                "titulos": len(titulos),
                "competencias_curso_certificacion": len(competencias),
            },
        }

    # COMPETENCIA - ACTUALIZAR
    # ========================================================

    async def actualizar_competencia(
        self,
        id_usuario: UUID,
        id_competencia: UUID,
        data: CompetenciaAuditorCrear,
    ):

        # Las competencias pueden actualizarse también por auditores ya aprobados (Activo).
        result = await self.db.execute(
            text("""
                SELECT id_usuario, estado, estado_auditor
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        usuario = result.mappings().first()
        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario auditor.",
            )
        if str(usuario["estado"] or "").strip().upper() != "ACTIVO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El usuario no está activo.",
            )
        if str(usuario["estado_auditor"] or "").strip().upper() not in {"ACTIVO", "APROBADO", "APROBADA"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El auditor no se encuentra aprobado/activo.",
            )

        result = await self.db.execute(
            text("""
                UPDATE competencia_auditor
                SET
                    id_norma = :id_norma,
                    tipo_competencia = :tipo_competencia,
                    codigo_sector_iaf = :codigo_sector_iaf,
                    titulo_institucion = :titulo_institucion,
                    descripcion = :descripcion,
                    fecha_inicio = :fecha_inicio,
                    fecha_fin = :fecha_fin,
                    es_vigente = :es_vigente
                WHERE id_competencia = :id_competencia
                  AND id_usuario = :id_usuario
                RETURNING id_competencia
            """),
            {
                "id_competencia": id_competencia,
                "id_usuario": id_usuario,
                "id_norma": data.id_norma,
                "tipo_competencia": data.tipo_competencia,
                "codigo_sector_iaf": data.codigo_sector_iaf,
                "titulo_institucion": data.titulo_institucion,
                "descripcion": data.descripcion,
                "fecha_inicio": data.fecha_inicio,
                "fecha_fin": data.fecha_fin,
                "es_vigente": data.es_vigente,
            },
        )

        actualizado = result.mappings().first()

        if not actualizado:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La competencia no existe o no pertenece al auditor.",
            )

        await self.db.commit()

        return {
            "id_competencia": actualizado["id_competencia"],
            "mensaje": "Competencia actualizada correctamente.",
        }

    # ========================================================
    # CONFLICTO - CREAR
    # ========================================================

    async def crear_conflicto(
        self,
        id_usuario: UUID,
        data: ConflictoInteresCrear,
    ):

        await self._verificar_usuario_borrador(id_usuario)

        # La interfaz permite declarar un único conflicto. Eliminamos
        # registros anteriores para evitar duplicados históricos.
        await self.db.execute(
            text("""
                DELETE FROM conflicto_interes
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )

        id_postulacion = await self._obtener_postulacion_activa(id_usuario)
        result = await self.db.execute(
            text("""
                INSERT INTO conflicto_interes (
                    id_usuario,
                    id_empresa,
                    tipo_conflicto,
                    descripcion,
                    bloquea_asignacion,
                    fecha_declaracion,
                    estado,
                    id_postulacion
                )
                VALUES (
                    :id_usuario,
                    :id_empresa,
                    :tipo_conflicto,
                    :descripcion,
                    :bloquea_asignacion,
                    CURRENT_TIMESTAMP,
                    'Activo',
                    :id_postulacion
                )
                RETURNING id_conflicto
            """),
            {
                "id_usuario": id_usuario,
                "id_empresa": data.id_empresa,
                "tipo_conflicto": data.tipo_conflicto,
                "descripcion": data.descripcion,
                "bloquea_asignacion": data.bloquea_asignacion,
                "id_postulacion": id_postulacion,
            },
        )

        conflicto = result.mappings().first()

        await self.db.commit()

        return {
            "id_conflicto": conflicto["id_conflicto"],
            "mensaje": "Conflicto de interés registrado correctamente.",
        }

    # ========================================================
    # CONFLICTO - CREAR DESDE ADMINISTRADOR (sin restricci��n de estado)
    # ========================================================
    async def crear_conflicto_administrador(self, id_usuario: UUID, data: ConflictoInteresCrear):
        result = await self.db.execute(
            text("SELECT id_usuario FROM usuario WHERE id_usuario = :id_usuario"),
            {"id_usuario": id_usuario},
        )
        if not result.scalar():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No se encontr�� el usuario auditor.")
        id_postulacion = await self._obtener_postulacion_activa(id_usuario)
        result = await self.db.execute(
            text("""
                INSERT INTO conflicto_interes (
                    id_usuario, id_empresa, tipo_conflicto, descripcion,
                    bloquea_asignacion, fecha_declaracion, estado, id_postulacion
                ) VALUES (
                    :id_usuario, :id_empresa, :tipo_conflicto, :descripcion,
                    :bloquea_asignacion, CURRENT_TIMESTAMP, 'Activo', :id_postulacion
                )
                RETURNING id_conflicto
            """),
            {
                "id_usuario": id_usuario,
                "id_empresa": data.id_empresa,
                "tipo_conflicto": data.tipo_conflicto,
                "descripcion": data.descripcion,
                "bloquea_asignacion": data.bloquea_asignacion,
                "id_postulacion": id_postulacion,
            },
        )
        conflicto = result.mappings().first()
        await self.db.commit()
        return {"id_conflicto": conflicto["id_conflicto"], "mensaje": "Conflicto de inter��s registrado correctamente."}

    # ========================================================
    # CONFLICTO - ACTUALIZAR
    # ========================================================

    async def actualizar_conflicto(
        self,
        id_usuario: UUID,
        id_conflicto: UUID,
        data: ConflictoInteresCrear,
    ):

        await self._verificar_usuario_borrador(id_usuario)

        result = await self.db.execute(
            text("""
                UPDATE conflicto_interes
                SET
                    id_empresa = :id_empresa,
                    tipo_conflicto = :tipo_conflicto,
                    descripcion = :descripcion,
                    bloquea_asignacion = :bloquea_asignacion
                WHERE id_conflicto = :id_conflicto
                  AND id_usuario = :id_usuario
                RETURNING id_conflicto
            """),
            {
                "id_conflicto": id_conflicto,
                "id_usuario": id_usuario,
                "id_empresa": data.id_empresa,
                "tipo_conflicto": data.tipo_conflicto,
                "descripcion": data.descripcion,
                "bloquea_asignacion": data.bloquea_asignacion,
            },
        )

        actualizado = result.mappings().first()

        if actualizado:
            # Conservamos únicamente el conflicto que acaba de editarse.
            await self.db.execute(
                text("""
                    DELETE FROM conflicto_interes
                    WHERE id_usuario = :id_usuario
                      AND id_conflicto <> :id_conflicto
                """),
                {
                    "id_usuario": id_usuario,
                    "id_conflicto": id_conflicto,
                },
            )

        if not actualizado:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "El conflicto no existe o no pertenece al auditor."
                ),
            )

        await self.db.commit()

        return {
            "id_conflicto": actualizado["id_conflicto"],
            "mensaje": "Conflicto actualizado correctamente.",
        }

    # ========================================================

    async def listar_conflictos(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT c.id_conflicto, c.id_empresa, e.nombre AS empresa, e.nit,
                       c.tipo_conflicto, c.descripcion, c.bloquea_asignacion,
                       c.fecha_declaracion, c.estado
                FROM conflicto_interes c
                INNER JOIN empresa e ON e.id_empresa = c.id_empresa
                WHERE c.id_usuario = :id_usuario
                ORDER BY c.fecha_declaracion DESC
            """),
            {"id_usuario": id_usuario},
        )
        return [dict(row) for row in result.mappings().all()]

    async def eliminar_conflicto(self, id_usuario: UUID, id_conflicto: UUID):
        await self._verificar_usuario_borrador(id_usuario)
        result = await self.db.execute(
            text("""
                DELETE FROM conflicto_interes
                WHERE id_conflicto = :id_conflicto
                  AND id_usuario = :id_usuario
                RETURNING id_conflicto
            """),
            {"id_conflicto": id_conflicto, "id_usuario": id_usuario},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(404, "El conflicto no existe o no pertenece al auditor.")
        await self.db.commit()
        return {"mensaje": "Conflicto eliminado correctamente."}

    # ========================================================
    # CONFLICTO - ELIMINAR DESDE ADMINISTRADOR (sin restricci��n de borrador)
    # ========================================================
    async def eliminar_conflicto_administrador(self, id_usuario: UUID, id_conflicto: UUID):
        result = await self.db.execute(
            text("SELECT id_usuario FROM usuario WHERE id_usuario = :id_usuario"),
            {"id_usuario": id_usuario},
        )
        if not result.scalar():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No se encontr�� el usuario auditor.")
        result = await self.db.execute(
            text("""
                DELETE FROM conflicto_interes
                WHERE id_conflicto = :id_conflicto
                  AND id_usuario = :id_usuario
                RETURNING id_conflicto
            """),
            {"id_conflicto": id_conflicto, "id_usuario": id_usuario},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(404, "El conflicto no existe o no pertenece al auditor.")
        await self.db.commit()
        return {"mensaje": "Conflicto eliminado correctamente."}

    async def consultar_empresas_restringidas(self):
        result = await self.db.execute(
            text("""
                SELECT DISTINCT e.id_empresa, e.nombre, e.nit,
                       ci.tipo_conflicto, ci.descripcion, ci.estado
                FROM conflicto_interes ci
                INNER JOIN empresa e ON e.id_empresa = ci.id_empresa
                WHERE ci.estado = 'Activo' AND ci.bloquea_asignacion = TRUE
                ORDER BY e.nombre ASC
            """)
        )
        return [dict(row) for row in result.mappings().all()]

    async def validar_conflicto_antes_asignacion(self, id_usuario: UUID, id_empresa: UUID):
        result = await self.db.execute(
            text("""
                SELECT id_conflicto, tipo_conflicto, descripcion
                FROM conflicto_interes
                WHERE id_usuario = :id_usuario
                  AND id_empresa = :id_empresa
                  AND estado = 'Activo'
            """),
            {"id_usuario": id_usuario, "id_empresa": id_empresa},
        )
        conflictos = [dict(row) for row in result.mappings().all()]
        return {"tiene_conflicto": len(conflictos) > 0, "detalles": conflictos}

    # REENVIAR POSTULACIÓN DESPUÉS DE CORRECCIONES
    # ========================================================

    async def reenviar_postulacion_correcciones(
        self,
        id_postulacion: UUID,
        id_usuario: UUID,
    ):
        """
        Reenvía exactamente la postulación que el administrador
        devolvió a Correcciones. No crea una postulación nueva.
        """

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado
                FROM postulacion_auditor
                WHERE id_postulacion = :id_postulacion
                  AND id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
                "id_usuario": id_usuario,
            },
        )

        postulacion = result.mappings().first()

        if not postulacion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación solicitada para este auditor.",
            )

        if postulacion["estado"] != "Correcciones":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La postulación no se encuentra en estado "
                    "'Correcciones'. Estado actual: "
                    f"'{postulacion['estado']}'."
                ),
            )

        # Reutilizar la misma fila. El método de envío valida
        # documentos y cambia Correcciones -> Enviado.
        return await self.enviar_solicitud(id_usuario)


    # ========================================================
    # ENVIAR SOLICITUD
    # ========================================================

    async def enviar_solicitud(
        self,
        id_usuario: UUID,
    ):
        # ========================================================
        # BUSCAR USUARIO
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_usuario,
                    nombre,
                    correo,
                    estado,
                    estado_auditor
                FROM usuario
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        usuario = result.mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró el usuario del auditor.",
            )

        # ========================================================
        # NO PERMITIR SI YA ESTÁ APROBADO
        # ========================================================

        if usuario["estado_auditor"] == "APROBADO":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El auditor ya se encuentra aprobado.",
            )

        # ========================================================
        # BUSCAR ÚLTIMA POSTULACIÓN
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_postulacion,
                    fecha_revision
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        postulacion = result.mappings().first()

        if not postulacion:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No existe una postulación. "
                    "Debe completar la información antes de enviar."
                ),
            )

        # ========================================================
        # ESTADOS QUE PUEDEN SER ENVIADOS
        #
        # Borrador      -> Enviado
        # Correcciones  -> Enviado
        #
        # EN AMBOS CASOS ES LA MISMA FILA.
        # ========================================================

        estados_editables = {
            "Borrador",
            "Correcciones",
        }

        if postulacion["estado"] not in estados_editables:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La última postulación se encuentra en estado "
                    f"'{postulacion['estado']}' y no puede ser enviada."
                ),
            )

        id_postulacion = postulacion["id_postulacion"]

        # ========================================================
        # VERIFICAR DOCUMENTOS
        #
        # Se buscan los documentos de ESTA postulación.
        # ========================================================

        result = await self.db.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM documento_auditor
                WHERE id_usuario = :id_usuario
                AND id_postulacion = :id_postulacion
            """),
            {
                "id_usuario": id_usuario,
                "id_postulacion": id_postulacion,
            },
        )

        total_documentos = result.scalar() or 0

        if total_documentos == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Debe adjuntar al menos un documento de soporte "
                    "antes de enviar la inscripción."
                ),
            )

        # ========================================================
        # CORRECCIONES -> ENVIADO
        #
        # NO SE CREA POSTULACIÓN NUEVA.
        #
        # Se actualiza la MISMA fila.
        # ========================================================

        result = await self.db.execute(
            text("""
                UPDATE postulacion_auditor
                SET
                    estado = 'Enviado',
                    fecha_revision = NULL
                WHERE id_postulacion = :id_postulacion
                AND id_usuario = :id_usuario
                AND estado IN ('Borrador', 'Correcciones')
                RETURNING
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_postulacion,
                    fecha_revision
            """),
            {
                "id_postulacion": id_postulacion,
                "id_usuario": id_usuario,
            },
        )

        actualizada = result.mappings().first()

        if not actualizada:
            await self.db.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible enviar la postulación. "
                    "El estado pudo haber cambiado."
                ),
            )

        # ========================================================
        # ESTADO DEL AUDITOR
        # ========================================================

        await self.db.execute(
            text("""
                UPDATE usuario
                SET estado_auditor = 'Postulante'
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        # ========================================================
        # CONFIRMAR
        # ========================================================

        await self.db.commit()

        # ========================================================
        # RESPUESTA
        # ========================================================

        return {
            "id_usuario": id_usuario,
            "id_postulacion": actualizada["id_postulacion"],
            "estado": actualizada["estado"],
            "estado_auditor": "Postulante",
            "mensaje": (
                "La postulación fue enviada correctamente. "
                "La solicitud quedó nuevamente en estado "
                "'Enviado' para revisión."
            ),
            "faltantes": [],
        }
  
  
  
    # ========================================================
    # CONSULTAR ESTADO por correo
    # ========================================================

    async def consultar_estado_por_correo(self, correo: str):
        """Devuelve los datos del auditor y solo sus postulaciones enviadas,
        en revisión, aprobadas, devueltas a correcciones o rechazadas.

        Los borradores y las postulaciones canceladas no se incluyen en la
        lista que alimenta el paginador.
        """
        result = await self.db.execute(
            text("""
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.correo,
                    u.tipo_doc,
                    u.num_doc,
                    u.estado AS estado_usuario,
                    u.estado_auditor,
                    r.nombre AS rol
                FROM usuario u
                LEFT JOIN rol r ON r.id_rol = u.rol_id
                WHERE LOWER(TRIM(u.correo)) = LOWER(TRIM(:correo))
                LIMIT 1
            """),
            {"correo": correo},
        )
        auditor = result.mappings().first()

        if not auditor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró un usuario con ese correo.",
            )

        # Consulta todas las postulaciones que llegaron al flujo de revisión.
        # Se excluyen explícitamente Borrador y Cancelado.
        result = await self.db.execute(
            text("""
                SELECT
                    p.id_postulacion,
                    p.id_usuario,
                    p.estado AS estado_postulacion,
                    p.fecha_postulacion,
                    p.fecha_revision,
                    p.observaciones_tecnicas
                FROM postulacion_auditor p
                WHERE p.id_usuario = :id_usuario
                AND LOWER(TRIM(COALESCE(p.estado, ''))) IN (
                    'enviado',
                    'en revisión',
                    'en revision',
                    'aprobado',
                    'rechazado',
                    'correcciones'
                )
                ORDER BY p.fecha_postulacion DESC NULLS LAST,
                        p.id_postulacion DESC
            """),
            {"id_usuario": auditor["id_usuario"]},
        )
        filas_postulaciones = result.mappings().all()
        postulaciones = []

        for fila in filas_postulaciones:
            postulacion = dict(fila)
            id_postulacion = postulacion["id_postulacion"]
            estado_normalizado = str(
                postulacion.get("estado_postulacion") or ""
            ).strip().lower()

            # Último registro en el que esta postulación fue devuelta a correcciones.
            correccion = None
            try:
                result = await self.db.execute(
                    text("""
                        SELECT
                            h.id_historial,
                            h.id_postulacion,
                            h.id_usuario_administrador,
                            h.estado_anterior,
                            h.estado_nuevo,
                            h.observaciones,
                            h.fecha_cambio,
                            admin.nombre AS administrador
                        FROM historial_postulacion_auditor h
                        LEFT JOIN usuario admin
                            ON admin.id_usuario = h.id_usuario_administrador
                        WHERE h.id_postulacion = :id_postulacion
                        AND LOWER(h.estado_nuevo) = LOWER('Correcciones')
                        ORDER BY h.fecha_cambio DESC
                        LIMIT 1
                    """),
                    {"id_postulacion": id_postulacion},
                )
                correccion = result.mappings().first()
            except Exception:
                # Si el historial de correcciones no está disponible, la
                # consulta del estado debe seguir mostrando la postulación.
                await self.db.rollback()
                correccion = None

            observaciones_correccion = (
                correccion["observaciones"] if correccion else ""
            ) or ""
            if not observaciones_correccion and estado_normalizado == "correcciones":
                observaciones_correccion = (
                    postulacion.get("observaciones_tecnicas") or ""
                )

            # Última observación de rechazo asociada a ESTA postulación.
            rechazo = None
            try:
                result = await self.db.execute(
                    text("""
                        SELECT observacion AS observaciones
                        FROM historial_estado
                        WHERE id_solicitud = :id_postulacion
                        AND LOWER(estado) = LOWER('Rechazado')
                        ORDER BY fecha DESC
                        LIMIT 1
                    """),
                    {"id_postulacion": id_postulacion},
                )
                rechazo = result.mappings().first()
            except Exception:
                # La postulación se conserva aunque no exista historial_estado
                # o el historial no esté disponible.
                await self.db.rollback()
                rechazo = None

            observaciones_rechazo = (
                rechazo["observaciones"] if rechazo else ""
            ) or ""
            if not observaciones_rechazo and estado_normalizado == "rechazado":
                observaciones_rechazo = (
                    postulacion.get("observaciones_tecnicas") or ""
                )

            postulacion["estado"] = postulacion.get("estado_postulacion")
            postulacion["observaciones_correccion"] = observaciones_correccion
            postulacion["observaciones_rechazo"] = observaciones_rechazo
            postulacion["administrador_correccion"] = (
                correccion["administrador"] if correccion else None
            )
            postulacion["fecha_correccion"] = (
                correccion["fecha_cambio"] if correccion else None
            )
            postulacion["estado_anterior_correccion"] = (
                correccion["estado_anterior"] if correccion else None
            )
            postulacion["tiene_correcciones"] = bool(observaciones_correccion)
            postulaciones.append(postulacion)

        # La pantalla usa estos campos superiores como compatibilidad con la
        # postulación seleccionada inicialmente: la más reciente de las visibles.
        actual = postulaciones[0] if postulaciones else None

        return {
            "id_usuario": auditor["id_usuario"],
            "nombre": auditor["nombre"],
            "correo": auditor["correo"],
            "tipo_doc": auditor["tipo_doc"],
            "num_doc": auditor["num_doc"],
            "estado_usuario": auditor["estado_usuario"],
            "estado_auditor": auditor["estado_auditor"],
            "rol": auditor["rol"] or "Auditor",
            "id_postulacion": actual["id_postulacion"] if actual else None,
            "estado_postulacion": actual["estado_postulacion"] if actual else None,
            "fecha_postulacion": actual["fecha_postulacion"] if actual else None,
            "fecha_revision": actual["fecha_revision"] if actual else None,
            "observaciones_correccion": actual["observaciones_correccion"] if actual else "",
            "observaciones_rechazo": actual["observaciones_rechazo"] if actual else "",
            "administrador_correccion": actual["administrador_correccion"] if actual else None,
            "fecha_correccion": actual["fecha_correccion"] if actual else None,
            "tiene_correcciones": bool(
                actual
                and str(actual.get("estado_postulacion") or "").strip().lower() == "correcciones"
                and actual.get("observaciones_correccion")
            ),
            "postulaciones": postulaciones,
        }


    # ========================================================
    # CONSULTAR ESTADO POR POSTULACIÓN
    # ========================================================

    async def consultar_estado(
        self,
        id_postulacion: UUID,
    ):

        result = await self.db.execute(
            text("""
                SELECT
                    pa.id_postulacion,
                    pa.id_usuario,
                    pa.estado AS estado_postulacion,
                    u.nombre,
                    u.correo,
                    u.estado AS estado_usuario,
                    u.estado_auditor
                FROM postulacion_auditor pa
                INNER JOIN usuario u
                    ON u.id_usuario = pa.id_usuario
                WHERE pa.id_postulacion = :id_postulacion
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        auditor = result.mappings().first()

        if not auditor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación.",
            )

        return {
            "id_usuario": auditor["id_usuario"],
            "id_postulacion": auditor["id_postulacion"],
            "nombre": auditor["nombre"],
            "correo": auditor["correo"],
            "estado_usuario": auditor["estado_usuario"],
            "estado_auditor": auditor["estado_auditor"],
            "estado_postulacion": auditor["estado_postulacion"],
        }

        # ========================================================
   
    # ========================================================
    # GENERAR COMPROBANTE PDF
    # ========================================================

    async def generar_comprobante_pdf(
    self,
    id_postulacion: UUID,
):
        result = await self.db.execute(
            text("""
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

                WHERE pa.id_postulacion = :id_postulacion

                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        registro = result.mappings().first()

        if not registro:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación solicitada.",
            )

        # ====================================================
        # DOCUMENTOS DE SOPORTE
        # ====================================================

        result = await self.db.execute(
            text("""
                SELECT
                    nombre_archivo,
                    tipo_documento,
                    estado_revision,
                    fecha_subida
                FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
                ORDER BY fecha_subida ASC
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        documentos = result.mappings().all()

        # ====================================================
        # CREAR PDF EN MEMORIA
        # ====================================================

        buffer = BytesIO()

        documento = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45,
        )

        estilos = getSampleStyleSheet()

        titulo = ParagraphStyle(
            "TituloCertiSENA",
            parent=estilos["Title"],
            alignment=TA_CENTER,
            fontSize=18,
            spaceAfter=8,
        )

        subtitulo = ParagraphStyle(
            "SubtituloCertiSENA",
            parent=estilos["Normal"],
            alignment=TA_CENTER,
            fontSize=11,
            spaceAfter=20,
        )

        encabezado = ParagraphStyle(
            "Encabezado",
            parent=estilos["Heading2"],
            fontSize=12,
            spaceBefore=12,
            spaceAfter=8,
        )

        contenido = []

        # ====================================================
        # ENCABEZADO
        # ====================================================

        contenido.append(
            Paragraph(
                "CertiSENA",
                titulo,
            )
        )

        contenido.append(
            Paragraph(
                "Comprobante de registro de auditor",
                subtitulo,
            )
        )

        contenido.append(
            Paragraph(
                "Información de la postulación",
                encabezado,
            )
        )

        # ====================================================
        # INFORMACIÓN DEL REGISTRO
        # ====================================================

        datos_registro = [
            ["Campo", "Información"],

            [
                "Nombre completo",
                str(registro["nombre"] or "-"),
            ],

            [
                "Correo electrónico",
                str(registro["correo"] or "-"),
            ],

            [
                "Tipo de documento",
                str(registro["tipo_doc"] or "-"),
            ],

            [
                "Número de documento",
                str(registro["num_doc"] or "-"),
            ],

            [
                "ID usuario",
                str(registro["id_usuario"]),
            ],

            [
                "ID postulación",
                str(registro["id_postulacion"]),
            ],

            [
                "Rol",
                str(registro["rol"] or "Auditor"),
            ],

            [
                "Estado de la cuenta",
                str(registro["estado_usuario"] or "-"),
            ],

            [
                "Estado del auditor",
                str(registro["estado_auditor"] or "-"),
            ],

            [
                "Estado de la postulación",
                str(registro["estado_postulacion"] or "-"),
            ],

            [
                "Fecha de postulación",
                (
                    registro["fecha_postulacion"].strftime(
                        "%d/%m/%Y %H:%M:%S"
                    )
                    if registro["fecha_postulacion"]
                    else "-"
                ),
            ],
        ]

        tabla_registro = Table(
            datos_registro,
            colWidths=[170, 320],
        )

        tabla_registro.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#256d00"),
                    ),

                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),

                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold",
                    ),

                    (
                        "FONTNAME",
                        (0, 1),
                        (0, -1),
                        "Helvetica-Bold",
                    ),

                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.5,
                        colors.grey,
                    ),

                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),

                    (
                        "PADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                ]
            )
        )

        contenido.append(tabla_registro)

        # ====================================================
        # DOCUMENTOS
        # ====================================================

        contenido.append(
            Paragraph(
                "Documentos asociados",
                encabezado,
            )
        )

        if documentos:

            datos_documentos = [
                [
                    "Archivo",
                    "Tipo",
                    "Estado",
                    "Fecha",
                ]
            ]

            for documento_registro in documentos:

                fecha = documento_registro["fecha_subida"]

                datos_documentos.append(
                    [
                        str(
                            documento_registro[
                                "nombre_archivo"
                            ]
                            or "-"
                        ),

                        str(
                            documento_registro[
                                "tipo_documento"
                            ]
                            or "-"
                        ),

                        str(
                            documento_registro[
                                "estado_revision"
                            ]
                            or "-"
                        ),

                        (
                            fecha.strftime(
                                "%d/%m/%Y %H:%M:%S"
                            )
                            if fecha
                            else "-"
                        ),
                    ]
                )

            tabla_documentos = Table(
                datos_documentos,
                colWidths=[
                    180,
                    100,
                    100,
                    110,
                ],
                repeatRows=1,
            )

            tabla_documentos.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.HexColor("#256d00"),
                        ),

                        (
                            "TEXTCOLOR",
                            (0, 0),
                            (-1, 0),
                            colors.white,
                        ),

                        (
                            "FONTNAME",
                            (0, 0),
                            (-1, 0),
                            "Helvetica-Bold",
                        ),

                        (
                            "GRID",
                            (0, 0),
                            (-1, -1),
                            0.5,
                            colors.grey,
                        ),

                        (
                            "VALIGN",
                            (0, 0),
                            (-1, -1),
                            "MIDDLE",
                        ),

                        (
                            "FONTSIZE",
                            (0, 0),
                            (-1, -1),
                            8,
                        ),

                        (
                            "PADDING",
                            (0, 0),
                            (-1, -1),
                            6,
                        ),
                    ]
                )
            )

            contenido.append(tabla_documentos)

        else:

            contenido.append(
                Paragraph(
                    "No existen documentos asociados a esta postulación.",
                    estilos["Normal"],
                )
            )

        # ====================================================
        # PIE
        # ====================================================

        contenido.append(
            Spacer(1, 25)
        )

        contenido.append(
            Paragraph(
                "Este documento es un comprobante generado "
                "por el sistema CertiSENA.",
                estilos["Normal"],
            )
        )

        documento.build(contenido)

        buffer.seek(0)

        # ====================================================
        # RESPUESTA
        # ====================================================

        nombre_pdf = (
            f"comprobante_registro_"
            f"{str(registro['id_postulacion'])}.pdf"
        )

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'inline; filename="{nombre_pdf}"'
                )
            },
        )

   
    # CANCELAR SOLICITUD
    # ========================================================
   
    async def cancelar_solicitud(
        self,
        id_postulacion: UUID,
    ):
        # ----------------------------------------------------
        # Buscar la postulación
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    pa.id_postulacion,
                    pa.id_usuario,
                    pa.estado,
                    u.nombre,
                    u.correo
                FROM postulacion_auditor pa
                INNER JOIN usuario u
                    ON u.id_usuario = pa.id_usuario
                WHERE pa.id_postulacion = :id_postulacion
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        postulacion = result.mappings().first()

        if not postulacion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación.",
            )

        # ----------------------------------------------------
        # Solo se puede cancelar una solicitud Enviada
        # ----------------------------------------------------

        if postulacion["estado"] != "Enviado":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La solicitud no puede ser cancelada porque "
                    "actualmente se encuentra en estado "
                    f"'{postulacion['estado']}'."
                ),
            )

        # ----------------------------------------------------
        # CAMBIAR ESTADO
        # ----------------------------------------------------
        # IMPORTANTE:
        # Aquí NO eliminamos ningún dato.
        #
        # Los datos se eliminarán mediante el endpoint:
        #
        # DELETE
        # /registro/postulacion/{id_postulacion}/datos
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                UPDATE postulacion_auditor
                SET estado = 'Cancelado'
                WHERE id_postulacion = :id_postulacion
                AND estado = 'Enviado'
                RETURNING
                    id_postulacion,
                    id_usuario,
                    estado
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        postulacion_cancelada = result.mappings().first()

        if not postulacion_cancelada:
            await self.db.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No fue posible cancelar la postulación. "
                    "Es posible que su estado haya cambiado."
                ),
            )

        # ----------------------------------------------------
        # GUARDAR CAMBIO
        # ----------------------------------------------------

        await self.db.commit()

        # ----------------------------------------------------
        # RESPUESTA
        # ----------------------------------------------------

        return {
            "id_postulacion": postulacion_cancelada[
                "id_postulacion"
            ],
            "id_usuario": postulacion_cancelada[
                "id_usuario"
            ],
            "estado": "Cancelado",
            "mensaje": (
                "La solicitud fue cancelada correctamente. "
                "Los datos registrados todavía se conservan "
                "hasta ejecutar el proceso de eliminación."
            ),
        }
  

    # ========================================================
    # ELIMINAR DATOS DE POSTULACIÓN CANCELADA
    # ========================================================

    async def eliminar_datos_postulacion_cancelada(
        self,
        id_postulacion: UUID,
    ):
        # ----------------------------------------------------
        # BUSCAR POSTULACIÓN
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado
                FROM postulacion_auditor
                WHERE id_postulacion = :id_postulacion
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        postulacion = result.mappings().first()

        if not postulacion:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró la postulación.",
            )

        # ----------------------------------------------------
        # VERIFICAR ESTADO
        # ----------------------------------------------------

        if postulacion["estado"] != "Cancelado":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se pueden eliminar los datos de una "
                    "postulación que se encuentre en estado "
                    "'Cancelado'."
                ),
            )

        id_usuario = postulacion["id_usuario"]

        # ====================================================
        # 1. OBTENER DOCUMENTOS
        # ====================================================
        #
        # Primero obtenemos las rutas físicas porque después
        # eliminaremos los registros de la base de datos.
        # ====================================================

        result = await self.db.execute(
            text("""
                SELECT
                    id_documento,
                    url_archivo
                FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        documentos = result.mappings().all()

        # ====================================================
        # 2. ELIMINAR DOCUMENTOS DE LA BD
        # ====================================================

        await self.db.execute(
            text("""
                DELETE FROM documento_auditor
                WHERE id_postulacion = :id_postulacion
            """),
            {
                "id_postulacion": id_postulacion,
            },
        )

        # ====================================================
        # 3. ELIMINAR CONFLICTOS
        # ====================================================

        await self.db.execute(
            text("""
                DELETE FROM conflicto_interes
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        # ====================================================
        # 4. ELIMINAR COMPETENCIAS
        # ====================================================

        await self.db.execute(
            text("""
                DELETE FROM competencia_auditor
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        # ====================================================
        # 5. ELIMINAR PERFIL
        # ====================================================

        await self.db.execute(
            text("""
                DELETE FROM perfil_auditor
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        # ====================================================
        # IMPORTANTE
        # ====================================================
        #
        # NO eliminamos:
        #
        # usuario
        # postulacion_auditor
        #
        # La postulación permanece como:
        #
        # Cancelado
        #
        # para conservar el historial y permitir generar
        # el comprobante.
        # ====================================================

        # ----------------------------------------------------
        # GUARDAR CAMBIOS DE BASE DE DATOS
        # ----------------------------------------------------

        await self.db.commit()

        # ====================================================
        # 6. ELIMINAR ARCHIVOS FÍSICOS
        # ====================================================

        for documento in documentos:

            url_archivo = documento["url_archivo"]

            if not url_archivo:
                continue

            # La URL almacenada es:
            #
            # /uploads/auditores/nombre_archivo.pdf
            #
            # Convertimos a:
            #
            # uploads/auditores/nombre_archivo.pdf
            #

            ruta = Path(
                url_archivo.lstrip("/")
            )

            if ruta.exists():

                try:
                    ruta.unlink()

                except OSError:
                    # Si falla la eliminación física,
                    # no revertimos la eliminación de BD.
                    pass

        # ====================================================
        # RESPUESTA
        # ====================================================

        return {
            "id_postulacion": postulacion[
                "id_postulacion"
            ],
            "id_usuario": id_usuario,
            "estado": "Cancelado",
            "mensaje": (
                "Los datos del formulario de la "
                "postulación cancelada fueron eliminados "
                "correctamente. Los datos personales fueron "
                "conservados y la postulación permanece "
                "registrada como Cancelado."
            ),
        }


    # guardar archivo documento
    async def _guardar_archivo_documento(
        self,
        archivo: UploadFile,
        id_postulacion: UUID,
    ):
        if not archivo.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo no tiene un nombre válido.",
            )

        extension = Path(archivo.filename).suffix.lower()

        extensiones_permitidas = {
            ".pdf",
            ".doc",
            ".docx",
            ".jpg",
            ".jpeg",
            ".png",
        }

        if extension not in extensiones_permitidas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Tipo de archivo no permitido. "
                    "Solo se permiten PDF, DOC, DOCX, JPG, JPEG y PNG."
                ),
            )

        self.DIRECTORIO_DOCUMENTOS.mkdir(
            parents=True,
            exist_ok=True,
        )

        nombre_seguro = (
            f"{id_postulacion}_"
            f"{UUID()}"
            f"{extension}"
        )

        ruta = self.DIRECTORIO_DOCUMENTOS / nombre_seguro

        with ruta.open("wb") as buffer:
            shutil.copyfileobj(
                archivo.file,
                buffer,
            )

        return {
            "nombre_archivo": archivo.filename,
            "url_archivo": f"/uploads/auditores/{nombre_seguro}",
        }


    # ========================================================
    # REENVIAR POSTULACIÓN DESPUÉS DE CORRECCIONES
    # ========================================================

    async def _obtener_o_crear_postulacion_borrador(
        self,
        id_usuario: UUID,
    ):
        """
        Obtiene la postulación que el auditor debe utilizar.

        Reglas:

        Borrador
            -> se reutiliza.

        Correcciones
            -> se reutiliza.
            NO crear otro Borrador.

        Enviado
        En Revisión
        Aprobado
            -> no crear otra postulación.

        Cancelado
        Rechazado
            -> sí permiten iniciar una nueva postulación.
        """

        result = await self.db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        ultima = result.mappings().first()

        # ========================================================
        # NO EXISTE POSTULACIÓN
        # ========================================================

        if not ultima:

            result = await self.db.execute(
                text("""
                    INSERT INTO postulacion_auditor (
                        id_usuario,
                        estado,
                        observaciones_tecnicas,
                        fecha_postulacion,
                        fecha_revision
                    )
                    VALUES (
                        :id_usuario,
                        'Borrador',
                        '',
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    RETURNING
                        id_postulacion,
                        id_usuario,
                        estado
                """),
                {
                    "id_usuario": id_usuario,
                },
            )

            postulacion = result.mappings().first()

            if not postulacion:

                await self.db.rollback()

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "No fue posible crear el borrador "
                        "de la postulación."
                    ),
                )

            return postulacion

        # ========================================================
        # BORRADOR
        # ========================================================

        if ultima["estado"] == "Borrador":

            return ultima

        # ========================================================
        # CORRECCIONES
        #
        # MUY IMPORTANTE:
        #
        # SE DEVUELVE LA MISMA POSTULACIÓN.
        #
        # NO SE CREA BORRADOR.
        # ========================================================

        if ultima["estado"] == "Correcciones":

            return ultima

        # ========================================================
        # POSTULACIÓN ACTIVA
        # ========================================================

        if ultima["estado"] in (
            "Enviado",
            "En Revisión",
            "Aprobado",
        ):

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El auditor ya tiene una postulación activa "
                    f"en estado '{ultima['estado']}'."
                ),
            )

        # ========================================================
        # CANCELADO / RECHAZADO
        #
        # AQUÍ SÍ SE PUEDE CREAR UNA NUEVA POSTULACIÓN.
        # ========================================================

        if ultima["estado"] in (
            "Cancelado",
            "Rechazado",
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La última postulación está "
                    f"'{ultima['estado']}'. Debe iniciar una nueva "
                    "postulación explícitamente antes de cargar o editar información."
                ),
            )

        # ========================================================
        # ESTADO NO CONTEMPLADO
        # ========================================================

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "La postulación se encuentra en un estado "
                f"no permitido: '{ultima['estado']}'."
            ),
        )

    # ========================================================
    # NUEVA POSTULACIÓN DESPUÉS DE RECHAZO/CANCELACIÓN
    # ========================================================
    async def crear_nueva_postulacion(self, id_usuario: UUID):
        result = await self.db.execute(
            text("""
                SELECT id_postulacion, estado
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {"id_usuario": id_usuario},
        )
        ultima = result.mappings().first()
        # Solo un rechazo o una cancelación habilitan una nueva postulación.
        # En estado Correcciones se reutiliza la MISMA postulación, por lo que
        # no debe permitirse crear otra (dejaría huérfana la que debe
        # corregirse, con sus documentos rechazados).
        if ultima and ultima["estado"] not in ("Rechazado", "Cancelado"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo puede iniciar una nueva postulación cuando la "
                    "anterior esté Rechazada o Cancelada."
                ),
            )

        result = await self.db.execute(
            text("""
                INSERT INTO postulacion_auditor (
                    id_usuario, estado, observaciones_tecnicas,
                    fecha_postulacion, fecha_revision
                ) VALUES (
                    :id_usuario, 'Borrador', '', CURRENT_TIMESTAMP, NULL
                )
                RETURNING id_postulacion, id_usuario, estado,
                          fecha_postulacion, fecha_revision,
                          observaciones_tecnicas
            """),
            {"id_usuario": id_usuario},
        )
        nueva = result.mappings().first()
        if not nueva:
            await self.db.rollback()
            raise HTTPException(500, "No fue posible crear la nueva postulación.")

        await self.db.execute(
            text("""
                UPDATE usuario
                SET estado_auditor = 'Postulante'
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )
        await self.db.commit()
        return {"mensaje": "Nueva postulación creada.", **dict(nueva)}

    # ========================================================
    # TÍTULOS ACADÉMICOS
    # ========================================================
    async def listar_titulos_academicos(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_titulo, nivel, titulo, institucion, fecha_grado,
                   estado_validacion, observacion_validacion
            FROM titulo_academico
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_grado DESC NULLS LAST, created_at DESC
        """), {"id_usuario": id_usuario})
        return [dict(x) for x in result.mappings().all()]

    async def crear_titulo_academico(self, id_usuario: UUID, data: TituloAcademicoCrear):
        await self._verificar_usuario_borrador(id_usuario)
        id_postulacion = await self._obtener_postulacion_activa(id_usuario)
        result = await self.db.execute(text("""
            INSERT INTO titulo_academico
                (id_usuario, nivel, titulo, institucion, fecha_grado, id_postulacion)
            VALUES
                (:id_usuario, :nivel, :titulo, :institucion, :fecha_grado, :id_postulacion)
            RETURNING id_titulo, nivel, titulo, institucion, fecha_grado,
                      estado_validacion, observacion_validacion
        """), {"id_usuario": id_usuario, "id_postulacion": id_postulacion, **data.model_dump()})
        row = result.mappings().first()
        await self.db.commit()
        return dict(row)

    async def eliminar_titulo_academico(self, id_usuario: UUID, id_titulo: UUID):
        await self._verificar_usuario_borrador(id_usuario)
        result = await self.db.execute(text("""
            DELETE FROM titulo_academico
            WHERE id_titulo = :id_titulo AND id_usuario = :id_usuario
              AND estado_validacion <> 'Aprobado'
            RETURNING id_titulo
        """), {"id_titulo": id_titulo, "id_usuario": id_usuario})
        row = result.mappings().first()
        if not row:
            raise HTTPException(409, "El título no existe o ya está aprobado.")
        await self.db.commit()
        return {"mensaje": "Título eliminado correctamente."}

    # ========================================================
    # EXPERIENCIA LABORAL
    # ========================================================
    async def listar_experiencias_laborales(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_experiencia, empresa, cargo, fecha_inicio, fecha_fin,
                   descripcion, estado_validacion, observacion_validacion
            FROM experiencia_laboral
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_inicio DESC
        """), {"id_usuario": id_usuario})
        return [dict(x) for x in result.mappings().all()]

    async def crear_experiencia_laboral(self, id_usuario: UUID, data: ExperienciaLaboralCrear):
        await self._verificar_usuario_borrador(id_usuario)
        id_postulacion = await self._obtener_postulacion_activa(id_usuario)
        result = await self.db.execute(text("""
            INSERT INTO experiencia_laboral
                (id_usuario, empresa, cargo, fecha_inicio, fecha_fin, descripcion, id_postulacion)
            VALUES
                (:id_usuario, :empresa, :cargo, :fecha_inicio, :fecha_fin, :descripcion, :id_postulacion)
            RETURNING id_experiencia, empresa, cargo, fecha_inicio, fecha_fin,
                      descripcion, estado_validacion, observacion_validacion
        """), {"id_usuario": id_usuario, "id_postulacion": id_postulacion, **data.model_dump()})
        row = result.mappings().first()
        await self.db.commit()
        return dict(row)

    async def eliminar_experiencia_laboral(self, id_usuario: UUID, id_experiencia: UUID):
        await self._verificar_usuario_borrador(id_usuario)
        result = await self.db.execute(text("""
            DELETE FROM experiencia_laboral
            WHERE id_experiencia = :id_experiencia AND id_usuario = :id_usuario
              AND estado_validacion <> 'Aprobado'
            RETURNING id_experiencia
        """), {"id_experiencia": id_experiencia, "id_usuario": id_usuario})
        if not result.mappings().first():
            raise HTTPException(409, "La experiencia no existe o ya está aprobada.")
        await self.db.commit()
        return {"mensaje": "Experiencia laboral eliminada correctamente."}

    # ========================================================
    # EXPERIENCIA EN AUDITORÍA
    # ========================================================
    async def listar_experiencias_auditoria(self, id_usuario: UUID):
        result = await self.db.execute(text("""
            SELECT id_experiencia, organizacion, rol_auditoria, tipo_auditoria,
                   fecha_inicio, fecha_fin, descripcion, estado_validacion,
                   observacion_validacion
            FROM experiencia_auditoria
            WHERE id_usuario = :id_usuario
            ORDER BY fecha_inicio DESC
        """), {"id_usuario": id_usuario})
        return [dict(x) for x in result.mappings().all()]

    async def crear_experiencia_auditoria(self, id_usuario: UUID, data: ExperienciaAuditoriaCrear):
        await self._verificar_usuario_borrador(id_usuario)
        id_postulacion = await self._obtener_postulacion_activa(id_usuario)
        result = await self.db.execute(text("""
            INSERT INTO experiencia_auditoria
                (id_usuario, organizacion, rol_auditoria, tipo_auditoria,
                 fecha_inicio, fecha_fin, descripcion, id_postulacion)
            VALUES
                (:id_usuario, :organizacion, :rol_auditoria, :tipo_auditoria,
                 :fecha_inicio, :fecha_fin, :descripcion, :id_postulacion)
            RETURNING id_experiencia, organizacion, rol_auditoria, tipo_auditoria,
                      fecha_inicio, fecha_fin, descripcion, estado_validacion,
                      observacion_validacion
        """), {"id_usuario": id_usuario, "id_postulacion": id_postulacion, **data.model_dump()})
        row = result.mappings().first()
        await self.db.commit()
        return dict(row)

    async def eliminar_experiencia_auditoria(self, id_usuario: UUID, id_experiencia: UUID):
        await self._verificar_usuario_borrador(id_usuario)
        result = await self.db.execute(text("""
            DELETE FROM experiencia_auditoria
            WHERE id_experiencia = :id_experiencia AND id_usuario = :id_usuario
              AND estado_validacion <> 'Aprobado'
            RETURNING id_experiencia
        """), {"id_experiencia": id_experiencia, "id_usuario": id_usuario})
        if not result.mappings().first():
            raise HTTPException(409, "La experiencia no existe o ya está aprobada.")
        await self.db.commit()
        return {"mensaje": "Experiencia en auditoría eliminada correctamente."}
