from uuid import UUID

from fastapi import APIRouter, Depends, status
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

    return await service.consultar_estado_por_correo(correo)


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
        data.id_usuario,
        data.documento_url_soporte,
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
# prueba
@router.get("/debug/check-tipo-competencia")
async def debug_check_tipo_competencia(
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        text("""
         SELECT
            conname,
            pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conname = 'chk_estado_auditor';
        """)
    )

    return [dict(row) for row in result.mappings().all()]