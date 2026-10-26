from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
    UploadFile,
    File,
    Form,
    Query,
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logger import logger
from core.security import get_current_user
from modules.auth.dependencies import es_rol_administrativo

from modules.auditores.auditor_schema import (
    IniciarRegistroAuditor,
    RegistroAuditorRespuesta,
    BorradorAuditorRespuesta,
    EstadoAuditorRespuesta,
    PerfilAuditorCrear,
    CompetenciaAuditorCrear,
    ConflictoInteresCrear,
    EnviarSolicitudAuditor,
    EnviarSolicitudRespuesta,
    TituloAcademicoCrear,
    ExperienciaLaboralCrear,
    ExperienciaAuditoriaCrear,
    NuevaPostulacionRequest,
    ReenviarCorreccionesRequest,
)

from modules.auditores.auditor_service import AuditorService


async def require_auditor_access(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if es_rol_administrativo(current_user):
        return current_user

    id_usuario = request.path_params.get("id_usuario")
    if id_usuario is not None and str(id_usuario) != str(current_user["id_usuario"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para acceder a los datos de otro usuario.",
        )

    id_postulacion = request.path_params.get("id_postulacion")
    if id_postulacion is not None:
        resultado = await db.execute(
            text("""
                SELECT 1
                FROM postulacion_auditor
                WHERE id_postulacion = :id_postulacion
                  AND id_usuario = :id_usuario
                LIMIT 1
            """),
            {
                "id_postulacion": id_postulacion,
                "id_usuario": current_user["id_usuario"],
            },
        )
        if resultado.first() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para acceder a esta postulación.",
            )

    return current_user


# Rutas abiertas: registro inicial, consulta de estado y catálogos de referencia.
public_router = APIRouter(
    prefix="/auditores",
    tags=["Auditores"],
)

router = APIRouter(
    prefix="/auditores",
    tags=["Auditores"],
    dependencies=[Depends(require_auditor_access)],
)


# ============================================================
# INICIAR REGISTRO
# ============================================================

@public_router.post(
    "/registro/iniciar",
    response_model=RegistroAuditorRespuesta,
    status_code=status.HTTP_201_CREATED,
)
async def iniciar_registro_auditor(
    data: IniciarRegistroAuditor,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).iniciar_registro(data)

# ============================================================
# CONSULTAR ESTADO POR CORREO
# ============================================================

@public_router.get("/registro/estado")
async def consultar_estado_auditor(
    correo: str,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).consultar_estado_por_correo(
        correo=correo
    )



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
    return await AuditorService(db).consultar_estado(
        id_postulacion
    )


# ============================================================
# COMPROBANTE PDF
# ============================================================

@router.get(
    "/registro/postulacion/{id_postulacion}/comprobante",
)
async def descargar_comprobante_registro(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).generar_comprobante_pdf(
        id_postulacion
    )


# ============================================================
# DOCUMENTOS
# ============================================================

@router.get(
    "/registro/{id_usuario}/documentos",
)
async def listar_documentos_soporte(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).obtener_documentos(
        id_usuario
    )


@router.post(
    "/registro/{id_usuario}/documento",
)
async def adjuntar_documento_soporte(
    id_usuario: UUID,
    tipo_documento: str = Query(...),
    categoria_documento: str = Query("Soporte"),
    id_titulo: UUID | None = Query(None),
    id_experiencia_laboral: UUID | None = Query(None),
    id_experiencia_auditoria: UUID | None = Query(None),
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).adjuntar_documento(
        id_usuario=id_usuario,
        tipo_documento=tipo_documento,
        archivo=archivo,
        categoria_documento=categoria_documento,
        id_titulo=id_titulo,
        id_experiencia_laboral=id_experiencia_laboral,
        id_experiencia_auditoria=id_experiencia_auditoria,
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
    return await AuditorService(db).reemplazar_documento(
        id_usuario=id_usuario,
        id_documento=id_documento,
        archivo=archivo,
    )


@router.delete(
    "/registro/{id_usuario}/documento/{id_documento}",
)
async def eliminar_documento_soporte(
    id_usuario: UUID,
    id_documento: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_documento(
        id_usuario=id_usuario,
        id_documento=id_documento,
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
    return await AuditorService(db).subir_foto_perfil(
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
    return await AuditorService(db).eliminar_foto_perfil(
        id_usuario
    )


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
    return await AuditorService(db).guardar_perfil(
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
    return await AuditorService(db).guardar_perfil(
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
    return await AuditorService(db).crear_competencia(
        id_usuario,
        data,
    )



@router.delete(
    "/registro/{id_usuario}/competencias/{id_competencia}",
)
async def eliminar_competencia(
    id_usuario: UUID,
    id_competencia: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_competencia(
        id_usuario,
        id_competencia,
    )


# ============================================================
# NOTIFICACIONES DE AGENDA (bandeja del auditor)
# ============================================================

@router.get(
    "/{id_usuario}/notificaciones",
)
async def listar_notificaciones_auditor(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            SELECT
                id_notificacion,
                NULL::uuid AS id_programacion,
                asunto AS titulo,
                mensaje,
                leida,
                fecha_envio::timestamp AS fecha_creacion
            FROM notificacion
            WHERE id_usuario = :id_usuario

            UNION ALL

            SELECT
                id_notificacion,
                id_programacion,
                titulo,
                mensaje,
                leida,
                fecha_creacion
            FROM notificacion_agenda_auditor
            WHERE id_usuario = :id_usuario

            ORDER BY fecha_creacion DESC
        """),
        {"id_usuario": id_usuario},
    )
    return {
        "notificaciones": [
            dict(row) for row in result.mappings().all()
        ]
    }


@router.patch(
    "/{id_usuario}/notificaciones/{id_notificacion}/leer",
)
async def marcar_notificacion_leida(
    id_usuario: UUID,
    id_notificacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            UPDATE notificacion
            SET leida = TRUE,
                fecha_lectura = CURRENT_TIMESTAMP
            WHERE id_notificacion = :id_notificacion
              AND id_usuario = :id_usuario
            RETURNING id_notificacion
        """),
        {
            "id_notificacion": id_notificacion,
            "id_usuario": id_usuario,
        },
    )
    row = result.mappings().first()
    if not row:
        result = await db.execute(
            text("""
                UPDATE notificacion_agenda_auditor
                SET leida = TRUE
                WHERE id_notificacion = :id_notificacion
                  AND id_usuario = :id_usuario
                RETURNING id_notificacion
            """),
            {
                "id_notificacion": id_notificacion,
                "id_usuario": id_usuario,
            },
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada.")
    await db.commit()
    return {"mensaje": "Notificacion marcada como leida."}


@router.patch(
    "/{id_usuario}/notificaciones/{id_notificacion}/no-leida",
)
async def marcar_notificacion_no_leida(
    id_usuario: UUID,
    id_notificacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            UPDATE notificacion
            SET leida = FALSE,
                fecha_lectura = NULL
            WHERE id_notificacion = :id_notificacion
              AND id_usuario = :id_usuario
            RETURNING id_notificacion
        """),
        {
            "id_notificacion": id_notificacion,
            "id_usuario": id_usuario,
        },
    )
    row = result.mappings().first()
    if not row:
        result = await db.execute(
            text("""
                UPDATE notificacion_agenda_auditor
                SET leida = FALSE
                WHERE id_notificacion = :id_notificacion
                  AND id_usuario = :id_usuario
                RETURNING id_notificacion
            """),
            {
                "id_notificacion": id_notificacion,
                "id_usuario": id_usuario,
            },
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada.")
    await db.commit()
    return {"mensaje": "Notificacion marcada como no leida."}


@router.delete(
    "/{id_usuario}/notificaciones/{id_notificacion}",
)
async def eliminar_notificacion_auditor(
    id_usuario: UUID,
    id_notificacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            DELETE FROM notificacion
            WHERE id_notificacion = :id_notificacion
              AND id_usuario = :id_usuario
            RETURNING id_notificacion
        """),
        {
            "id_notificacion": id_notificacion,
            "id_usuario": id_usuario,
        },
    )
    row = result.mappings().first()
    if not row:
        result = await db.execute(
            text("""
                DELETE FROM notificacion_agenda_auditor
                WHERE id_notificacion = :id_notificacion
                  AND id_usuario = :id_usuario
                RETURNING id_notificacion
            """),
            {
                "id_notificacion": id_notificacion,
                "id_usuario": id_usuario,
            },
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Notificacion no encontrada.")
    await db.commit()
    return {"mensaje": "Notificacion eliminada.", "eliminadas": 1}


@router.post(
    "/{id_usuario}/notificaciones/eliminar",
)
async def eliminar_notificaciones_seleccionadas(
    id_usuario: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Debe indicar las notificaciones a eliminar.")

    result1 = await db.execute(
        text("""
            DELETE FROM notificacion
            WHERE id_usuario = :id_usuario
              AND id_notificacion = ANY(:ids)
            RETURNING id_notificacion
        """),
        {"id_usuario": id_usuario, "ids": ids},
    )
    eliminadas1 = len(result1.mappings().all())

    result2 = await db.execute(
        text("""
            DELETE FROM notificacion_agenda_auditor
            WHERE id_usuario = :id_usuario
              AND id_notificacion = ANY(:ids)
            RETURNING id_notificacion
        """),
        {"id_usuario": id_usuario, "ids": ids},
    )
    eliminadas2 = len(result2.mappings().all())

    await db.commit()
    return {"mensaje": "Notificaciones eliminadas.", "eliminadas": eliminadas1 + eliminadas2}


@router.delete(
    "/{id_usuario}/notificaciones",
)
async def eliminar_notificaciones_leidas(
    id_usuario: UUID,
    solo_leidas: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    condicion = "AND leida = TRUE" if solo_leidas else ""

    result1 = await db.execute(
        text(f"""
            DELETE FROM notificacion
            WHERE id_usuario = :id_usuario
              {condicion}
            RETURNING id_notificacion
        """),
        {"id_usuario": id_usuario},
    )
    eliminadas1 = len(result1.mappings().all())

    result2 = await db.execute(
        text(f"""
            DELETE FROM notificacion_agenda_auditor
            WHERE id_usuario = :id_usuario
              {condicion}
            RETURNING id_notificacion
        """),
        {"id_usuario": id_usuario},
    )
    eliminadas2 = len(result2.mappings().all())

    await db.commit()
    return {"mensaje": "Notificaciones eliminadas.", "eliminadas": eliminadas1 + eliminadas2}


@router.patch(
    "/{id_usuario}/notificaciones/marcar-todas-leidas",
)
async def marcar_todas_notificaciones_leidas(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("""
            UPDATE notificacion
            SET leida = TRUE,
                fecha_lectura = CURRENT_TIMESTAMP
            WHERE id_usuario = :id_usuario
              AND leida = FALSE
        """),
        {"id_usuario": id_usuario},
    )
    await db.execute(
        text("""
            UPDATE notificacion_agenda_auditor
            SET leida = TRUE
            WHERE id_usuario = :id_usuario
              AND leida = FALSE
        """),
        {"id_usuario": id_usuario},
    )
    await db.commit()
    return {"mensaje": "Todas las notificaciones fueron marcadas como leidas."}


@router.get(
    "/registro/historial-academico/{id_usuario}",
)
async def consultar_historial_academico(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).consultar_historial_academico(id_usuario)

@router.post(
    "/registro/{id_usuario}/competencias/curso-complementario",
)
async def registrar_curso_complementario(
    id_usuario: UUID,
    data: CompetenciaAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).registrar_curso_complementario(
        id_usuario=id_usuario,
        data=data,
    )

@router.post(
    "/registro/{id_usuario}/competencias/certificacion",
)
async def registrar_certificacion(
    id_usuario: UUID,
    data: CompetenciaAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).registrar_certificacion(
        id_usuario=id_usuario,
        data=data,
    )


# ============================================================
# CERTIFICACIONES VIGENTES (TIPO + ARCHIVO)
# ============================================================

@router.get(
    "/registro/{id_usuario}/certificaciones",
)
async def listar_certificaciones_vigentes(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return {
        "certificaciones":
            await AuditorService(db).listar_certificaciones_vigentes(
                id_usuario
            )
    }


@router.post(
    "/registro/{id_usuario}/certificaciones",
)
async def registrar_certificacion_vigente(
    id_usuario: UUID,
    id_norma: UUID = Form(...),
    descripcion: str = Form(""),
    archivo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).registrar_certificacion_vigente(
        id_usuario=id_usuario,
        id_norma=id_norma,
        archivo=archivo,
        descripcion=descripcion,
    )


@router.delete(
    "/registro/{id_usuario}/certificaciones/{id_certificacion}",
)
async def eliminar_certificacion_vigente(
    id_usuario: UUID,
    id_certificacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_certificacion_vigente(
        id_usuario=id_usuario,
        id_certificacion=id_certificacion,
    )


@router.get(
    "/registro/conflictos/{id_usuario}",
)
async def listar_conflictos(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return {
        "conflictos":
            await AuditorService(db).listar_conflictos(id_usuario)
    }

@router.delete(
    "/registro/conflictos/{id_conflicto}",
)
async def eliminar_conflicto(
    id_conflicto: UUID,
    id_usuario: UUID,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (
        not es_rol_administrativo(usuario)
        and str(id_usuario) != str(usuario["id_usuario"])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para eliminar conflictos de otro usuario.",
        )

    return await AuditorService(db).eliminar_conflicto(
        id_usuario=id_usuario,
        id_conflicto=id_conflicto,
    )

@router.get(
    "/registro/empresas-restringidas",
)
async def consultar_empresas_restringidas(
    db: AsyncSession = Depends(get_db),
):
    return {
        "empresas":
            await AuditorService(db).consultar_empresas_restringidas()
    }

@router.post(
    "/registro/validar-conflicto",
)
async def validar_conflicto_antes_asignacion(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).validar_conflicto_antes_asignacion(
        id_usuario=UUID(str(data.get("id_usuario"))),
        id_empresa=UUID(str(data.get("id_empresa"))),
    )

@public_router.get(
    "/registro/catalogo-competencias",
)
async def consultar_catalogo_competencias(
    db: AsyncSession = Depends(get_db),
):
    return {
        "catalogo": await AuditorService(db).consultar_catalogo_competencias()
    }

@public_router.get(
    "/registro/sectores-iaf",
)
async def consultar_sectores_iaf(
    db: AsyncSession = Depends(get_db),
):
    return {
        "sectores": await AuditorService(db).consultar_sectores_iaf()
    }

@router.put(
    "/registro/{id_usuario}/competencias/{id_competencia}",
)
async def actualizar_competencia(
    id_usuario: UUID,
    id_competencia: UUID,
    data: CompetenciaAuditorCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).actualizar_competencia(
        id_usuario,
        id_competencia,
        data,
    )


# ============================================================
# CONFLICTOS
# ============================================================

@router.delete(
    "/registro/{id_usuario}/conflictos",
)
async def declarar_sin_conflicto(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).declarar_sin_conflicto(
        id_usuario
    )


@router.post(
    "/registro/{id_usuario}/conflictos",
)
async def crear_conflicto(
    id_usuario: UUID,
    data: ConflictoInteresCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_conflicto(
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
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (
        not es_rol_administrativo(usuario)
        and str(id_usuario) != str(usuario["id_usuario"])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para actualizar conflictos de otro usuario.",
        )

    return await AuditorService(db).actualizar_conflicto(
        id_usuario,
        id_conflicto,
        data,
    )


# ============================================================
# TÍTULOS ACADÉMICOS - MÚLTIPLES
# ============================================================

@router.get(
    "/registro/{id_usuario}/titulos",
)
async def listar_titulos(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).listar_titulos_academicos(
        id_usuario
    )


@router.post(
    "/registro/{id_usuario}/titulos",
)
async def crear_titulo(
    id_usuario: UUID,
    data: TituloAcademicoCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_titulo_academico(
        id_usuario,
        data,
    )


@router.delete(
    "/registro/{id_usuario}/titulos/{id_titulo}",
)
async def eliminar_titulo(
    id_usuario: UUID,
    id_titulo: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_titulo_academico(
        id_usuario,
        id_titulo,
    )


# ============================================================
# EXPERIENCIA LABORAL - MÚLTIPLE
# ============================================================

@router.get(
    "/registro/{id_usuario}/experiencias-laborales",
)
async def listar_experiencias_laborales(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).listar_experiencias_laborales(
        id_usuario
    )


@router.post(
    "/registro/{id_usuario}/experiencias-laborales",
)
async def crear_experiencia_laboral(
    id_usuario: UUID,
    data: ExperienciaLaboralCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_experiencia_laboral(
        id_usuario,
        data,
    )


@router.delete(
    "/registro/{id_usuario}/experiencias-laborales/{id_experiencia}",
)
async def eliminar_experiencia_laboral(
    id_usuario: UUID,
    id_experiencia: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_experiencia_laboral(
        id_usuario,
        id_experiencia,
    )


# ============================================================
# EXPERIENCIA EN AUDITORÍA - MÚLTIPLE
# ============================================================

@router.get(
    "/registro/{id_usuario}/experiencias-auditoria",
)
async def listar_experiencias_auditoria(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).listar_experiencias_auditoria(
        id_usuario
    )


@router.post(
    "/registro/{id_usuario}/experiencias-auditoria",
)
async def crear_experiencia_auditoria(
    id_usuario: UUID,
    data: ExperienciaAuditoriaCrear,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_experiencia_auditoria(
        id_usuario,
        data,
    )


@router.delete(
    "/registro/{id_usuario}/experiencias-auditoria/{id_experiencia}",
)
async def eliminar_experiencia_auditoria(
    id_usuario: UUID,
    id_experiencia: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_experiencia_auditoria(
        id_usuario,
        id_experiencia,
    )


# ============================================================
# ENVIAR FORMULARIO
# ============================================================

@router.post(
    "/registro/enviar",
    response_model=EnviarSolicitudRespuesta,
)
async def enviar_formulario_inscripcion(
    data: EnviarSolicitudAuditor,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (
        not es_rol_administrativo(usuario)
        and str(data.id_usuario) != str(usuario["id_usuario"])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para enviar la postulación de otro usuario.",
        )

    return await AuditorService(db).enviar_solicitud(
        data.id_usuario
    )


# ============================================================
# REENVIAR CORRECCIONES
# ============================================================

@router.post(
    "/registro/{id_postulacion}/reenviar-correcciones",
)
async def reenviar_postulacion_correcciones(
    id_postulacion: UUID,
    data: ReenviarCorreccionesRequest,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).reenviar_postulacion_correcciones(
        id_postulacion=id_postulacion,
        id_usuario=data.id_usuario,
    )


# ============================================================
# CREAR NUEVA POSTULACIÓN
#
# SOLO DESPUÉS DE RECHAZADO/CANCELADO
# ============================================================

@router.post(
    "/registro/nueva-postulacion",
)
async def crear_nueva_postulacion(
    data: NuevaPostulacionRequest,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if (
        not es_rol_administrativo(usuario)
        and str(data.id_usuario) != str(usuario["id_usuario"])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para crear una postulación de otro usuario.",
        )

    return await AuditorService(db).crear_nueva_postulacion(
        data.id_usuario
    )


# ============================================================
# CANCELAR POSTULACIÓN
# ============================================================

@router.post(
    "/registro/postulacion/{id_postulacion}/cancelar",
)
async def cancelar_solicitud_auditor(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).cancelar_solicitud(
        id_postulacion
    )


# ============================================================
# ELIMINAR DATOS DE POSTULACIÓN CANCELADA
# ============================================================

@router.delete(
    "/registro/postulacion/{id_postulacion}/datos",
)
async def eliminar_datos_postulacion_cancelada(
    id_postulacion: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_datos_postulacion_cancelada(
        id_postulacion
    )


# ============================================================
# CATÁLOGO DE NORMAS
# ============================================================

@public_router.get(
    "/catalogos/normas",
)
async def listar_normas(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            SELECT
                n.id_norma,
                n.nombre,
                n.version,
                (
                    SELECT STRING_AGG(DISTINCT c.codigo_sector_iaf, ', ' ORDER BY c.codigo_sector_iaf)
                    FROM competencia_auditor c
                    WHERE c.id_norma = n.id_norma
                      AND c.codigo_sector_iaf IS NOT NULL
                      AND TRIM(c.codigo_sector_iaf) <> ''
                ) AS codigo_sector_iaf
            FROM norma n
            ORDER BY n.nombre, n.version
        """)
    )

    return [
        {
            "id_norma": row["id_norma"],
            "nombre": row["nombre"],
            "version": row["version"],
            "codigo_sector_iaf": row["codigo_sector_iaf"],
        }
        for row in result.mappings().all()
    ]


# ============================================================
# CATÁLOGO DE EMPRESAS
# ============================================================

@public_router.get(
    "/catalogos/empresas",
)
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


# ============================================================
# DIAGNÓSTICO
# ============================================================

@router.get(
    "/diagnostico/{id_usuario}",
)
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
                    fecha_postulacion,
                    fecha_revision,
                    observaciones_tecnicas
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                ORDER BY fecha_postulacion DESC
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        resultado_perfil = await db.execute(
            text("""
                SELECT *
                FROM perfil_auditor
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        resultado_competencias = await db.execute(
            text("""
                SELECT *
                FROM competencia_auditor
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
        )

        resultado_conflictos = await db.execute(
            text("""
                SELECT *
                FROM conflicto_interes
                WHERE id_usuario = :id_usuario
            """),
            {
                "id_usuario": id_usuario,
            },
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

    except Exception:
        logger.exception(
            "Error generando el diagnóstico del auditor %s",
            id_usuario,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No fue posible generar el diagnóstico.",
        )


# ============================================================
# OBTENER BORRADOR / REGISTRO
# Va al final para que las rutas literales /registro/... tengan
# prioridad sobre este parámetro dinámico.
# ============================================================

@router.get(
    "/registro/{id_usuario}",
    response_model=BorradorAuditorRespuesta,
)
async def obtener_borrador_auditor(
    id_usuario: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).obtener_borrador(
        id_usuario
    )