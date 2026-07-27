from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def cerrar_todas_las_sesiones(user_id: int, db: AsyncSession) -> bool:
    """
    Incrementa 'token_version'. Cualquier token o sesión activa 
    con una versión previa quedará invalidada automáticamente.
    """
    query = text("""
        UPDATE usuario 
        SET token_version = COALESCE(token_version, 1) + 1 
        WHERE id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    await db.commit()
    return result.rowcount > 0