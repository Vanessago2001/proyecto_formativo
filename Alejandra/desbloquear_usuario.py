import sqlite3

def desbloquear_usuario(user_id: int) -> bool:
    """Limpia el bloqueo y vuelve a activar la cuenta del usuario."""
    conn = sqlite3.connect("seguridad.db")
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE usuarios 
        SET blocked_until = NULL, is_active = 1 
        WHERE id = ?
    """, (user_id,))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated