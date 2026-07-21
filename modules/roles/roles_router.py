from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.security import get_current_user
from modules.roles.roles_schema import RoleCreate, RoleResponse
from modules.roles.roles_service import RoleService

router = APIRouter(prefix="/roles", tags=["Roles"])

@router.get("/", response_model=list[RoleResponse], status_code=status.HTTP_200_OK)
async def read_roles(
    db: AsyncSession = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """Acceso restringido: Solo Administradores pueden listar roles."""
    if current_user["role_name"] != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado. Rol insuficiente.")
    service = RoleService(db)
    return await service.get_all_roles()

@router.get("/get-by-name", response_model=list[RoleResponse], status_code=status.HTTP_200_OK)
async def read_roles_by_name(nom:str, db: AsyncSession = Depends(get_db)):
    service = RoleService(db)
    return await service.get_role_by_name(nom)

@router.get("/get-by-id", response_model=list[RoleResponse], status_code=status.HTTP_200_OK)
async def read_roles_by_id(id:int, db: AsyncSession = Depends(get_db)):
    service = RoleService(db)
    return await service.get_role_by_id(id)

@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def add_role(
    role_in: RoleCreate, 
    db: AsyncSession = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """Acceso restringido: Solo Administradores pueden registrar nuevos roles."""
    if current_user["role_name"] != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado. Rol insuficiente.")
    service = RoleService(db)
    return await service.create_role(role_in)

@router.delete("/", response_model=dict, status_code=status.HTTP_200_OK)
async def del_role_by_id(
    id:int, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
    ):
    if current_user["role_name"] != ("Administrador" or "instructor"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado. Rol insuficiente.")

    service = RoleService(db)
    return await service.delete_role_by_id(id)