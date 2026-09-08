<<<<<<< HEAD
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.empresas.constancia_pdf import generar_pdf_constancia
=======
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user, require_role
>>>>>>> 533fbb2 (Modulos empresa y apelaciones)
from modules.empresas.empresas_service import EmpresasService

router = APIRouter(prefix="/api/empresas", tags=["Empresas"])


class EmpresaCreate(BaseModel):
    nombre: str
    nit: str
    ciudad: str
    direccion: str
    correo: EmailStr


class EmpresaUpdate(BaseModel):
    nombre: str
    nit: str
    ciudad: str
    direccion: str
    correo: EmailStr


class SedeCreate(BaseModel):
    nombre_sede: str
    direccion: str
    ciudad: str
    departamento: Optional[str] = None
    pais: Optional[str] = None
    es_principal: bool = False
    estado: str = "Activo"


class SedeUpdate(BaseModel):
    nombre_sede: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    pais: Optional[str] = None
    es_principal: Optional[bool] = None
    estado: Optional[str] = None


@router.get("/")
async def get_empresas(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "auditor", "empresa"]))
):
    return await EmpresasService(db).get_all_empresas()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_empresa(
    data: EmpresaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    return await EmpresasService(db).create_empresa(data.model_dump())


@router.get("/{id_empresa}")
async def get_empresa(
    id_empresa: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "auditor", "empresa"]))
):
    empresa = await EmpresasService(db).get_empresa_by_id(id_empresa)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return empresa


@router.put("/{id_empresa}")
async def update_empresa(
    id_empresa: int,
    data: EmpresaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    updated = await EmpresasService(db).update_empresa(id_empresa, data.model_dump())
    if not updated:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return updated


@router.get("/{id_empresa}/solicitudes")
async def get_historial_empresa(
    id_empresa: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite"]))
):
    return await EmpresasService(db).get_historial_solicitudes_by_empresa(id_empresa)


@router.get("/{id_empresa}/sedes")
async def get_sedes_empresa(
    id_empresa: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite"]))
):
    return await EmpresasService(db).get_sedes_by_empresa(id_empresa)


@router.post("/{id_empresa}/sedes", status_code=status.HTTP_201_CREATED)
async def create_sede_empresa(
    id_empresa: int,
    data: SedeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    sede = await EmpresasService(db).create_sede(id_empresa, data.model_dump())
    if not sede:
        raise HTTPException(status_code=404, detail="No se pudo crear la sede")
    return sede


@router.get("/{id_empresa}/sedes/{id_sede}")
async def get_sede_empresa(
    id_empresa: int,
    id_sede: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa", "auditor", "comite"]))
):
    sede = await EmpresasService(db).get_sede_by_id(id_empresa, id_sede)
    if not sede:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return sede


@router.put("/{id_empresa}/sedes/{id_sede}")
async def update_sede_empresa(
    id_empresa: int,
    id_sede: int,
    data: SedeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    updated = await EmpresasService(db).update_sede(id_empresa, id_sede, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return updated


@router.delete("/{id_empresa}/sedes/{id_sede}")
async def delete_sede_empresa(
    id_empresa: int,
    id_sede: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    deleted = await EmpresasService(db).delete_sede(id_empresa, id_sede)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    return {"message": "Sede eliminada correctamente", "sede": deleted}


@router.get("/{id_empresa}/documentos")
async def get_documentos_empresa(
    id_empresa: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(["superadmin", "admin", "auxiliar", "empresa"]))
):
    return await EmpresasService(db).get_documentos_by_empresa(id_empresa)
