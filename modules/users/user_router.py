from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.users.user_schema import UserCreate, UserResponse
from modules.users.user_service import UserService

router = APIRouter(prefix="/users", tags=["Usuarios"])

@router.get("/all-users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def read_users(db: AsyncSession = Depends(get_db)):
    service = UserService(db)
    return await service.get_all_users()

@router.post("/create-user", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def add_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    service = UserService(db)
    return await service.create_user(user_in)

