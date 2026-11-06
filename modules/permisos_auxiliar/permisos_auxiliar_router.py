"""
Endpoints para que el Administrador otorgue y retire permisos al Auxiliar.

Todas las rutas son solo del rol Administrador, salvo GET /mios, con la que
el auxiliar consulta los permisos que tiene vigentes.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user, require_role
from modules.permisos_auxiliar.permisos_auxiliar_service import (
    PermisosAuxiliarService,
    permisos_delegables,
)

router = APIRouter(prefix="/api/permisos-auxiliar", tags=["Permisos delegados al Auxiliar"])

# El rol Super Administrador ya no se usa: solo el Administrador delega.
solo_admin = require_role(["admin"])


class Otorgamiento(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    codigo_permiso: str = Field(..., min_length=3, max_length=30)
    motivo: str = Field(..., min_length=5, max_length=500)
    fecha_vencimiento: Optional[date] = None


class Revocacion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    motivo: str = Field(..., min_length=5, max_length=500)


@router.get("/catalogo", summary="Catálogo de permisos delegables, agrupado por módulo")
async def catalogo(_: dict = Depends(solo_admin)):
    grupos: dict[str, list[dict]] = {}
    for item in permisos_delegables():
        grupos.setdefault(item["modulo"], []).append(item)
    return {
        "total": sum(len(v) for v in grupos.values()),
        "modulos": [{"modulo": m, "permisos": p} for m, p in grupos.items()],
    }


@router.get("/auxiliares", summary="Listar usuarios con rol Auxiliar")
async def listar_auxiliares(db: AsyncSession = Depends(get_db), _: dict = Depends(solo_admin)):
    return await PermisosAuxiliarService(db).listar_auxiliares()


@router.get("/mios", summary="Permisos delegados vigentes del usuario actual")
async def mis_permisos(db: AsyncSession = Depends(get_db), usuario: dict = Depends(get_current_user)):
    permisos = await PermisosAuxiliarService(db).mios(usuario)
    return {"codigos": [p["codigo_permiso"] for p in permisos], "permisos": permisos}


@router.get("/historial", summary="Historial de otorgamientos, revocaciones y usos")
async def historial(
    id_usuario: Optional[UUID] = Query(default=None),
    limite: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(solo_admin),
):
    return await PermisosAuxiliarService(db).historial(id_usuario, limite)


@router.get("/auxiliares/{id_usuario}", summary="Permisos de un auxiliar")
async def permisos_de(id_usuario: UUID, db: AsyncSession = Depends(get_db), _: dict = Depends(solo_admin)):
    return await PermisosAuxiliarService(db).permisos_de(id_usuario)


@router.post("/auxiliares/{id_usuario}/otorgar", status_code=201, summary="Otorgar un permiso")
async def otorgar(
    id_usuario: UUID,
    data: Otorgamiento,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(solo_admin),
):
    return await PermisosAuxiliarService(db).otorgar(
        id_usuario, data.codigo_permiso, data.motivo, data.fecha_vencimiento, admin
    )


@router.post("/auxiliares/{id_usuario}/revocar/{codigo_permiso}", summary="Revocar un permiso")
async def revocar(
    id_usuario: UUID,
    codigo_permiso: str,
    data: Revocacion,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(solo_admin),
):
    return await PermisosAuxiliarService(db).revocar(id_usuario, codigo_permiso, data.motivo, admin)
