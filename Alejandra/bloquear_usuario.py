import sqlite3
from datetime import datetime, timedelta, timezone

def bloquear_usuario_temporalmente(user_id: int, minutos: int = 15) -> bool:
    """Guarda la fecha límite de bloqueo en la BD y desactiva la cuenta."""
    conn = sqlite3.connect("seguridad.db")
    cursor = conn.cursor()
    tiempo_bloqueo = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    
    cursor.execute("""
        UPDATE usuarios 
        SET blocked_until = ?, is_active = 0 
        WHERE id = ?
    """, (tiempo_bloqueo.isoformat(), user_id))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated