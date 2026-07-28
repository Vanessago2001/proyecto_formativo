from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def desbloquear_usuario(user_id: int, db: AsyncSession) -> bool:
    """
    Limpia la fecha de bloqueo (NULL) y reactiva la cuenta del usuario.
    """
    query = text("""
        UPDATE usuario 
        SET bloqueado_hasta = NULL, 
            estado = 'Activo' 
        WHERE id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    await db.commit()
    return result.rowcount > 0