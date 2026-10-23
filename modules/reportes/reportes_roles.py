"""
Catálogo de reportes y matriz de roles (M12).

Cada reporte declara qué roles pueden ejecutarlo y si su contenido se recorta
según quién consulta:

- `alcance_empresa`: una cuenta de empresa solo ve las filas de su propia
  empresa (resuelta por `user_empresa`), nunca las de las demás.
- `alcance_auditor`: un auditor solo ve lo que le corresponde (sus asignaciones,
  sus auditorías, su disponibilidad, sus apelaciones).

Los nombres de rol se guardan ya normalizados con `core.security`, que es quien
traduce "Super Administrador", "ADMIN" o "aud" a una forma canónica.
"""

SUPERADMIN = "superadmin"
ADMIN = "admin"
AUXILIAR = "auxiliar"
EMPRESA = "empresa"
AUDITOR = "auditor"
COMITE = "comite"

# Dirección y operación del sistema: ven todo el parque de empresas.
ROLES_DIRECCION = [SUPERADMIN, ADMIN, AUXILIAR]
# Órganos de control: vigilan auditorías, conflictos y apelaciones.
ROLES_CONTROL = [SUPERADMIN, ADMIN, COMITE]

CATALOGO_REPORTES: dict[str, dict] = {
    "estadistico-empresas": {
        "titulo": "Reporte estadístico de empresas",
        "descripcion": (
            "Parque de empresas con sus trámites radicados y certificados "
            "vigentes. Vista global de la operación."
        ),
        "roles": ROLES_DIRECCION,
        "alcance_empresa": False,
        "alcance_auditor": False,
    },
    "operativo-auditores": {
        "titulo": "Reporte operativo de auditores",
        "descripcion": (
            "Carga de trabajo por auditor: asignaciones, auditorías abiertas y "
            "cerradas. Un auditor solo ve su propia carga."
        ),
        "roles": [SUPERADMIN, ADMIN, AUDITOR],
        "alcance_empresa": False,
        "alcance_auditor": True,
    },
    "solicitudes-criticas": {
        "titulo": "Reporte de solicitudes críticas",
        "descripcion": (
            "Trámites abiertos con más de 30 días sin avanzar, ordenados por "
            "antigüedad. Una empresa ve solo los suyos."
        ),
        "roles": ROLES_DIRECCION + [EMPRESA],
        "alcance_empresa": True,
        "alcance_auditor": False,
    },
    "auditorias-ejecutadas": {
        "titulo": "Reporte de auditorías ejecutadas",
        "descripcion": (
            "Auditorías ya cerradas con su solicitud, empresa y auditor "
            "responsable. Un auditor solo ve las suyas."
        ),
        "roles": [SUPERADMIN, ADMIN, AUDITOR],
        "alcance_empresa": False,
        "alcance_auditor": True,
    },
    "certificados-vigentes": {
        "titulo": "Reporte de certificados vigentes",
        "descripcion": (
            "Certificados con fecha de vencimiento en el futuro, con días "
            "restantes. Una empresa ve solo los suyos."
        ),
        "roles": ROLES_DIRECCION + [AUDITOR, COMITE, EMPRESA],
        "alcance_empresa": True,
        "alcance_auditor": False,
    },
    "apelaciones-fallos": {
        "titulo": "Reporte de apelaciones y fallos",
        "descripcion": (
            "Apelaciones presentadas, quién las revisa y su sentido del fallo. "
            "Una empresa ve las suyas; un auditor, las que presentó o evalúa."
        ),
        "roles": ROLES_CONTROL + [EMPRESA, AUDITOR],
        "alcance_empresa": True,
        "alcance_auditor": True,
    },
    "preventivo-conflictos": {
        "titulo": "Reporte preventivo de conflictos",
        "descripcion": (
            "Declaraciones de conflicto de interés pendientes o que bloquean "
            "asignaciones, para evitar destinar un auditor impedido."
        ),
        "roles": ROLES_CONTROL,
        "alcance_empresa": False,
        "alcance_auditor": False,
    },
    "disponibilidad-horaria": {
        "titulo": "Reporte de disponibilidad horaria",
        "descripcion": (
            "Franjas declaradas por los auditores por día de semana, para "
            "programar visitas. Un auditor solo ve su disponibilidad."
        ),
        "roles": [SUPERADMIN, ADMIN, AUDITOR],
        "alcance_empresa": False,
        "alcance_auditor": True,
    },
    "critico-vencimiento": {
        "titulo": "Reporte crítico de vencimiento",
        "descripcion": (
            "Certificados que vencen en 90 días o menos, o ya vencidos, para "
            "gestionar renovaciones. Una empresa ve solo los suyos."
        ),
        "roles": ROLES_DIRECCION + [EMPRESA],
        "alcance_empresa": True,
        "alcance_auditor": False,
    },
}

# Días que faltan para el vencimiento a partir de los cuales un certificado
# entra al reporte crítico. Mismo criterio que el portal público (M11).
DIAS_VENCIMIENTO_CRITICO = 90

# Días sin avance a partir de los cuales una solicitud abierta es crítica.
DIAS_SOLICITUD_CRITICA = 30


def reporte_o_none(codigo: str) -> dict | None:
    return CATALOGO_REPORTES.get(codigo)


def roles_del_reporte(codigo: str) -> list[str]:
    return CATALOGO_REPORTES[codigo]["roles"]


def catalogo_para_rol(rol: str) -> list[dict]:
    """Los reportes que un rol puede ejecutar, para pintar su menú."""
    return [
        {"codigo": codigo, "titulo": datos["titulo"], "descripcion": datos["descripcion"]}
        for codigo, datos in CATALOGO_REPORTES.items()
        if rol in datos["roles"]
    ]
