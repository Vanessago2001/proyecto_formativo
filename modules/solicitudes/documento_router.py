"""
M5 — GESTIÓN DE SOLICITUDES
Endpoints del Bloque 4 (documentos adjuntos, SOL-031 a SOL-040).
"""

import mimetypes
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.solicitudes.documento_schema import (
    AprobacionDocumento,
    DocumentoRespuesta,
    EstadoDocumento,
    ReglasFormato,
    RevisionDocumento,
    VersionDocumento,
)
from modules.solicitudes.documento_service import (
    EXTENSIONES_PERMITIDAS,
    TAMANO_MAXIMO_BYTES,
    TIPOS_DOCUMENTO_SUGERIDOS,
    DocumentoService,
)
from modules.solicitudes.solicitud_permissions import requiere_permiso

router = APIRouter(
    prefix="/solicitudes",
    tags=["M5 - Documentos de la solicitud"],
)


# ============================================================
# SOL-036 — REGLAS DE FORMATO
# ============================================================

@router.get(
    "/documentos/formatos-permitidos",
    response_model=ReglasFormato,
    summary="SOL-036 · Consultar reglas de formato",
)
async def formatos_permitidos(
    usuario: dict = Depends(requiere_permiso("SOL-036")),
):
    """
    Reglas que aplica la validación automática al subir un archivo.

    El portal las usa para avisar al usuario antes de que intente subir algo
    que va a ser rechazado.
    """
    return ReglasFormato(
        extensiones_permitidas=sorted(EXTENSIONES_PERMITIDAS),
        tamano_maximo_mb=TAMANO_MAXIMO_BYTES / 1024 / 1024,
        tipos_documento_sugeridos=TIPOS_DOCUMENTO_SUGERIDOS,
    )


# ============================================================
# SOL-031 — SUBIR DOCUMENTO
# ============================================================

@router.post(
    "/{id_solicitud}/documentos",
    response_model=DocumentoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="SOL-031 · Subir documento requerido",
)
async def subir_documento(
    id_solicitud: UUID,
    tipo_documento: str = Form(..., min_length=3, max_length=100),
    archivo: UploadFile = File(...),
    usuario: dict = Depends(requiere_permiso("SOL-031")),
    db: AsyncSession = Depends(get_db),
):
    """Adjunta un documento nuevo. El formato se valida automáticamente."""
    return await DocumentoService(db).subir(
        id_solicitud, tipo_documento, archivo, usuario
    )


# ============================================================
# SOL-035 — LISTAR / VISOR
# ============================================================

@router.get(
    "/{id_solicitud}/documentos",
    response_model=list[DocumentoRespuesta],
    summary="SOL-035 · Consultar documentos de la solicitud",
)
async def listar_documentos(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-035")),
    db: AsyncSession = Depends(get_db),
):
    """Documentos adjuntos con su estado de revisión."""
    return await DocumentoService(db).listar(id_solicitud, usuario)


@router.get(
    "/{id_solicitud}/documentos/{id_documento}/ver",
    summary="SOL-035 · Ver documento en el visor",
    response_class=FileResponse,
)
async def ver_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-035")),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve el archivo para mostrarlo en el navegador, sin descargarlo."""
    ruta, nombre = await DocumentoService(db).obtener_archivo(
        id_solicitud, id_documento, usuario
    )
    tipo, _ = mimetypes.guess_type(nombre)

    return FileResponse(
        path=ruta,
        media_type=tipo or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


# ============================================================
# SOL-034 — DESCARGAR
# ============================================================

@router.get(
    "/{id_solicitud}/documentos/{id_documento}/descargar",
    summary="SOL-034 · Descargar documento adjunto",
    response_class=FileResponse,
)
async def descargar_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-034")),
    db: AsyncSession = Depends(get_db),
):
    """Descarga el archivo con su nombre original."""
    ruta, nombre = await DocumentoService(db).obtener_archivo(
        id_solicitud, id_documento, usuario
    )
    return FileResponse(path=ruta, filename=nombre)


# ============================================================
# SOL-040 — HISTORIAL DOCUMENTAL
# ============================================================

@router.get(
    "/{id_solicitud}/documentos/historial",
    response_model=list[VersionDocumento],
    summary="SOL-040 · Consultar historial documental",
)
async def historial_documental(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-040")),
    db: AsyncSession = Depends(get_db),
):
    """Versiones anteriores de los documentos, con quién y cuándo."""
    return await DocumentoService(db).historial(id_solicitud, usuario)


# ============================================================
# SOL-032 — REEMPLAZAR
# ============================================================

@router.put(
    "/{id_solicitud}/documentos/{id_documento}",
    response_model=DocumentoRespuesta,
    summary="SOL-032 · Reemplazar documento",
)
async def reemplazar_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    archivo: UploadFile = File(...),
    usuario: dict = Depends(requiere_permiso("SOL-032")),
    db: AsyncSession = Depends(get_db),
):
    """Sube una versión nueva; la anterior queda en el historial."""
    return await DocumentoService(db).reemplazar(
        id_solicitud, id_documento, archivo, usuario
    )


# ============================================================
# SOL-033 — ELIMINAR
# ============================================================

@router.delete(
    "/{id_solicitud}/documentos/{id_documento}",
    summary="SOL-033 · Eliminar documento",
)
async def eliminar_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-033")),
    db: AsyncSession = Depends(get_db),
):
    """Quita un documento no aprobado; su historial se conserva."""
    return await DocumentoService(db).eliminar(id_solicitud, id_documento, usuario)


# ============================================================
# SOL-038 / SOL-037 / SOL-039 — REVISIÓN
# ============================================================

@router.post(
    "/{id_solicitud}/documentos/{id_documento}/aprobar",
    response_model=DocumentoRespuesta,
    summary="SOL-038 · Aprobar documento adjunto",
)
async def aprobar_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    data: AprobacionDocumento | None = None,
    usuario: dict = Depends(requiere_permiso("SOL-038")),
    db: AsyncSession = Depends(get_db),
):
    """Da el documento por válido. Deja de poder reemplazarse."""
    return await DocumentoService(db).revisar(
        id_solicitud,
        id_documento,
        EstadoDocumento.aprobado,
        data.observaciones if data else None,
        usuario,
    )


@router.post(
    "/{id_solicitud}/documentos/{id_documento}/rechazar",
    response_model=DocumentoRespuesta,
    summary="SOL-037 · Rechazar documento",
)
async def rechazar_documento(
    id_solicitud: UUID,
    id_documento: UUID,
    data: RevisionDocumento,
    usuario: dict = Depends(requiere_permiso("SOL-037")),
    db: AsyncSession = Depends(get_db),
):
    """Rechaza el documento indicando el motivo, que ve la empresa."""
    return await DocumentoService(db).revisar(
        id_solicitud,
        id_documento,
        EstadoDocumento.rechazado,
        data.observaciones,
        usuario,
    )


@router.post(
    "/{id_solicitud}/documentos/{id_documento}/solicitar-correccion",
    response_model=DocumentoRespuesta,
    summary="SOL-039 · Solicitar corrección",
)
async def solicitar_correccion(
    id_solicitud: UUID,
    id_documento: UUID,
    data: RevisionDocumento,
    usuario: dict = Depends(requiere_permiso("SOL-039")),
    db: AsyncSession = Depends(get_db),
):
    """Pide a la empresa que corrija y vuelva a subir el documento."""
    return await DocumentoService(db).revisar(
        id_solicitud,
        id_documento,
        EstadoDocumento.correccion,
        data.observaciones,
        usuario,
    )
