from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.conflictos_auditor.conflictos_service import ConflictoAuditorService
from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from modules.solicitudes.solicitud_permissions import requiere_permiso

router = APIRouter(prefix="/conflictos-auditor", tags=["Conflictos de interés del auditor"])


@router.get("/usuario/{id_usuario}")
async def listar(id_usuario: UUID, db: AsyncSession = Depends(get_db)):
    return {"conflictos": await ConflictoAuditorService(db).listar_por_usuario(id_usuario)}


@router.delete("/{id_conflicto}")
async def eliminar_conflicto_administrador(
    id_conflicto: UUID,
    id_usuario: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_conflicto_administrador(id_usuario, id_conflicto)


@router.get("/empresas-restringidas")
async def empresas_restringidas(db: AsyncSession = Depends(get_db)):
    return {"empresas": await ConflictoAuditorService(db).empresas_restringidas()}


@router.post("/administrador/usuario/{id_usuario}")
async def crear_conflicto_administrador(
    id_usuario: UUID,
    data: ConflictoInteresCrear,
    usuario: dict = Depends(requiere_permiso("SOL-006")),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_conflicto_administrador(id_usuario, data)


@router.post("/validar-asignacion")
async def validar_asignacion(data: dict, db: AsyncSession = Depends(get_db)):
    try:
        id_usuario = UUID(str(data.get("id_usuario")))
        id_empresa = UUID(str(data.get("id_empresa")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="id_usuario e id_empresa deben ser UUID válidos.",
        )
    return await ConflictoAuditorService(db).validar_antes_asignacion(
        id_usuario=id_usuario,
        id_empresa=id_empresa,
    )


@router.post("/validar-asignacion-nit")
async def validar_asignacion_por_nit(data: dict, db: AsyncSession = Depends(get_db)):
    try:
        id_usuario = UUID(str(data.get("id_usuario")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="id_usuario debe ser un UUID válido.",
        )
    nit_empresa = str(data.get("nit_empresa") or "").strip()
    if not nit_empresa:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="nit_empresa es requerido.",
        )
    return await ConflictoAuditorService(db).validar_antes_asignacion_por_nit(
        id_usuario=id_usuario,
        nit_empresa=nit_empresa,
    )
