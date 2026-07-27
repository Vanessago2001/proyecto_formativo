import sqlite3

def cerrar_todas_las_sesiones(user_id: int) -> bool:
    """Incrementa la versión del token para invalidar todas las sesiones previas."""
    conn = sqlite3.connect("seguridad.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE usuarios SET token_version = token_version + 1 WHERE id = ?", (user_id,))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated