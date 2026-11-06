from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from core.security import get_current_user
from uuid import UUID

from modules.users.gestion_cuenta_service import GestionCuentaService
from modules.users.user_schema import (
    CambioCorreoCuenta,
    RestablecerPasswordCuenta,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from modules.users.user_service import UserService

router = APIRouter(prefix="/users", tags=["Usuarios"])


@router.get("/public-roles")
async def read_public_roles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("""
        -- DISTINCT ON evita que el selector muestre el mismo rol dos veces:
        -- la tabla `rol` no tiene restriccion UNIQUE sobre `nombre`, y ya han
        -- aparecido duplicados antes (ver los comentarios del seed en main.py).
        SELECT DISTINCT ON (nombre) id_rol, nombre
        FROM rol
        WHERE nombre IN ('Auditor', 'Empresa')
        ORDER BY nombre, id_rol;
    """))
    return [dict(row) for row in result.mappings().all()]


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_public_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    role_result = await db.execute(
        text("SELECT nombre FROM rol WHERE id_rol = :rol;"), {"rol": user_in.rol}
    )
    role_name = role_result.scalar_one_or_none()
    if role_name not in {"Auditor", "Empresa"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro publico solo esta disponible para auditores y empresas.",
        )
    return await UserService(db).create_user(user_in)


@router.get("/me", status_code=status.HTTP_200_OK)
async def read_current_user(current_user: dict = Depends(get_current_user)):
    """Datos de la cuenta autenticada para la vista de perfil."""
    return current_user

@router.get("/all-users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def read_users(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    if current_user.get("role_name") != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso exclusivo para administradores.")
    service = UserService(db)
    return await service.get_all_users()

@router.post("/create-user", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def add_user(user_in: UserCreate, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    if current_user.get("role_name") != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un administrador puede crear cuentas.")
    service = UserService(db)
    return await service.create_user(user_in)


@router.put("/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def edit_user(user_id: str, user_in: UserUpdate, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    if current_user.get("role_name") != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo un administrador puede modificar cuentas.")
    return await UserService(db).update_user(user_id, user_in, current_user)



# ============================================================
# GESTION DE ACCESO DE CUENTAS EMPRESA / AUDITOR (USR-CORREO, USR-CLAVE)
# ============================================================
# Los permisos (Administrador siempre; Auxiliar solo con el permiso delegado)
# se validan en GestionCuentaService, no solo ocultando el boton.

@router.put("/{user_id}/correo", status_code=status.HTTP_200_OK)
async def cambiar_correo_cuenta(
    user_id: UUID,
    data: CambioCorreoCuenta,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await GestionCuentaService(db).cambiar_correo(
        current_user, user_id, str(data.correo), data.motivo.strip()
    )


@router.post("/{user_id}/restablecer-password", status_code=status.HTTP_200_OK)
async def restablecer_password_cuenta(
    user_id: UUID,
    data: RestablecerPasswordCuenta,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await GestionCuentaService(db).restablecer_password(
        current_user, user_id, data.motivo.strip()
    )


@router.get("/{user_id}/historial-gestion", status_code=status.HTTP_200_OK)
async def historial_gestion_cuenta(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await GestionCuentaService(db).historial(current_user, user_id)
