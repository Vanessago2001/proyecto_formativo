from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.auth.dependencies import (
    es_rol_administrativo,
    require_auditor_aprobado,
    require_self_or_admin_con,
)
from modules.permisos_auxiliar.regla_auxiliar import exigir_permiso_auxiliar
from modules.conflictos_auditor.conflictos_service import ConflictoAuditorService
from modules.auditores.auditor_schema import ConflictoInteresCrear
from modules.auditores.auditor_service import AuditorService
from modules.solicitudes.solicitud_permissions import requiere_permiso

# Módulo "Conflictos y restricciones" (aparte del formulario de registro, que
# declara sus conflictos en /auditores/registro/{id}/conflictos): solo para el
# auditor ya aprobado (ver require_auditor_aprobado).
router = APIRouter(
    prefix="/conflictos-auditor",
    tags=["Conflictos de interés del auditor"],
    dependencies=[Depends(require_auditor_aprobado)],
)


@router.get("/usuario/{id_usuario}")
async def listar(
    id_usuario: UUID,
    usuario: dict = Depends(require_self_or_admin_con("AUD-033")),
    db: AsyncSession = Depends(get_db),
):
    return {"conflictos": await ConflictoAuditorService(db).listar_por_usuario(id_usuario)}


@router.post("/usuario/{id_usuario}")
async def declarar(
    id_usuario: UUID,
    data: ConflictoInteresCrear,
    usuario: dict = Depends(require_self_or_admin_con("AUD-035")),
    db: AsyncSession = Depends(get_db),
):
    """Declara un conflicto de interés nuevo sin importar el estado de la postulación."""
    return await AuditorService(db).declarar_conflicto(id_usuario, data)


@router.delete("/{id_conflicto}")
async def eliminar_conflicto_administrador(
    id_conflicto: UUID,
    id_usuario: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-006", auxiliar=("AUD-035",))),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).eliminar_conflicto_administrador(id_usuario, id_conflicto)


@router.get("/empresas-restringidas")
async def empresas_restringidas(
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # El auditor solo ve sus propios conflictos; los roles administrativos ven
    # todos (el Auxiliar, con AUD-036 delegado).
    exigir_permiso_auxiliar(usuario, "AUD-036")
    propio = None if es_rol_administrativo(usuario, "AUD-036") else usuario["id_usuario"]
    return {"empresas": await ConflictoAuditorService(db).empresas_restringidas(propio)}


@router.post("/administrador/usuario/{id_usuario}")
async def crear_conflicto_administrador(
    id_usuario: UUID,
    data: ConflictoInteresCrear,
    usuario: dict = Depends(requiere_permiso("SOL-006", auxiliar=("AUD-035",))),
    db: AsyncSession = Depends(get_db),
):
    return await AuditorService(db).crear_conflicto_administrador(id_usuario, data)


@router.post("/validar-asignacion")
async def validar_asignacion(
    data: dict,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exigir_permiso_auxiliar(usuario, "AUD-038")
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
async def validar_asignacion_por_nit(
    data: dict,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exigir_permiso_auxiliar(usuario, "AUD-038")
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
