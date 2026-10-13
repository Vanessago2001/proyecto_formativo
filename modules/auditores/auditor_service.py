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
                    d.estado_revision
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
                    d.estado_revision
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
    ):
        await self._verificar_usuario_borrador(id_usuario)

        tipo_documento = tipo_documento.strip()

        tipos_permitidos = {
            "Hoja de Vida",
            "Título",
            "Certificado ISO",
            "Soporte",
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
                        estado_revision
                    )
                    VALUES (
                        :id_usuario,
                        :id_postulacion,
                        :nombre_archivo,
                        :tipo_documento,
                        :url_archivo,
                        CURRENT_TIMESTAMP,
                        'Pendiente'
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
                        estado_revision = 'Pendiente'
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
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El registro ya no se encuentra disponible "
                    "para edición."
                ),
            )

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
        await self._verificar_usuario_borrador(id_usuario)

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
        await self._verificar_usuario_borrador(id_usuario)

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

        await self._verificar_usuario_borrador(id_usuario)

        result = await self.db.execute(
            text("""
                SELECT id_perfil
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
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
                    WHERE id_usuario = :id_usuario
                """),
                {
                    "id_usuario": id_usuario,
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
                        calificacion_promedio
                    )
                    VALUES (
                        :id_usuario,
                        :foto_url,
                        :ciudad_residencia,
                        :departamento_residencia,
                        :modalidad_preferida,
                        :resumen_profesional,
                        0
                    )
                """),
                {
                    "id_usuario": id_usuario,
                    "foto_url": data.foto_url,
                    "ciudad_residencia": data.ciudad_residencia,
                    "departamento_residencia": data.departamento_residencia,
                    "modalidad_preferida": data.modalidad_preferida,
                    "resumen_profesional": data.resumen_profesional,
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
                    estado_validacion
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
                    'Pendiente'
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
            },
        )

        competencia = result.mappings().first()

        await self.db.commit()

        return {
            "id_competencia": competencia["id_competencia"],
            "mensaje": "Competencia registrada correctamente.",
        }

    # ========================================================
    # COMPETENCIA - ACTUALIZAR
    # ========================================================

    async def actualizar_competencia(
        self,
        id_usuario: UUID,
        id_competencia: UUID,
        data: CompetenciaAuditorCrear,
    ):

        await self._verificar_usuario_borrador(id_usuario)

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

        result = await self.db.execute(
            text("""
                INSERT INTO conflicto_interes (
                    id_usuario,
                    id_empresa,
                    tipo_conflicto,
                    descripcion,
                    bloquea_asignacion,
                    fecha_declaracion,
                    estado
                )
                VALUES (
                    :id_usuario,
                    :id_empresa,
                    :tipo_conflicto,
                    :descripcion,
                    :bloquea_asignacion,
                    CURRENT_TIMESTAMP,
                    'Activo'
                )
                RETURNING id_conflicto
            """),
            {
                "id_usuario": id_usuario,
                "id_empresa": data.id_empresa,
                "tipo_conflicto": data.tipo_conflicto,
                "descripcion": data.descripcion,
                "bloquea_asignacion": data.bloquea_asignacion,
            },
        )

        conflicto = result.mappings().first()

        await self.db.commit()

        return {
            "id_conflicto": conflicto["id_conflicto"],
            "mensaje": "Conflicto de interés registrado correctamente.",
        }

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

    async def consultar_estado_por_correo(
        self,
        correo: str,
    ):
        """
        Consulta el estado actual de la postulación del auditor
        mediante su correo.

        Si la postulación está en Correcciones, devuelve además
        la observación registrada por el administrador para esa
        postulación.

        IMPORTANTE:
        No crea ninguna postulación.
        No crea ningún borrador.
        Solo consulta información existente.
        """

        # ============================================================
        # BUSCAR USUARIO Y SU POSTULACIÓN MÁS RECIENTE
        # ============================================================

        result = await self.db.execute(
            text("""
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.correo,
                    u.estado AS estado_usuario,
                    u.estado_auditor,

                    pa.id_postulacion,
                    pa.estado AS estado_postulacion,
                    pa.fecha_postulacion,
                    pa.fecha_revision

                FROM usuario u

                LEFT JOIN LATERAL (
                    SELECT
                        p.id_postulacion,
                        p.estado,
                        p.fecha_postulacion,
                        p.fecha_revision

                    FROM postulacion_auditor p

                    WHERE p.id_usuario = u.id_usuario

                    ORDER BY
                        p.fecha_postulacion DESC

                    LIMIT 1
                ) pa
                    ON TRUE

                WHERE LOWER(TRIM(u.correo))
                    = LOWER(TRIM(:correo))

                LIMIT 1
            """),
            {
                "correo": correo,
            },
        )

        auditor = result.mappings().first()

        # ============================================================
        # VALIDAR USUARIO
        # ============================================================

        if not auditor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró un usuario con ese correo.",
            )

        id_postulacion = auditor["id_postulacion"]

        # ============================================================
        # ÚLTIMA CORRECCIÓN DE ESTA POSTULACIÓN
        # ============================================================
        #
        # Solamente buscamos historial relacionado con ESTA
        # postulación.
        #
        # No buscamos por usuario únicamente porque un auditor
        # puede tener varias postulaciones históricas.
        # ============================================================

        correccion = None

        if id_postulacion:

            result = await self.db.execute(
                text("""
                    SELECT
                        h.id_historial,
                        h.id_postulacion,
                        h.id_usuario_auditor,
                        h.id_usuario_administrador,
                        h.estado_anterior,
                        h.estado_nuevo,
                        h.observaciones,
                        h.fecha_cambio,

                        admin.nombre AS administrador

                    FROM historial_postulacion_auditor h

                    LEFT JOIN usuario admin
                        ON admin.id_usuario =
                        h.id_usuario_administrador

                    WHERE h.id_postulacion = :id_postulacion

                    AND LOWER(h.estado_nuevo)
                        = LOWER('Correcciones')

                    ORDER BY
                        h.fecha_cambio DESC

                    LIMIT 1
                """),
                {
                    "id_postulacion": id_postulacion,
                },
            )

            correccion = result.mappings().first()

        # ============================================================
        # OBSERVACIÓN DE CORRECCIÓN
        # ============================================================

        observaciones_correccion = ""

        if correccion:
            observaciones_correccion = (
                correccion["observaciones"]
                or ""
            )

        # ============================================================
        # RESPUESTA
        # ============================================================

        return {
            "id_usuario": auditor["id_usuario"],
            "id_postulacion": auditor["id_postulacion"],

            "nombre": auditor["nombre"],
            "correo": auditor["correo"],

            "estado_usuario": auditor["estado_usuario"],
            "estado_auditor": auditor["estado_auditor"],

            "estado_postulacion": auditor["estado_postulacion"],

            "fecha_postulacion": (
                auditor["fecha_postulacion"]
            ),

            "fecha_revision": (
                auditor["fecha_revision"]
            ),

            # ========================================================
            # CORRECCIÓN
            # ========================================================

            "tiene_correcciones": (
                auditor["estado_postulacion"]
                == "Correcciones"
                and bool(observaciones_correccion)
            ),

            "observaciones_correccion": (
                observaciones_correccion
            ),

            "administrador_correccion": (
                correccion["administrador"]
                if correccion
                else None
            ),

            "fecha_correccion": (
                correccion["fecha_cambio"]
                if correccion
                else None
            ),

            "estado_anterior_correccion": (
                correccion["estado_anterior"]
                if correccion
                else None
            ),
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
                        "No fue posible crear el nuevo borrador."
                    ),
                )

            return postulacion

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