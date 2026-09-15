from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import hash_password

from modules.auditores.auditor_schema import (
    IniciarRegistroAuditor,
    PerfilAuditorCrear,
    CompetenciaAuditorCrear,
    ConflictoInteresCrear,
)


class AuditorService:

    def __init__(self, db: AsyncSession):
        self.db = db

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
    # OBTENER BORRADOR
    # ========================================================

    async def obtener_borrador(self, id_usuario: UUID):

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

        # ----------------------------------------------------
        # Perfil
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Competencias
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

        # ----------------------------------------------------
        # Conflictos
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Documentos ya enviados
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT
                    id_documento,
                    nombre_archivo,
                    tipo_documento,
                    url_archivo
                FROM documento_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_subida DESC
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        documentos = result.mappings().all()

        return {
            "id_usuario": usuario["id_usuario"],
            "estado": usuario["estado"],
            "estado_auditor": usuario["estado_auditor"],
            "nombre": usuario["nombre"],
            "tipo_doc": usuario["tipo_doc"],
            "num_doc": usuario["num_doc"],
            "correo": usuario["correo"],
            "perfil": dict(perfil) if perfil else None,
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

    # ========================================================
    # ENVIAR SOLICITUD
    # ========================================================

    async def enviar_solicitud(
        self,
        id_usuario: UUID,
        documento_url_soporte: str,
    ):

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

        if usuario["estado_auditor"] == "APROBADO":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El auditor ya se encuentra aprobado.",
            )

        # ----------------------------------------------------
        # Verificar que no exista postulación
        # ----------------------------------------------------

        result = await self.db.execute(
            text("""
                SELECT id_postulacion
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        if result.mappings().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El auditor ya tiene una postulación registrada.",
            )

        # ----------------------------------------------------
        # Crear postulación
        # ----------------------------------------------------

        ahora = datetime.utcnow()

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
                    'Enviado',
                    '',
                    :fecha_postulacion,
                    :fecha_revision
                )
                RETURNING id_postulacion
            """),
            {
                "id_usuario": id_usuario,
                "fecha_postulacion": ahora,
                "fecha_revision": ahora,
            },
        )

        postulacion = result.mappings().first()

        if not postulacion:
            await self.db.rollback()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No fue posible crear la postulación.",
            )

        id_postulacion = postulacion["id_postulacion"]

        # ----------------------------------------------------
        # Guardar documento soporte
        # ----------------------------------------------------

        await self.db.execute(
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
                    'Documentos soporte de inscripción',
                    'Soporte',
                    :url_archivo,
                    CURRENT_TIMESTAMP,
                    'Pendiente'
                )
            """),
            {
                "id_usuario": id_usuario,
                "id_postulacion": id_postulacion,
                "url_archivo": documento_url_soporte,
            },
        )

        # ----------------------------------------------------
        # Cambiar estado_auditor
        #
        # NO tocamos usuario.estado
        # ----------------------------------------------------

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

        await self.db.commit()

        return {
            "id_usuario": id_usuario,
            "id_postulacion": id_postulacion,
            "estado": "Pendiente",
            "estado_auditor": "PENDIENTE",
            "mensaje": (
                "Formulario de inscripción enviado correctamente. "
                "La solicitud quedó pendiente de revisión."
            ),
            "faltantes": [],
        }

    # ========================================================
    # CONSULTAR ESTADO
    # ========================================================

    async def consultar_estado_por_correo(
        self,
        correo: str,
    ):

        result = await self.db.execute(
            text("""
                SELECT
                    u.id_usuario,
                    u.nombre,
                    u.correo,
                    u.estado,
                    u.estado_auditor,
                    r.nombre AS rol,
                    pa.id_postulacion,
                    pa.estado AS estado_postulacion
                FROM usuario u
                LEFT JOIN rol r
                    ON r.id_rol = u.rol_id
                LEFT JOIN postulacion_auditor pa
                    ON pa.id_usuario = u.id_usuario
                WHERE LOWER(u.correo) = LOWER(:correo)
                ORDER BY pa.fecha_postulacion DESC NULLS LAST
                LIMIT 1
            """),
            {
                "correo": correo.strip(),
            },
        )

        auditor = result.mappings().first()

        if not auditor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró un auditor con ese correo.",
            )

        return {
            "id_usuario": auditor["id_usuario"],
            "id_postulacion": auditor["id_postulacion"],
            "nombre": auditor["nombre"],
            "correo": auditor["correo"],
            "estado": auditor["estado"],
            "estado_auditor": auditor["estado_auditor"],
            "estado_postulacion": auditor["estado_postulacion"],
            "rol": auditor["rol"],
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