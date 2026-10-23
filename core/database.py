from typing import AsyncGenerator
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from core.config import settings
from core.logger import logger

engine = create_async_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except HTTPException:
            # Errores de negocio esperados (400/403/404): no son fallos de la DB.
            await session.rollback()
            raise
        except Exception as e:
            logger.exception(f"Error en la sesión de DB: {str(e)}")
            await session.rollback()
            raise e
        finally:
            await session.close()
