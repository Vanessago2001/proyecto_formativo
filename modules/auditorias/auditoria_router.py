"""
M7 — AUDITORÍAS
Endpoints de los siete bloques (AUT-001 a AUT-070).

Varios permisos de la hoja describen partes de una misma pantalla: consultar
la empresa (AUT-003), sus sedes (AUT-004), el alcance (AUT-005), los procesos
(AUT-006) y el expediente previo (AUT-007) se resuelven en una sola respuesta,
y esa respuesta verifica los cinco permisos con `exigir_permisos`, igual que
hace M5 al registrar una sede.

Donde la hoja marca REQ y la acción cambia algo (AUT-010 suspender, AUT-014
registrar un requisito y AUT-057 cerrar), la acción no se ejecuta: queda
pendiente de aprobación y la respuesta es 202. Los otros REQ de la hoja solo
leen, así que se resuelven en el momento.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.auditorias import auditoria_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.auditorias.auditoria_permissions import (
    NivelPermiso,
    exigir_permisos,
    requiere_permiso,
)
from modules.auditorias.auditoria_schema import (
    AccionSeguimiento,
    AsociarEvidencia,
    CierreAuditoria,
    CierreHallazgo,
    ClasificacionHallazgo,
    ComentarioTecnico,
    ConfirmacionInicio,
    ContenidoInforme,
    EstadoAccion,
    EvaluacionRequisito,
    HallazgoEditado,
    HallazgoNuevo,
    IncidenciaJornada,
    InicioAuditoria,
    JornadaCierre,
    JornadaInicio,
    MejoraEvaluacion,
    MotivoAuditoria,
    ObservacionEvidencia,
    Observaciones,
    RequisitoControl,
    RequisitoRelacionado,
)
from modules.auditorias.auditoria_service import AuditoriaService
from modules.auditorias.evaluacion_service import (
    RESULTADO_CUMPLE,
    RESULTADO_NO_APLICA,
    RESULTADO_NO_CUMPLE,
    EvaluacionService,
)
from modules.auditorias.evidencia_service import EvidenciaService
from modules.auditorias.hallazgo_service import (
    TIPO_MEJORA,
    TIPO_NO_CONFORMIDAD,
    TIPO_OBSERVACION,
    HallazgoService,
)
from modules.auditorias.informe_service import InformeService
from modules.auditorias.seguimiento_service import (
    TIPO_CORRECTIVA,
    TIPO_SEGUIMIENTO,
    SeguimientoService,
)
from modules.solicitudes.sede_excel import TIPO_XLSX, generar_excel

router = APIRouter(prefix="/auditorias", tags=["M7 - Auditorías"])


def _requiere_aprobacion(usuario: dict) -> bool:
    """La hoja marcó REQ para el rol de quien pide la acción."""
    return usuario.get("permiso_nivel") == NivelPermiso.REQUIERE_APROBACION.value


async def _dejar_pendiente(
    db: AsyncSession, usuario: dict, codigo: str, id_auditoria: UUID, datos: dict, detalle: str
) -> JSONResponse:
    """
    Registra la acción como pendiente y responde 202 sin ejecutarla, igual
    que hacen M3 y M5 con sus permisos REQ.
    """
    auditoria = await AuditoriaService(db).obtener(id_auditoria)
    id_empresa = await _empresa_de(db, auditoria["id_solicitud"])
    aprobacion = await AprobacionService(db).solicitar(
        codigo, id_empresa, {**datos, "id_auditoria": str(id_auditoria)}, detalle, usuario
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder({
            "mensaje": "La acción requiere aprobación de un superior. Quedó registrada como pendiente.",
            "aprobacion": aprobacion,
        }),
    )


async def _empresa_de(db: AsyncSession, id_solicitud) -> str | None:
    from sqlalchemy import text

    resultado = await db.execute(
        text("SELECT id_empresa FROM solicitud WHERE id_solicitud = :id;"),
        {"id": str(id_solicitud)},
    )
    valor = resultado.scalar()
    return str(valor) if valor else None


# ============================================================
# BLOQUE 1 · EJECUCIÓN DE LA AUDITORÍA (AUT-001 a AUT-010)
# ============================================================

@router.post("", status_code=status.HTTP_201_CREATED, summary="AUT-001 · Iniciar auditoría de campo")
async def iniciar_auditoria(
    datos: InicioAuditoria,
    usuario: dict = Depends(requiere_permiso("AUT-001")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).iniciar(
        datos.id_solicitud, usuario, datos.id_programacion, datos.observaciones_iniciales
    )


@router.get("", summary="AUT-002 · Consultar las auditorías y su solicitud")
async def listar_auditorias(
    id_solicitud: Optional[UUID] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-002")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).listar(id_solicitud, estado)


@router.get(
    "/{id_auditoria}/expediente",
    summary="AUT-007 · Expediente previo (incluye AUT-003 a AUT-006)",
)
async def expediente_previo(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-007")),
    db: AsyncSession = Depends(get_db),
):
    """
    Una sola respuesta con la empresa (AUT-003), sus sedes (AUT-004), el
    alcance (AUT-005) y los procesos (AUT-006): se verifican los cuatro
    permisos además del de descarga del expediente.
    """
    exigir_permisos(usuario, "AUT-003", "AUT-004", "AUT-005", "AUT-006")
    return await AuditoriaService(db).expediente_previo(id_auditoria)


@router.post("/{id_auditoria}/inicio", summary="AUT-008 · Confirmar inicio formal")
async def confirmar_inicio(
    id_auditoria: UUID,
    datos: ConfirmacionInicio,
    usuario: dict = Depends(requiere_permiso("AUT-008")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).confirmar_inicio(id_auditoria, usuario, datos.hora_inicio)


@router.post(
    "/{id_auditoria}/observaciones-iniciales",
    summary="AUT-009 · Registrar observaciones iniciales",
)
async def observaciones_iniciales(
    id_auditoria: UUID,
    datos: Observaciones,
    usuario: dict = Depends(requiere_permiso("AUT-009")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).registrar_observaciones_iniciales(
        id_auditoria, datos.observaciones, usuario
    )


@router.post("/{id_auditoria}/suspender", summary="AUT-010 · Suspender auditoría por anomalía")
async def suspender_auditoria(
    id_auditoria: UUID,
    datos: MotivoAuditoria,
    usuario: dict = Depends(requiere_permiso("AUT-010")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "AUT-010", id_auditoria, {"motivo": datos.motivo},
            f"Suspender la auditoría por anomalía: {datos.motivo}",
        )
    return await AuditoriaService(db).suspender(id_auditoria, datos.motivo, usuario)


@router.post("/{id_auditoria}/reanudar", summary="AUT-010 · Reanudar una auditoría suspendida")
async def reanudar_auditoria(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-010")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).reanudar(id_auditoria, usuario)


# ============================================================
# BLOQUE 2 · EVALUACIÓN POR REQUISITO (AUT-011 a AUT-020)
# ============================================================

@router.get("/{id_auditoria}/requisitos", summary="AUT-014 · Requisitos de la norma y su evaluación")
async def listar_requisitos(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-014")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).requisitos_de_la_auditoria(id_auditoria)


@router.post(
    "/{id_auditoria}/requisitos",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-014 · Registrar un requisito de control",
)
async def registrar_requisito(
    id_auditoria: UUID,
    datos: RequisitoControl,
    usuario: dict = Depends(requiere_permiso("AUT-014")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "AUT-014", id_auditoria,
            {"numeral": datos.numeral, "descripcion": datos.descripcion},
            f"Registrar el requisito de control {datos.numeral}.",
        )
    return await EvaluacionService(db).registrar_requisito(
        id_auditoria, datos.numeral, datos.descripcion, usuario
    )


@router.post(
    "/{id_auditoria}/evaluaciones/{id_variable}",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-011 · Registrar evaluación por requisito",
)
async def registrar_evaluacion(
    id_auditoria: UUID,
    id_variable: UUID,
    datos: EvaluacionRequisito,
    usuario: dict = Depends(requiere_permiso("AUT-011")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).guardar(
        id_auditoria, id_variable, datos.resultado, usuario,
        datos.observacion, datos.comentario_tecnico, datos.definitiva,
    )


@router.put(
    "/{id_auditoria}/evaluaciones/{id_variable}",
    summary="AUT-012 · Editar la evaluación (autoguardado)",
)
async def editar_evaluacion(
    id_auditoria: UUID,
    id_variable: UUID,
    datos: EvaluacionRequisito,
    usuario: dict = Depends(requiere_permiso("AUT-012")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).guardar(
        id_auditoria, id_variable, datos.resultado, usuario,
        datos.observacion, datos.comentario_tecnico, datos.definitiva,
    )


@router.delete(
    "/{id_auditoria}/evaluaciones/{id_evaluacion}",
    summary="AUT-013 · Eliminar una evaluación pendiente",
)
async def eliminar_evaluacion(
    id_auditoria: UUID,
    id_evaluacion: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-013")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).eliminar(id_auditoria, id_evaluacion, usuario)


@router.post("/{id_auditoria}/evaluaciones/{id_variable}/cumple", summary="AUT-015 · Marcar 'Cumple'")
async def marcar_cumple(
    id_auditoria: UUID,
    id_variable: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-015")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).marcar(id_auditoria, id_variable, RESULTADO_CUMPLE, usuario)


@router.post("/{id_auditoria}/evaluaciones/{id_variable}/no-cumple", summary="AUT-016 · Marcar 'No Cumple'")
async def marcar_no_cumple(
    id_auditoria: UUID,
    id_variable: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-016")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).marcar(id_auditoria, id_variable, RESULTADO_NO_CUMPLE, usuario)


@router.post("/{id_auditoria}/evaluaciones/{id_variable}/no-aplica", summary="AUT-017 · Marcar 'No Aplica'")
async def marcar_no_aplica(
    id_auditoria: UUID,
    id_variable: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-017")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).marcar(id_auditoria, id_variable, RESULTADO_NO_APLICA, usuario)


@router.post(
    "/{id_auditoria}/evaluaciones/{id_evaluacion}/mejora",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-018 · Registrar una mejora (OFI)",
)
async def registrar_mejora(
    id_auditoria: UUID,
    id_evaluacion: UUID,
    datos: MejoraEvaluacion,
    usuario: dict = Depends(requiere_permiso("AUT-018")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).registrar_mejora(
        id_auditoria, id_evaluacion, datos.descripcion, usuario
    )


@router.post(
    "/{id_auditoria}/evaluaciones/{id_evaluacion}/comentario",
    summary="AUT-019 · Registrar comentario técnico",
)
async def registrar_comentario(
    id_auditoria: UUID,
    id_evaluacion: UUID,
    datos: ComentarioTecnico,
    usuario: dict = Depends(requiere_permiso("AUT-019")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).registrar_comentario(
        id_auditoria, id_evaluacion, datos.comentario, usuario
    )


@router.get("/{id_auditoria}/avance", summary="AUT-020 · Consultar la evaluación en tiempo real")
async def avance_evaluacion(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-020")),
    db: AsyncSession = Depends(get_db),
):
    return await EvaluacionService(db).avance(id_auditoria)


# ============================================================
# BLOQUE 3 · HALLAZGOS (AUT-021 a AUT-030)
# ============================================================

@router.post(
    "/{id_auditoria}/hallazgos",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-021 · Registrar hallazgo específico",
)
async def registrar_hallazgo(
    id_auditoria: UUID,
    datos: HallazgoNuevo,
    usuario: dict = Depends(requiere_permiso("AUT-021")),
    db: AsyncSession = Depends(get_db),
):
    """
    Según el tipo, la hoja lo llama no conformidad formal (AUT-025),
    observación formal (AUT-026) u oportunidad de mejora (AUT-027): se
    verifica el permiso del tipo que se está registrando.
    """
    por_tipo = {
        TIPO_NO_CONFORMIDAD: "AUT-025",
        TIPO_OBSERVACION: "AUT-026",
        TIPO_MEJORA: "AUT-027",
    }
    if datos.tipo in por_tipo:
        exigir_permisos(usuario, por_tipo[datos.tipo])

    return await HallazgoService(db).registrar(
        id_auditoria, datos.tipo, datos.titulo, datos.descripcion, usuario,
        datos.clasificacion, datos.requisito_relacionado, datos.id_evaluacion,
    )


@router.get("/{id_auditoria}/hallazgos", summary="AUT-029 · Consultar hallazgos consolidados")
async def consolidado_hallazgos(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-029")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).consolidado(id_auditoria)


@router.get(
    "/{id_auditoria}/hallazgos/exportar",
    response_class=Response,
    summary="AUT-030 · Exportar hallazgos al informe preliminar",
)
async def exportar_hallazgos(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-030")),
    db: AsyncSession = Depends(get_db),
):
    consolidado = await HallazgoService(db).consolidado(id_auditoria)
    contenido = generar_excel(
        "Hallazgos de la auditoría",
        ["Tipo", "Clasificación", "Título", "Requisito", "Estado", "Evidencias", "Registrado por"],
        [
            [h["tipo"], h["clasificacion"], h["titulo"],
             h.get("numeral") or h.get("requisito_relacionado"),
             h["estado"], h["evidencias"], h["registrado_por"]]
            for h in consolidado["hallazgos"]
        ],
    )
    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": 'attachment; filename="hallazgos-auditoria.xlsx"'},
    )


@router.put("/{id_auditoria}/hallazgos/{id_hallazgo}", summary="AUT-022 · Editar hallazgo registrado")
async def editar_hallazgo(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    datos: HallazgoEditado,
    usuario: dict = Depends(requiere_permiso("AUT-022")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).editar(
        id_auditoria, id_hallazgo, datos.model_dump(exclude_none=True), usuario
    )


@router.delete("/{id_auditoria}/hallazgos/{id_hallazgo}", summary="AUT-023 · Eliminar hallazgo pendiente")
async def eliminar_hallazgo(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-023")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).eliminar(id_auditoria, id_hallazgo, usuario)


@router.post(
    "/{id_auditoria}/hallazgos/{id_hallazgo}/clasificar",
    summary="AUT-024 · Clasificar el hallazgo (Mayor / Menor)",
)
async def clasificar_hallazgo(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    datos: ClasificacionHallazgo,
    usuario: dict = Depends(requiere_permiso("AUT-024")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).clasificar(
        id_auditoria, id_hallazgo, datos.clasificacion, usuario
    )


@router.post(
    "/{id_auditoria}/hallazgos/{id_hallazgo}/requisito",
    summary="AUT-028 · Adjuntar el requisito relacionado",
)
async def asociar_requisito(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    datos: RequisitoRelacionado,
    usuario: dict = Depends(requiere_permiso("AUT-028")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).asociar_requisito(
        id_auditoria, id_hallazgo, datos.requisito, usuario
    )


@router.get(
    "/{id_auditoria}/hallazgos/{id_hallazgo}/historial",
    summary="AUT-029 · Historial de un hallazgo",
)
async def historial_hallazgo(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-029")),
    db: AsyncSession = Depends(get_db),
):
    return await HallazgoService(db).historial(id_auditoria, id_hallazgo)


# ============================================================
# BLOQUE 4 · EVIDENCIAS (AUT-031 a AUT-040)
# ============================================================

@router.post(
    "/{id_auditoria}/evidencias",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-031 · Subir evidencia (fotos / PDF)",
)
async def subir_evidencia(
    id_auditoria: UUID,
    archivo: UploadFile = File(...),
    id_hallazgo: Optional[UUID] = Query(default=None),
    id_evaluacion: Optional[UUID] = Query(default=None),
    observaciones: Optional[str] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-031")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).subir(
        id_auditoria, archivo, usuario, id_hallazgo, id_evaluacion, observaciones
    )


@router.get("/{id_auditoria}/evidencias", summary="AUT-035 · Consultar las evidencias en línea")
async def listar_evidencias(
    id_auditoria: UUID,
    id_hallazgo: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-035")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).listar(id_auditoria, id_hallazgo)


@router.get("/{id_auditoria}/evidencias/paquete", summary="AUT-039 · Exportar el paquete de evidencias")
async def paquete_evidencias(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-039")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).paquete(id_auditoria)


@router.get("/{id_auditoria}/evidencias/historial", summary="AUT-040 · Ver el historial de carga")
async def historial_evidencias(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-040")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).historial(id_auditoria)


@router.get(
    "/{id_auditoria}/evidencias/{id_evidencia}/archivo",
    response_class=FileResponse,
    summary="AUT-032 · Descargar la evidencia cargada",
)
async def descargar_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-032")),
    db: AsyncSession = Depends(get_db),
):
    ruta, nombre = await EvidenciaService(db).archivo(id_auditoria, id_evidencia)
    return FileResponse(path=ruta, filename=nombre)


@router.put("/{id_auditoria}/evidencias/{id_evidencia}", summary="AUT-033 · Reemplazar evidencia técnica")
async def reemplazar_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    archivo: UploadFile = File(...),
    usuario: dict = Depends(requiere_permiso("AUT-033")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).reemplazar(id_auditoria, id_evidencia, archivo, usuario)


@router.delete("/{id_auditoria}/evidencias/{id_evidencia}", summary="AUT-034 · Eliminar evidencia pendiente")
async def eliminar_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-034")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).eliminar(id_auditoria, id_evidencia, usuario)


@router.post(
    "/{id_auditoria}/evidencias/{id_evidencia}/requisito",
    summary="AUT-036 · Asociar la evidencia al requisito",
)
async def asociar_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    datos: AsociarEvidencia,
    usuario: dict = Depends(requiere_permiso("AUT-036")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).asociar(
        id_auditoria, id_evidencia, datos.id_evaluacion, usuario
    )


@router.get(
    "/{id_auditoria}/evidencias/{id_evidencia}/integridad",
    summary="AUT-037 · Validar la integridad de la evidencia",
)
async def integridad_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-037")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).verificar_integridad(id_auditoria, id_evidencia)


@router.post(
    "/{id_auditoria}/evidencias/{id_evidencia}/observaciones",
    summary="AUT-038 · Registrar observaciones de la evidencia",
)
async def observaciones_evidencia(
    id_auditoria: UUID,
    id_evidencia: UUID,
    datos: ObservacionEvidencia,
    usuario: dict = Depends(requiere_permiso("AUT-038")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).registrar_observacion(
        id_auditoria, id_evidencia, datos.observaciones, usuario, datos.validar
    )


# ============================================================
# BLOQUE 5 · INFORME (AUT-041 a AUT-050)
# ============================================================

@router.post(
    "/{id_auditoria}/informe",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-041 · Generar el borrador del informe",
)
async def generar_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-041")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).generar_borrador(id_auditoria, usuario)


@router.get("/{id_auditoria}/informe", summary="AUT-048 · Consultar el informe de auditoría")
async def consultar_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-048")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).obtener(id_auditoria)


@router.put("/{id_auditoria}/informe", summary="AUT-042 · Editar y AUT-043 · guardar el borrador")
async def guardar_informe(
    id_auditoria: UUID,
    datos: ContenidoInforme,
    usuario: dict = Depends(requiere_permiso("AUT-042")),
    db: AsyncSession = Depends(get_db),
):
    exigir_permisos(usuario, "AUT-043")
    return await InformeService(db).guardar_borrador(id_auditoria, datos.contenido, usuario)


@router.post("/{id_auditoria}/informe/finalizar", summary="AUT-044 · Finalizar el informe (inmutable)")
async def finalizar_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-044")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).finalizar(id_auditoria, usuario)


@router.get(
    "/{id_auditoria}/informe/pdf",
    response_class=Response,
    summary="AUT-045 · Descargar el informe definitivo en PDF",
)
async def descargar_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-045")),
    db: AsyncSession = Depends(get_db),
):
    contenido, nombre = await InformeService(db).pdf(id_auditoria)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get(
    "/{id_auditoria}/informe/impresion",
    response_class=Response,
    summary="AUT-046 · Imprimir el informe técnico",
)
async def imprimir_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-046")),
    db: AsyncSession = Depends(get_db),
):
    contenido, nombre = await InformeService(db).pdf(id_auditoria)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@router.get(
    "/{id_auditoria}/informe/pdf-firmado",
    response_class=Response,
    summary="AUT-049 · Exportar el informe PDF firmado",
)
async def descargar_informe_firmado(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-049")),
    db: AsyncSession = Depends(get_db),
):
    servicio = InformeService(db)
    informe = await servicio.obtener(id_auditoria)
    if not informe.get("firma_digital"):
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="El informe todavía no está firmado.")
    contenido, nombre = await servicio.pdf(id_auditoria)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="firmado-{nombre}"'},
    )


@router.post("/{id_auditoria}/informe/firmar", summary="AUT-050 · Firmar electrónicamente (auditor)")
async def firmar_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-050")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).firmar(id_auditoria, usuario)


@router.post("/{id_auditoria}/informe/comite", summary="AUT-047 · Enviar el informe oficial al Comité")
async def enviar_informe_al_comite(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-047")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).enviar_al_comite(id_auditoria, usuario)


# ============================================================
# BLOQUE 6 · SEGUIMIENTO Y CIERRE (AUT-051 a AUT-060)
# ============================================================

@router.get("/historial", summary="AUT-051 · Consultar auditorías (historial)")
async def historial_auditorias(
    id_empresa: Optional[UUID] = Query(default=None),
    id_solicitud: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-051")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).historial_de_auditorias(id_empresa, id_solicitud)


@router.get("/estadisticas", summary="AUT-059 · Generar estadísticas de hallazgos")
async def estadisticas_hallazgos(
    id_empresa: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-059")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).estadisticas(id_empresa)


@router.get(
    "/estadisticas/exportar",
    response_class=Response,
    summary="AUT-060 · Exportar las estadísticas del módulo",
)
async def exportar_estadisticas(
    id_empresa: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-060")),
    db: AsyncSession = Depends(get_db),
):
    datos = await SeguimientoService(db).estadisticas(id_empresa)
    filas = [["Auditorías", datos["totales"]["auditorias"]],
             ["Cerradas", datos["totales"]["cerradas"]],
             ["Suspendidas", datos["totales"]["suspendidas"]],
             ["Con informe final", datos["totales"]["con_informe_final"]],
             [],
             ["Tipo de hallazgo", "Clasificación", "Total"]]
    filas.extend([[f["tipo"], f["clasificacion"], f["total"]] for f in datos["por_tipo"]])
    contenido = generar_excel("Estadísticas de auditorías", ["Concepto", "Valor", ""], filas)
    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": 'attachment; filename="estadisticas-auditorias.xlsx"'},
    )


@router.get("/{id_auditoria}/historial-inmutable", summary="AUT-052 · Consultar el historial inmutable")
async def historial_inmutable(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-052")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).historial_inmutable(id_auditoria)


@router.post(
    "/{id_auditoria}/seguimiento",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-053 · Registrar acciones de seguimiento",
)
async def registrar_seguimiento(
    id_auditoria: UUID,
    datos: AccionSeguimiento,
    usuario: dict = Depends(requiere_permiso("AUT-053")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).registrar_accion(
        id_auditoria, datos.descripcion, usuario, TIPO_SEGUIMIENTO,
        datos.id_hallazgo, datos.observaciones,
    )


@router.get("/{id_auditoria}/seguimiento", summary="AUT-054 · Consultar acciones de seguimiento")
async def listar_seguimiento(
    id_auditoria: UUID,
    id_hallazgo: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("AUT-054")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).listar_acciones(id_auditoria, id_hallazgo)


@router.post(
    "/{id_auditoria}/acciones-correctivas",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-055 · Registrar acciones correctivas",
)
async def registrar_correctiva(
    id_auditoria: UUID,
    datos: AccionSeguimiento,
    usuario: dict = Depends(requiere_permiso("AUT-055")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).registrar_accion(
        id_auditoria, datos.descripcion, usuario, TIPO_CORRECTIVA,
        datos.id_hallazgo, datos.observaciones,
    )


@router.get("/{id_auditoria}/acciones-correctivas", summary="AUT-056 · Consultar el plan de acciones")
async def listar_correctivas(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-056")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).listar_acciones(id_auditoria)


@router.put(
    "/{id_auditoria}/seguimiento/{id_seguimiento}",
    summary="AUT-056 · Actualizar el avance de una acción",
)
async def actualizar_accion(
    id_auditoria: UUID,
    id_seguimiento: UUID,
    datos: EstadoAccion,
    usuario: dict = Depends(requiere_permiso("AUT-056")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).actualizar_accion(
        id_auditoria, id_seguimiento, datos.estado, datos.observaciones, usuario
    )


@router.post(
    "/{id_auditoria}/hallazgos/{id_hallazgo}/cerrar",
    summary="AUT-055 · Cerrar un hallazgo con su acción verificada",
)
async def cerrar_hallazgo(
    id_auditoria: UUID,
    id_hallazgo: UUID,
    datos: CierreHallazgo,
    usuario: dict = Depends(requiere_permiso("AUT-055")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).cerrar_hallazgo(
        id_auditoria, id_hallazgo, datos.observacion, usuario
    )


@router.post("/{id_auditoria}/cerrar", summary="AUT-057 · Cerrar la auditoría formalmente")
async def cerrar_auditoria(
    id_auditoria: UUID,
    datos: CierreAuditoria,
    usuario: dict = Depends(requiere_permiso("AUT-057")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "AUT-057", id_auditoria, {"observaciones": datos.observaciones},
            "Cerrar formalmente la auditoría.",
        )
    return await SeguimientoService(db).cerrar(id_auditoria, datos.observaciones, usuario)


@router.post("/{id_auditoria}/reabrir", summary="AUT-058 · Reabrir la auditoría (justificado)")
async def reabrir_auditoria(
    id_auditoria: UUID,
    datos: MotivoAuditoria,
    usuario: dict = Depends(requiere_permiso("AUT-058")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).reabrir(id_auditoria, datos.motivo, usuario)


# ============================================================
# BLOQUE 7 · JORNADAS, FIRMA Y ENVÍO (AUT-061 a AUT-070)
# ============================================================

@router.post(
    "/{id_auditoria}/jornadas",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-061 · Registrar la hora de inicio en campo",
)
async def abrir_jornada(
    id_auditoria: UUID,
    datos: JornadaInicio,
    usuario: dict = Depends(requiere_permiso("AUT-061")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).abrir_jornada(
        id_auditoria, usuario, datos.fecha, datos.hora_inicio
    )


@router.get("/{id_auditoria}/jornadas", summary="AUT-063 · Consultar la duración total")
async def consultar_jornadas(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-063")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).jornadas(id_auditoria)


@router.post(
    "/{id_auditoria}/jornadas/{id_jornada}/cerrar",
    summary="AUT-062 · Registrar la hora de finalización diaria",
)
async def cerrar_jornada(
    id_auditoria: UUID,
    id_jornada: UUID,
    datos: JornadaCierre,
    usuario: dict = Depends(requiere_permiso("AUT-062")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).cerrar_jornada(
        id_auditoria, id_jornada, usuario, datos.hora_fin, datos.incidencias, datos.observaciones
    )


@router.post(
    "/{id_auditoria}/jornadas/{id_jornada}/incidencias",
    summary="AUT-064 · Registrar incidencias en sitio",
)
async def registrar_incidencias(
    id_auditoria: UUID,
    id_jornada: UUID,
    datos: IncidenciaJornada,
    usuario: dict = Depends(requiere_permiso("AUT-064")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditoriaService(db).cerrar_jornada(
        id_auditoria, id_jornada, usuario, incidencias=datos.incidencias
    )


@router.post(
    "/{id_auditoria}/cierre/observaciones",
    summary="AUT-065 · Registrar observaciones de cierre",
)
async def observaciones_de_cierre(
    id_auditoria: UUID,
    datos: Observaciones,
    usuario: dict = Depends(requiere_permiso("AUT-065")),
    db: AsyncSession = Depends(get_db),
):
    return await SeguimientoService(db).cerrar(id_auditoria, datos.observaciones, usuario)


@router.post(
    "/{id_auditoria}/cierre/anexos",
    status_code=status.HTTP_201_CREATED,
    summary="AUT-066 · Adjuntar anexos al cierre",
)
async def adjuntar_anexo_cierre(
    id_auditoria: UUID,
    archivo: UploadFile = File(...),
    usuario: dict = Depends(requiere_permiso("AUT-066")),
    db: AsyncSession = Depends(get_db),
):
    return await EvidenciaService(db).subir(
        id_auditoria, archivo, usuario, observaciones="Anexo del cierre de la auditoría"
    )


@router.get("/{id_auditoria}/informe/integridad", summary="AUT-067 · Verificar la integridad digital")
async def integridad_informe(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-067")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).verificar_integridad(id_auditoria)


@router.get("/{id_auditoria}/informe/envio", summary="AUT-068 · Confirmar el envío formal al Comité")
async def confirmar_envio(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-068")),
    db: AsyncSession = Depends(get_db),
):
    return await InformeService(db).confirmar_envio(id_auditoria)


@router.get("/{id_auditoria}/informe/firma", summary="AUT-069 · Constancia de la firma del auditor")
async def constancia_de_firma(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-069")),
    db: AsyncSession = Depends(get_db),
):
    informe = await InformeService(db).obtener(id_auditoria)
    return {
        "id_informe": informe["id_informe"],
        "version": informe["version"],
        "firmado": bool(informe.get("firma_digital")),
        "firma_digital": informe.get("firma_digital"),
        "fecha_firma": informe.get("fecha_firma"),
        "hash_documento": informe.get("hash_documento"),
    }


@router.get("/{id_auditoria}/expediente/cierre", summary="AUT-070 · Expediente listo para votación")
async def expediente_para_votacion(
    id_auditoria: UUID,
    usuario: dict = Depends(requiere_permiso("AUT-070")),
    db: AsyncSession = Depends(get_db),
):
    """
    Lo que el Comité necesita para votar: el informe firmado y enviado, el
    consolidado de hallazgos y el inventario de evidencias verificadas.
    """
    informe = await InformeService(db).confirmar_envio(id_auditoria)
    consolidado = await HallazgoService(db).consolidado(id_auditoria)
    evidencias = await EvidenciaService(db).paquete(id_auditoria)
    return {
        "informe": informe,
        "listo_para_votacion": bool(informe["enviado"]) and informe["firmado"],
        "hallazgos": consolidado["resumen"],
        "evidencias": {"total": evidencias["total"], "integras": evidencias["integras"]},
    }
