"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 7 (cálculo del tiempo de auditoría, SOL-061 a SOL-070).

SOL-063 (recalcular) y SOL-065 (justificar ajustes) están marcadas REQ para
el Auxiliar: la acción queda pendiente de aprobación y responde 202.
SOL-066 (modificar variables base) es SA: solo el SuperAdministrador, y el
propio catálogo de permisos ya lo impone.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.aprobaciones.aprobacion_service import AprobacionService
from modules.solicitudes import calculo_aprobaciones  # noqa: F401  (registra las acciones REQ)
from modules.solicitudes.calculo_service import (
    COMPLEJIDADES,
    VARIABLES_BASE,
    CalculoAuditoriaService,
)
from modules.solicitudes.sede_excel import TIPO_XLSX, generar_excel
from modules.solicitudes.solicitud_permissions import NivelPermiso, requiere_permiso
from modules.solicitudes.solicitud_service import SolicitudService

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Cálculo del tiempo de auditoría"],
)


class VariablesCalculo(BaseModel):
    """Cuerpo de SOL-061 / SOL-062 (variables de entrada del cálculo)."""

    numero_empleados: Optional[int] = Field(default=None, ge=0)
    numero_sedes: Optional[int] = Field(default=None, ge=1)
    complejidad: Optional[str] = Field(
        default=None, description=f"Uno de: {', '.join(COMPLEJIDADES)}"
    )
    observaciones: Optional[str] = Field(default=None, max_length=500)


class AjusteTiempo(BaseModel):
    """Cuerpo de SOL-065 (justificar ajustes de tiempo)."""

    horas: float = Field(..., description="Horas que se suman o se restan al resultado")
    justificacion: str = Field(..., min_length=10, max_length=1000)


class VariablesNorma(BaseModel):
    """Cuerpo de SOL-066 (modificar variables base de la norma)."""

    valores: dict[str, float] = Field(
        ..., description=f"Variables admitidas: {', '.join(VARIABLES_BASE)}"
    )


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
# SOL-066 · VARIABLES BASE DE LA NORMA (ruta literal primero)
# ============================================================

@router.get(
    "/calculo/normas/{id_norma}/variables",
    summary="SOL-066 · Consultar las variables base de la norma",
)
async def consultar_variables_norma(
    id_norma: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-064")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).listar_variables_norma(id_norma)


@router.put(
    "/calculo/normas/{id_norma}/variables",
    summary="SOL-066 · Modificar las variables base de la norma",
)
async def modificar_variables_norma(
    id_norma: UUID,
    datos: VariablesNorma,
    usuario: dict = Depends(requiere_permiso("SOL-066")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).guardar_variables_norma(
        id_norma, datos.valores, usuario
    )


# ============================================================
# SOL-062 / SOL-063 · CALCULAR Y RECALCULAR
# ============================================================

@router.post(
    "/{id_solicitud}/calculo",
    status_code=status.HTTP_201_CREATED,
    summary="SOL-061 · Registrar variables y SOL-062 · calcular el tiempo",
)
async def calcular_tiempo(
    id_solicitud: UUID,
    datos: VariablesCalculo,
    usuario: dict = Depends(requiere_permiso("SOL-062")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).calcular(
        id_solicitud, datos.model_dump(exclude_none=True), usuario
    )


@router.post("/{id_solicitud}/calculo/recalcular", summary="SOL-063 · Recalcular el tiempo")
async def recalcular_tiempo(
    id_solicitud: UUID,
    datos: VariablesCalculo,
    usuario: dict = Depends(requiere_permiso("SOL-063")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-063", id_solicitud,
            {"variables": datos.model_dump(exclude_none=True)},
            "Recalcular el tiempo de auditoría con otras variables.",
        )
    return await CalculoAuditoriaService(db).calcular(
        id_solicitud, datos.model_dump(exclude_none=True), usuario, recalculo=True
    )


# ============================================================
# SOL-064 / SOL-067 · CONSULTAR
# ============================================================

@router.get("/{id_solicitud}/calculo", summary="SOL-064 · Consultar el resultado del cálculo")
async def consultar_calculo(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-064")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).consultar(id_solicitud, usuario)


@router.get("/{id_solicitud}/calculo/historial", summary="SOL-067 · Consultar historial matemático")
async def historial_calculo(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-067")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).historial(id_solicitud, usuario)


# ============================================================
# SOL-065 · AJUSTE JUSTIFICADO
# ============================================================

@router.post("/{id_solicitud}/calculo/ajuste", summary="SOL-065 · Justificar un ajuste de tiempo")
async def ajustar_tiempo(
    id_solicitud: UUID,
    datos: AjusteTiempo,
    usuario: dict = Depends(requiere_permiso("SOL-065")),
    db: AsyncSession = Depends(get_db),
):
    if _requiere_aprobacion(usuario):
        return await _dejar_pendiente(
            db, usuario, "SOL-065", id_solicitud,
            {"horas": datos.horas, "justificacion": datos.justificacion},
            f"Ajustar el tiempo de auditoría en {datos.horas} horas.",
        )
    return await CalculoAuditoriaService(db).ajustar(
        id_solicitud, datos.horas, datos.justificacion, usuario
    )


# ============================================================
# SOL-068 · EXPORTAR EL DESGLOSE
# ============================================================

@router.get(
    "/{id_solicitud}/calculo/exportar",
    response_class=Response,
    summary="SOL-068 · Exportar el desglose del cálculo",
)
async def exportar_desglose(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-068")),
    db: AsyncSession = Depends(get_db),
):
    servicio = CalculoAuditoriaService(db)
    calculo = await servicio.consultar(id_solicitud, usuario)
    desglose = calculo.get("desglose") or {}
    constantes = desglose.pop("constantes", {}) if isinstance(desglose, dict) else {}

    filas = [[clave.replace("_", " ").capitalize(), valor] for clave, valor in desglose.items()]
    filas.append(["Ajuste manual (horas)", str(calculo.get("ajuste_horas"))])
    filas.append(["Justificación del ajuste", calculo.get("justificacion_ajuste") or "Sin ajuste"])
    filas.append(["TOTAL (horas)", str(calculo.get("resultado_horas"))])
    filas.append([])
    filas.append(["Constantes aplicadas", ""])
    filas.extend([[clave.replace("_", " ").capitalize(), valor] for clave, valor in constantes.items()])

    contenido = generar_excel(
        f"Desglose del cálculo · versión {calculo.get('version')}",
        ["Concepto", "Valor"],
        filas,
    )
    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={"Content-Disposition": 'attachment; filename="desglose-calculo.xlsx"'},
    )


# ============================================================
# SOL-069 / SOL-070 · VALIDAR Y BLOQUEAR
# ============================================================

@router.post("/{id_solicitud}/calculo/validar", summary="SOL-069 · Validar el cálculo antes de asignar")
async def validar_calculo(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-069")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).validar(id_solicitud, usuario)


@router.post("/{id_solicitud}/calculo/bloquear", summary="SOL-070 · Bloquear cambios tras la aprobación")
async def bloquear_calculo(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-070")),
    db: AsyncSession = Depends(get_db),
):
    return await CalculoAuditoriaService(db).bloquear(id_solicitud, usuario, bloquear=True)
