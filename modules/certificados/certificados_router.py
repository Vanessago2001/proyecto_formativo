import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user, require_role
from modules.certificados.certificados_pdf import generar_pdf_certificado
from modules.certificados.certificados_permissions import (
    marcar_aprobacion,
    nivel_permiso,
    requiere_permiso,
    PERMISOS_M9,
    F,
    REQ,
)
from modules.certificados.certificados_schema import (
    CertificadoAlcance,
    CertificadoCrear,
    CertificadoMotivo,
    CertificadoRenovar,
    LiderComiteAsignar,
)
from modules.certificados.certificados_service import (
    CertificadosService,
    certificado_esta_vigente,
    es_usuario_publico,
    ESTADO_VIGENTE,
)
from modules.consultas_p.rate_limit import limitar_consultas

router = APIRouter(prefix="/certificados", tags=["M9 - Certificados"])


def _csv_safe_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def requiere_firma_lider_o_permiso():
    async def verificar(usuario: dict = Depends(get_current_user)) -> dict:
        rol = _normalize_role_name(usuario.get("role_name"))
        if rol == "comite":
            # CER-010 deniega el rol Comité en general. El servicio permite
            # continuar solo si este usuario es el líder asignado al certificado.
            return usuario
        nivel = nivel_permiso("CER-010", usuario.get("role_name"))
        if nivel is F:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso CER-010 ({PERMISOS_M9['CER-010'][0]}) denegado para el rol.",
            )
        usuario["requiere_aprobacion"] = nivel is REQ
        return usuario

    return verificar


def _csv_response(filas: list[dict], columnas: tuple[str, ...], nombre: str) -> Response:
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer)
    escritor.writerow(columnas)
    for fila in filas:
        escritor.writerow([_csv_safe_value(fila.get(columna)) for columna in columnas])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get(
    "/publico/{codigo}",
    summary="Consultar certificado publicado",
    dependencies=[Depends(limitar_consultas)],
)
async def consultar_certificado_publico(
    codigo: str,
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).publico(codigo)


@router.get(
    "/publico/{codigo}/pdf",
    summary="Descargar certificado público",
    response_class=Response,
    dependencies=[Depends(limitar_consultas)],
)
async def descargar_certificado_publico(
    codigo: str,
    db: AsyncSession = Depends(get_db),
):
    contenido = await CertificadosService(db).pdf_publico_firmado(codigo)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{codigo}.pdf"'},
    )


@router.get("/metricas-publicas", summary="Consultar métricas públicas")
async def consultar_metricas_publicas(db: AsyncSession = Depends(get_db)):
    return await CertificadosService(db).metricas_publicas()


@router.get("/lider-comite/actual", summary="Consultar líder de firma asignado")
async def consultar_lider_comite_actual(
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).mi_liderazgo(usuario)


@router.get(
    "/lider-comite/opciones",
    summary="Listar usuarios Comité activos para asignar líder",
    dependencies=[Depends(require_role(["Super Administrador", "Administrador"]))],
)
async def listar_lideres_comite(db: AsyncSession = Depends(get_db)):
    return await CertificadosService(db).listar_lideres_comite()


@router.put(
    "/lider-comite",
    summary="Asignar líder de firma del Comité",
    dependencies=[Depends(require_role(["Super Administrador", "Administrador"]))],
)
async def asignar_lider_comite(
    data: LiderComiteAsignar,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).asignar_lider_comite(data.id_usuario, usuario)


@router.post("/", status_code=status.HTTP_201_CREATED, summary="CER-001 · Generar certificado")
async def generar_certificado(
    data: CertificadoCrear,
    usuario: dict = Depends(requiere_permiso("CER-001")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).crear(data, usuario)


@router.get("/", summary="CER-011 · Consultar certificados")
async def listar_certificados(
    limite: int = Query(default=100, ge=1, le=500),
    desplazamiento: int = Query(default=0, ge=0),
    usuario: dict = Depends(requiere_permiso("CER-011")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).listar(usuario, limite, desplazamiento)


@router.get("/metricas", summary="CER-024 · Consultar publicación y métricas")
async def consultar_metricas(
    usuario: dict = Depends(requiere_permiso("CER-024")),
    db: AsyncSession = Depends(get_db),
):
    service = CertificadosService(db)
    if es_usuario_publico(usuario):
        return await service.metricas_publicas()
    return await service.metricas()


@router.get("/alertas/vencimiento", summary="CER-027 · Consultar próximos vencimientos")
async def consultar_alertas_vencimiento(
    dias: int = Query(default=30, ge=1, le=365),
    usuario: dict = Depends(requiere_permiso("CER-027")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).alertas_vencimiento(dias, usuario)


@router.post("/notificar-vencimiento/{id_certificado}", summary="CER-028 · Notificar vencimiento")
async def notificar_vencimiento(
    id_certificado: UUID,
    dias: int = Query(default=30, ge=1, le=365),
    usuario: dict = Depends(requiere_permiso("CER-028")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).notificar_vencimiento(id_certificado, dias, usuario)


@router.get("/exportar", summary="CER-025 · Exportar base de certificados")
async def exportar_certificados(
    usuario: dict = Depends(requiere_permiso("CER-025")),
    db: AsyncSession = Depends(get_db),
):
    filas = await CertificadosService(db).registros_exportacion()
    columnas = (
        "codigo_verificacion", "numero_radicado", "empresa", "nit",
        "norma_codigo", "alcance", "fecha_emision", "fecha_vencimiento",
        "estado_certificado", "publico_certificado",
    )
    respuesta = _csv_response(filas, columnas, "certificados.csv")
    if usuario.get("requiere_aprobacion"):
        respuesta.headers["X-Requiere-Aprobacion"] = "true"
    return respuesta


@router.get("/empresas-oficiales", summary="CER-026 · Listado oficial de empresas")
async def exportar_empresas_certificadas(
    usuario: dict = Depends(requiere_permiso("CER-026")),
    db: AsyncSession = Depends(get_db),
):
    filas = await CertificadosService(db).empresas_oficiales()
    columnas = (
        "empresa", "nit", "ciudad", "norma_codigo", "fecha_emision",
        "fecha_vencimiento", "codigo_verificacion",
    )
    return _csv_response(filas, columnas, "empresas-certificadas.csv")


@router.get("/{id_certificado}", summary="CER-011 · Consultar certificado")
async def consultar_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-011")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db)._obtener(id_certificado, usuario)


@router.get("/{id_certificado}/pdf/preview", summary="CER-009 · Generar PDF de revisión", response_class=Response)
async def generar_pdf_revision(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-009")),
    db: AsyncSession = Depends(get_db),
):
    certificado = await CertificadosService(db)._obtener(id_certificado)
    return Response(
        content=generar_pdf_certificado(certificado),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{certificado["codigo_verificacion"]}-revision.pdf"'},
    )


@router.get("/{id_certificado}/pdf", summary="CER-012 · Descargar certificado PDF", response_class=Response)
async def descargar_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-012")),
    db: AsyncSession = Depends(get_db),
):
    contenido = await CertificadosService(db).pdf_firmado(id_certificado, usuario)
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{certificado["codigo_verificacion"]}.pdf"'},
    )


@router.post("/{id_certificado}/firmar", summary="CER-010 · Firmar digitalmente")
async def firmar_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_firma_lider_o_permiso()),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).firmar_con_lider_asignado(id_certificado, usuario)


@router.post("/{id_certificado}/reenviar", summary="CER-013 · Reenviar certificado por correo")
async def reenviar_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-013")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).reenviar(id_certificado, usuario)


@router.post("/{id_certificado}/renovar", status_code=status.HTTP_201_CREATED, summary="CER-014/029 · Renovar certificado")
async def renovar_certificado(
    id_certificado: UUID,
    data: CertificadoRenovar,
    usuario: dict = Depends(requiere_permiso("CER-014")),
    db: AsyncSession = Depends(get_db),
):
    renovacion = await CertificadosService(db).renovar(
        id_certificado, data.fecha_vencimiento, usuario
    )
    renovacion["requiere_aprobacion"] = bool(usuario.get("requiere_aprobacion"))
    return renovacion


@router.post("/{id_certificado}/suspender", summary="CER-015/018 · Suspender certificado")
async def suspender_certificado(
    id_certificado: UUID,
    data: CertificadoMotivo,
    usuario: dict = Depends(requiere_permiso("CER-015")),
    db: AsyncSession = Depends(get_db),
):
    resultado = await CertificadosService(db).cambiar_estado(
        id_certificado, "SUSPENDIDO", data.motivo, usuario
    )
    return marcar_aprobacion(resultado, usuario)


@router.post("/{id_certificado}/motivo-suspension", summary="CER-018 · Registrar motivo de suspensión")
async def registrar_motivo_suspension(
    id_certificado: UUID,
    data: CertificadoMotivo,
    usuario: dict = Depends(requiere_permiso("CER-018")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).registrar_motivo_suspension(
        id_certificado, data.motivo, usuario
    )


@router.post("/{id_certificado}/reactivar", summary="CER-016 · Reactivar certificado")
async def reactivar_certificado(
    id_certificado: UUID,
    data: CertificadoMotivo,
    usuario: dict = Depends(requiere_permiso("CER-016")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).cambiar_estado(
        id_certificado, ESTADO_VIGENTE, data.motivo, usuario
    )


@router.post("/{id_certificado}/cancelar", summary="CER-017/019 · Cancelar certificado")
async def cancelar_certificado(
    id_certificado: UUID,
    data: CertificadoMotivo,
    usuario: dict = Depends(requiere_permiso("CER-017")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).cambiar_estado(
        id_certificado, "CANCELADO", data.motivo, usuario
    )


@router.post("/{id_certificado}/motivo-cancelacion", summary="CER-019 · Registrar motivo de cancelación")
async def registrar_motivo_cancelacion(
    id_certificado: UUID,
    data: CertificadoMotivo,
    usuario: dict = Depends(requiere_permiso("CER-019")),
    db: AsyncSession = Depends(get_db),
):
    resultado = await CertificadosService(db).registrar_motivo_cancelacion(
        id_certificado, data.motivo, usuario
    )
    return marcar_aprobacion(resultado, usuario)


@router.get("/{id_certificado}/historial", summary="CER-020 · Consultar historial de estados")
async def consultar_historial_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-020")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).historial(id_certificado, usuario)


@router.post("/{id_certificado}/publicar", summary="CER-021/023 · Publicar certificado")
async def publicar_certificado(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-021")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).cambiar_publicacion(id_certificado, True, usuario)


@router.post("/{id_certificado}/retirar-portal", summary="CER-022 · Retirar del portal público")
async def retirar_certificado_portal(
    id_certificado: UUID,
    usuario: dict = Depends(requiere_permiso("CER-022")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).cambiar_publicacion(id_certificado, False, usuario)


@router.post("/{id_certificado}/alcance", summary="CER-030 · Registrar cambios de alcance")
async def actualizar_alcance_certificado(
    id_certificado: UUID,
    data: CertificadoAlcance,
    usuario: dict = Depends(requiere_permiso("CER-030")),
    db: AsyncSession = Depends(get_db),
):
    return await CertificadosService(db).actualizar_alcance(
        id_certificado, data.id_alcance, usuario
    )