from uuid import UUID

from pydantic import BaseModel

from fastapi import (
    APIRouter,
    Depends,
    status,
    UploadFile,
    File,
    Query,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

from modules.auditores.auditor_schema import (
    IniciarRegistroAuditor,
    RegistroAuditorRespuesta,
    BorradorAuditorRespuesta,
    ConsultaEstadoAuditorRespuesta,
    EstadoAuditorRespuesta,
    PerfilAuditorCrear,
    CompetenciaAuditorCrear,
    ConflictoInteresCrear,
    EnviarSolicitudAuditor,
    EnviarSolicitudRespuesta,
)

from modules.auditores.auditor_service import AuditorService

router = APIRouter(
    prefix="/auditores",
    tags=["Auditores"],
)


class ReenviarCorreccionesRequest(BaseModel):
    """Datos mínimos para reenviar una postulación corregida."""

    id_usuario: UUID


# ============================================================
# INICIAR REGISTRO
# ============================================================

@router.post(
    "/registro/iniciar",
    response_model=RegistroAuditorRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def iniciar_registro_auditor(
    data: IniciarRegistroAuditor,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.iniciar_registro(data)


# ============================================================
# ESTADO POR CORREO
# ============================================================

@router.get(
    "/registro/estado",
    response_model=ConsultaEstadoAuditorRespuesta,
)
async def consultar_estado_auditor(
    correo: str,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.consultar_estado_por_correo(
        correo=correo
    )

# ============================================================
# OBTENER BORRADOR
#
# IMPORTANTE:
# El frontend actual utiliza el id_usuario.
# ============================================================

@router.get(
    "/registro/{id_usuario}",
    response_model=BorradorAuditorRespuesta,
)
async def obtener_borrador_auditor(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.obtener_borrador(id_usuario)


# ============================================================
# ESTADO POR POSTULACIÓN
# ============================================================

@router.get(
    "/registro/postulacion/{id_postulacion}/estado",
    response_model=EstadoAuditorRespuesta,
)
async def consultar_estado_auditor_por_id(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.consultar_estado(id_postulacion)
# comprobante para el pdf
@router.get(
    "/registro/postulacion/{id_postulacion}/comprobante",
)
async def descargar_comprobante_registro(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.generar_comprobante_pdf(
        id_postulacion
    )

# ============================================================
# DOCUMENTOS DE SOPORTE
# ============================================================

@router.get(
    "/registro/{id_usuario}/documentos",
)
async def listar_documentos_soporte(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.obtener_documentos(
        id_usuario,
    )


@router.post(
    "/registro/{id_usuario}/documento",
)
async def adjuntar_documento_soporte(
    id_usuario: UUID,
    tipo_documento: str = Query(...),
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.adjuntar_documento(
        id_usuario,
        tipo_documento,
        archivo,
    )


@router.put(
    "/registro/{id_usuario}/documento/{id_documento}",
)
async def reemplazar_documento_soporte(
    id_usuario: UUID,
    id_documento: UUID,
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.reemplazar_documento(
        id_usuario,
        id_documento,
        archivo,
    )


@router.delete(
    "/registro/{id_usuario}/documento/{id_documento}",
)
async def eliminar_documento_soporte(
    id_usuario: UUID,
    id_documento: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.eliminar_documento(
        id_usuario,
        id_documento,
    )


# ============================================================
# FOTO DE PERFIL
# ============================================================

@router.post(
    "/registro/{id_usuario}/perfil/foto",
)
async def subir_foto_perfil(
    id_usuario: UUID,
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)
    return await service.subir_foto_perfil(
        id_usuario,
        archivo,
    )


@router.delete(
    "/registro/{id_usuario}/perfil/foto",
)
async def eliminar_foto_perfil(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)
    return await service.eliminar_foto_perfil(id_usuario)


# ============================================================
# CONFLICTO - DECLARAR SIN CONFLICTO
# ============================================================

@router.delete(
    "/registro/{id_usuario}/conflictos",
)
async def declarar_sin_conflicto(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)
    return await service.declarar_sin_conflicto(id_usuario)


# ============================================================
# PERFIL
# ============================================================

@router.post(
    "/registro/{id_usuario}/perfil",
)
async def guardar_perfil(
    id_usuario: UUID,
    data: PerfilAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.guardar_perfil(
        id_usuario,
        data,
    )


@router.put(
    "/registro/{id_usuario}/perfil",
)
async def actualizar_perfil(
    id_usuario: UUID,
    data: PerfilAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.guardar_perfil(
        id_usuario,
        data,
    )


# ============================================================
# COMPETENCIAS
# ============================================================

@router.post(
    "/registro/{id_usuario}/competencias",
)
async def crear_competencia(
    id_usuario: UUID,
    data: CompetenciaAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.crear_competencia(
        id_usuario,
        data,
    )


@router.put(
    "/registro/{id_usuario}/competencias/{id_competencia}",
)
async def actualizar_competencia(
    id_usuario: UUID,
    id_competencia: UUID,
    data: CompetenciaAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.actualizar_competencia(
        id_usuario,
        id_competencia,
        data,
    )


# ============================================================
# CONFLICTOS
# ============================================================

@router.post(
    "/registro/{id_usuario}/conflictos",
)
async def crear_conflicto(
    id_usuario: UUID,
    data: ConflictoInteresCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.crear_conflicto(
        id_usuario,
        data,
    )


@router.put(
    "/registro/{id_usuario}/conflictos/{id_conflicto}",
)
async def actualizar_conflicto(
    id_usuario: UUID,
    id_conflicto: UUID,
    data: ConflictoInteresCrear,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.actualizar_conflicto(
        id_usuario,
        id_conflicto,
        data,
    )


# ============================================================
# ENVIAR FORMULARIO
# ============================================================

@router.post(
    "/registro/enviar",
    response_model=EnviarSolicitudRespuesta,
    status_code=status.HTTP_200_OK,
)
async def enviar_formulario_inscripcion(
    data: EnviarSolicitudAuditor,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.enviar_solicitud(
        data.id_usuario
    )


# ============================================================
# CATÁLOGO DE NORMAS
# ============================================================

@router.get("/catalogos/normas")
async def listar_normas(
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        text("""
            SELECT
                id_norma,
                nombre,
                version
            FROM norma
            ORDER BY nombre, version
        """)
    )

    return [
        {
            "id_norma": row["id_norma"],
            "nombre": row["nombre"],
            "version": row["version"],
        }
        for row in result.mappings().all()
    ]


# ============================================================
# CATÁLOGO DE EMPRESAS
# ============================================================

@router.get("/catalogos/empresas")
async def listar_empresas(
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(
        text("""
            SELECT
                id_empresa,
                nombre,
                nit
            FROM empresa
            ORDER BY nombre
        """)
    )

    return [
        {
            "id_empresa": row["id_empresa"],
            "nombre": row["nombre"],
            "nit": row["nit"],
        }
        for row in result.mappings().all()
    ]

# CANCELAR SOLICITUD
@router.post(
    "/registro/postulacion/{id_postulacion}/cancelar"
)
async def cancelar_solicitud_auditor(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)
    return await service.cancelar_solicitud(id_postulacion)

# ============================================================
# INICIAR REGISTRO
# ============================================================

@router.post(
    "/registro/iniciar",
    response_model=RegistroAuditorRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def iniciar_registro_auditor(
    data: IniciarRegistroAuditor,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.iniciar_registro(data)


# ============================================================
# REENVIAR POSTULACIÓN DESPUÉS DE CORRECCIONES
# ============================================================

@router.post(
    "/registro/{id_postulacion}/reenviar-correcciones",
)
async def reenviar_postulacion_correcciones(
    id_postulacion: UUID,
    data: ReenviarCorreccionesRequest,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.reenviar_postulacion_correcciones(
        id_postulacion=id_postulacion,
        id_usuario=data.id_usuario,
    )




# prueba
@router.get("/debug/check-tipo-competencia")
async def debug_check_tipo_competencia(
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        text("""
         SELECT
            conname,
            pg_get_constraintdef(oid) AS constraint_definition
        FROM pg_constraint
        WHERE conrelid = 'postulacion_auditor'::regclass
        AND contype = 'c';
        """)
    )

    return [dict(row) for row in result.mappings().all()]


@router.get("/diagnostico/{id_usuario}")
async def diagnostico_auditor(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        resultado_postulaciones = await db.execute(
            text("""
                SELECT
                    id_postulacion,
                    id_usuario,
                    estado,
                    fecha_postulacion
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
            """),
            {"id_usuario": id_usuario},
        )

        resultado_perfil = await db.execute(
            text("""
                SELECT *
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )

        resultado_competencias = await db.execute(
            text("""
                SELECT *
                FROM competencia_auditor
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )

        resultado_conflictos = await db.execute(
            text("""
                SELECT *
                FROM conflicto_interes
                WHERE id_usuario = :id_usuario
            """),
            {"id_usuario": id_usuario},
        )

        postulaciones = [
            dict(row)
            for row in resultado_postulaciones.mappings().all()
        ]

        perfil = [
            dict(row)
            for row in resultado_perfil.mappings().all()
        ]

        competencias = [
            dict(row)
            for row in resultado_competencias.mappings().all()
        ]

        conflictos = [
            dict(row)
            for row in resultado_conflictos.mappings().all()
        ]

        return {
            "id_usuario": str(id_usuario),
            "postulaciones": postulaciones,
            "perfil": perfil,
            "competencias": competencias,
            "conflictos": conflictos,
        }

    except Exception as e:
        return {
            "error": True,
            "detalle": str(e),
        }



# ============================================================
# ELIMINAR DATOS DE POSTULACIÓN CANCELADA
# ============================================================

@router.delete(
    "/registro/postulacion/{id_postulacion}/datos",
    status_code=status.HTTP_200_OK,
)
async def eliminar_datos_postulacion_cancelada(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    service = AuditorService(db)

    return await service.eliminar_datos_postulacion_cancelada(
        id_postulacion
    )