from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def bloquear_usuario_temporalmente(user_id: int, db: AsyncSession, minutos: int = 15) -> bool:
    """
    Establece la fecha/hora UTC hasta la que el usuario estará bloqueado y cambia su estado.
    """
    tiempo_bloqueo = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    
    query = text("""
        UPDATE usuario 
        SET bloqueado_hasta = :bloqueado_hasta, 
            estado = 'Inactivo' 
        WHERE id = :user_id
    """)
    result = await db.execute(query, {
        "bloqueado_hasta": tiempo_bloqueo, 
        "user_id": user_id
    })
    await db.commit()
    return result.rowcount > 0