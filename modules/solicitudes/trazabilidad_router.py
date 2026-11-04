"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 6 (trazabilidad, bitácora y cierre, SOL-051 a SOL-060).

Donde la hoja marca REQ para el Auxiliar (SOL-054 cambiar estado, SOL-056
exportar, SOL-058 compartir con el Comité, SOL-059 reporte y SOL-060 cerrar),
la acción con efecto no se ejecuta: queda pendiente de aprobación con un 202.
Las dos que solo leen (exportar y reporte) sí se resuelven en el momento.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.solicitudes import trazabilidad_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.solicitudes.sede_excel import TIPO_XLSX, generar_excel
from modules.solicitudes.solicitud_pdf import generar_pdf_solicitud
from modules.solicitudes.solicitud_permissions import NivelPermiso, requiere_permiso
from modules.solicitudes.solicitud_service import SolicitudService
from modules.solicitudes.trazabilidad_service import (
    ESTADOS_ADMINISTRACION,
    TIPOS_OBSERVACION,
    TrazabilidadService,
)

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Trazabilidad y cierre"],
)


class ObservacionControl(BaseModel):
    """Cuerpo de SOL-052 (registrar observación de control)."""

    texto: str = Field(..., min_length=5, max_length=2000)
    tipo: str = Field(default="Control", description=f"Uno de: {', '.join(TIPOS_OBSERVACION)}")


class CambioEstado(BaseModel):
    """Cuerpo de SOL-054 (cambiar estado de solicitud)."""

    estado: str = Field(..., description=f"Uno de: {', '.join(ESTADOS_ADMINISTRACION)}")
    motivo: Optional[str] = Field(default=None, max_length=500)


class CierreSolicitud(BaseModel):
    """Cuerpo de SOL-060 (cerrar solicitud definitivamente)."""

    motivo: str = Field(..., min_length=5, max_length=500)


def _requiere_aprobacion(usuario: dict) -> bool:
    return usuario.get("permiso_nivel") == NivelPermiso.REQUIERE_APROBACION.value


async def _dejar_pendiente(
    db: AsyncSession, usuario: dict, codigo: str, id_solicitud: UUID, datos: dict, detalle: str
) -> JSONResponse:
    solicitud = await SolicitudService(db).consultar(id_solicitud, usuario)
    aprobacion = await AprobacionService(db).solicitar(
        codigo, str(solicitud["id_empresa"]), {**datos, "id_solicitud": str(id_solicitud)},
        detalle, usuario,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=jsonable_encoder({
            "mensaje": "La acción requiere aprobación de un superior. Quedó registrada como pendiente.",
            "aprobacion": aprobacion,
        }),
    )


# ============================================================
# SOL-056 · EXPORTAR EL HISTORIAL DE SOLICITUDES
# ============================================================

@router.get(
    "/historial/exportar",
    response_class=Response,
    summary="SOL-056 · Exportar historial de solicitudes a Excel",
)
async def exportar_historial(
    estado: Optional[str] = Query(default=None),
    id_empresa: Optional[UUID] = Query(default=None),
    usuario: dict = Depends(requiere_permiso("SOL-056")),
    db: AsyncSession = Depends(get_db),
):
    filas = await TrazabilidadService(db).historial_general(usuario, estado, id_empresa)
    contenido = generar_excel(
        "Historial de solicitudes de certificación",
        ["Radicado", "Empresa", "NIT", "Norma", "Estado", "Creada",
         "Radicada", "Cerrada", "Último movimiento", "Observaciones"],
        [
            [f.get("numero_radicado"), f.get("empresa"), f.get("nit"), f.get("norma"),
             f.get("estado"), f.get("fecha_creacion"), f.get("fecha_radicacion"),
             f.get("fecha_cierre"), f.get("ultimo_movimiento"), f.get("observaciones")]
            for f in filas
        ],
    )
    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": 'attachment; filename="historial-solicitudes.xlsx"'},
    )


# ============================================================
# SOL-059 · REPORTE DEL MÓDULO
# ============================================================

@router.get("/reporte/modulo", summary="SOL-059 · Generar reporte del módulo")
async def reporte_modulo(
    usuario: dict = Depends(requiere_permiso("SOL-059")),
    db: AsyncSession = Depends(get_db),
):
    return await TrazabilidadService(db).reporte(usuario)


# ============================================================
# SOL-051 · HISTORIAL DE LA SOLICITUD
# ============================================================

@router.get("/{id_solicitud}/historial", summary="SOL-051 · Consultar historial de la solicitud")
async def consultar_historial(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-051")),
    db: AsyncSession = Depends(get_db),
):
    return await TrazabilidadService(db).historial(id_solicitud, usuario)


# ============================================================
# SOL-052 / SOL-053 · OBSERVACIONES DE CONTROL
# ============================================================

@router.post(
    "/{id_solicitud}/observaciones",
    status_code=status.HTTP_201_CREATED,
    summary="SOL-052 · Registrar observación de control",
)
async def registrar_observacion(
    id_solicitud: UUID,
    datos: ObservacionControl,
    usuario: dict = Depends(requiere_permiso("SOL-052")),
    db: AsyncSession = Depends(get_db),
):
    return await TrazabilidadService(db).registrar_observacion(
        id_solicitud, datos.texto, datos.tipo, usuario
    )


@router.get("/{id_solicitud}/observaciones", summary="SOL-053 · Consultar observaciones")
async def listar_observaciones(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-053")),
    db: AsyncSession = Depends(get_db),
):
    return await TrazabilidadService(db).listar_observaciones(id_solicitud, usuario)


# ============================================================
# SOL-054 · CAMBIAR EL ESTADO
# ============================================================

@router.patch("/{id_solicitud}/estado", summary="SOL-054 · Cambiar estado de la solicitud")
async def cambiar_estado(
    id_solicitud: UUID,
    datos: CambioEstado,
    usuario: dict = Depends(requiere_permiso("SOL-054")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-054", id_solicitud,
            {"estado": datos.estado, "motivo": datos.motivo},
            f"Cambiar el estado de la solicitud a '{datos.estado}'.",
        )
    return await TrazabilidadService(db).cambiar_estado(
        id_solicitud, datos.estado, datos.motivo, usuario
    )


# ============================================================
# SOL-055 · BITÁCORA INMUTABLE
# ============================================================

@router.get("/{id_solicitud}/bitacora", summary="SOL-055 · Consultar bitácora inmutable")
async def consultar_bitacora(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-055")),
    db: AsyncSession = Depends(get_db),
):
    return await TrazabilidadService(db).leer_bitacora(id_solicitud, usuario)


# ============================================================
# SOL-057 · IMPRIMIR LA SOLICITUD COMPLETA
# ============================================================

@router.get(
    "/{id_solicitud}/impresion",
    response_class=Response,
    summary="SOL-057 · Imprimir solicitud completa",
)
async def imprimir_solicitud(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-057")),
    db: AsyncSession = Depends(get_db),
):
    """
    El PDF de SOL-007 con lo que añaden los bloques siguientes: el historial
    de estados y las observaciones de control.
    """
    servicio = TrazabilidadService(db)
    solicitud = await SolicitudService(db).consultar_ampliada(id_solicitud, usuario)
    historial = await servicio.historial(id_solicitud, usuario)
    observaciones = await servicio.listar_observaciones(id_solicitud, usuario)

    extra = [
        ("Movimientos registrados", len(historial)),
        ("Observaciones de control", len(observaciones)),
    ]
    if historial:
        ultimo = historial[-1]
        extra.append(("Último movimiento", f"{ultimo['estado']} · {ultimo['fecha']}"))
    if observaciones:
        extra.append(("Última observación", observaciones[0]["texto"][:80]))

    contenido = generar_pdf_solicitud(solicitud, extra)
    radicado = solicitud.get("numero_radicado") or "borrador"
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="solicitud-{radicado}.pdf"'},
    )


# ============================================================
# SOL-058 · COMPARTIR EL EXPEDIENTE CON EL COMITÉ
# ============================================================

@router.post("/{id_solicitud}/comite", summary="SOL-058 · Compartir expediente con el Comité")
async def compartir_con_comite(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-058")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-058", id_solicitud, {},
            "Compartir el expediente de la solicitud con el Comité.",
        )
    return await TrazabilidadService(db).compartir_con_comite(id_solicitud, usuario)


# ============================================================
# SOL-060 · CERRAR LA SOLICITUD
# ============================================================

@router.post("/{id_solicitud}/cerrar", summary="SOL-060 · Cerrar solicitud definitivamente")
async def cerrar_solicitud(
    id_solicitud: UUID,
    datos: CierreSolicitud,
    usuario: dict = Depends(requiere_permiso("SOL-060")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-060", id_solicitud, {"motivo": datos.motivo},
            f"Cerrar definitivamente la solicitud: {datos.motivo}",
        )
    return await TrazabilidadService(db).cerrar(id_solicitud, datos.motivo, usuario)
