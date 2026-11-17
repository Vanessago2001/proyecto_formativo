"""
Rol único del auditor en una solicitud o visita.

Decisión de la usuaria (17/11/2026): "Quitar los roles del auditor y dejar
solo 'Auditor' para todo, así no hay errores de observador o auditor líder."

  · Ya no se elige rol al asignar ni al programar: todo se guarda como
    'Auditor'.
  · Los datos viejos ('Auditor líder', 'Observador', 'Experto técnicos',
    'Auditor Técnico'...) NO se cambian en la base: el código los lee todos
    como 'Auditor' (`normalizar_rol_auditor`).
  · `detalle_programacion_auditor.rol_auditor` tiene el CHECK
    chk_rol_auditor ('Auditor Líder', 'Auditor Técnico', 'Observador'), que
    no admite 'Auditor'. Mientras la usuaria no aplique
    documentacion/sql_rol_auditor_unico.sql se guarda ahí ROL_DETALLE_BD (un
    valor permitido que nunca se muestra). Tras aplicar el SQL basta cambiar
    ROL_DETALLE_BD a ROL_AUDITOR.
"""

ROL_AUDITOR = "Auditor"

# Valor guardado en detalle_programacion_auditor.rol_auditor. Cambiar a
# ROL_AUDITOR después de aplicar documentacion/sql_rol_auditor_unico.sql.
ROL_DETALLE_BD = "Auditor Técnico"


def normalizar_rol_auditor(_rol=None) -> str:
    """Cualquier rol guardado (o ninguno) se muestra como 'Auditor'."""
    return ROL_AUDITOR
