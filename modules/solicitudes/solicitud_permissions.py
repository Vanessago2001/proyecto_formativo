"""
M5 — GESTIÓN DE SOLICITUDES
Catálogo de permisos y matriz de roles.

Bloque 1: SOL-001 a SOL-010 (ciclo de vida).
Bloque 2: SOL-011 a SOL-020 (información general).
Bloque 3: SOL-021 a SOL-030 (sedes de la solicitud).
Bloque 4: SOL-031 a SOL-040 (documentos adjuntos).
Bloque 5: SOL-041 a SOL-050 (asignación de auditores).
Bloque 6: SOL-051 a SOL-060 (trazabilidad, bitácora y cierre).
Bloque 7: SOL-061 a SOL-070 (cálculo del tiempo de auditoría).

La fuente de verdad es la hoja "M5 — GESTIÓN DE SOLICITUDES" del archivo
documentacion/permisos.xlsx. Este módulo traduce esa matriz a código para que
los endpoints no repitan reglas de autorización dispersas.

Se distinguen dos cosas que no son lo mismo:

  · Las COLUMNAS de la hoja de cálculo (SUPERADM, ADM, AUX, EMP, AUD, COM,
    APR, PUB). Son ocho y se conservan tal cual para poder contrastar el
    código contra el Excel celda por celda.

  · Los ROLES reales de la tabla `rol`. Son siete, porque el aprobador no es
    un rol aparte: **el aprobador es el administrador**. La columna APR no
    tiene rol propio y sus permisos quedan cubiertos por la columna ADM.

Códigos usados en las celdas del Excel:

    V    -> El rol tiene el permiso.
    F    -> El rol NO tiene el permiso.
    REQ  -> El rol lo tiene, pero requiere aprobación de un superior.
            Se trata como concedido a nivel de endpoint y se marca en la
            respuesta para que el flujo de aprobación lo procese después.
    SA   -> Exclusivo del SuperAdministrador.
"""

from enum import Enum

from fastapi import Depends, HTTPException, status

from core.security import get_current_user


class NivelPermiso(str, Enum):
    """Valores posibles de una celda de la matriz de permisos."""

    CONCEDIDO = "V"
    DENEGADO = "F"
    REQUIERE_APROBACION = "REQ"
    SOLO_SUPERADMIN = "SA"


# ============================================================
# COLUMNAS DE LA HOJA DE CÁLCULO
# ============================================================
# Siglas tal como aparecen en el encabezado del Excel.

COL_SUPERADM = "SUPERADM"
COL_ADM = "ADM"
COL_AUX = "AUX"
COL_EMP = "EMP"
COL_AUD = "AUD"
COL_COM = "COM"
COL_APR = "APR"
COL_PUB = "PUB"

# Orden EXACTO de las columnas de la hoja. No reordenar: las filas de
# PERMISOS_M5 se leen posicionalmente contra esta tupla.
COLUMNAS_MATRIZ = (
    COL_SUPERADM,
    COL_ADM,
    COL_AUX,
    COL_EMP,
    COL_AUD,
    COL_COM,
    COL_APR,
    COL_PUB,
)


# ============================================================
# ROLES REALES DE LA TABLA `rol`
# ============================================================
# Los nombres se escriben igual que están en la base de datos.

ROL_SUPERADM = "Super Administrador"
ROL_ADM = "Administrador"
ROL_AUX = "Auxiliar"
ROL_EMP = "Empresa"
ROL_AUD = "Auditor"
ROL_COM = "Comité"
ROL_PUB = "Publico"

ROLES_DEL_SISTEMA = (
    ROL_SUPERADM,
    ROL_ADM,
    ROL_AUX,
    ROL_EMP,
    ROL_AUD,
    ROL_COM,
    ROL_PUB,
)

# Qué columna de la matriz le corresponde a cada rol.
#
# El administrador toma la columna ADM, que además cubre a APR: en las 70
# filas de M5 no hay ninguna donde APR conceda algo que ADM no conceda, así
# que unificarlos no le quita ningún permiso a nadie.
ROLES_A_COLUMNA = {
    ROL_SUPERADM: COL_SUPERADM,
    ROL_ADM: COL_ADM,
    ROL_AUX: COL_AUX,
    ROL_EMP: COL_EMP,
    ROL_AUD: COL_AUD,
    ROL_COM: COL_COM,
    ROL_PUB: COL_PUB,
}

# Alias tolerante: el equipo ha escrito los roles de varias formas distintas
# (con tilde, en minúscula, abreviados). Todo se normaliza al nombre real.
ALIAS_ROLES = {
    "super administrador": ROL_SUPERADM,
    "superadministrador": ROL_SUPERADM,
    "superadmin": ROL_SUPERADM,
    "superadm": ROL_SUPERADM,
    "administrador": ROL_ADM,
    "admin": ROL_ADM,
    "adm": ROL_ADM,
    # El aprobador no es un rol aparte: es el administrador.
    "aprobador": ROL_ADM,
    "apr": ROL_ADM,
    "auxiliar": ROL_AUX,
    "aux": ROL_AUX,
    "empresa": ROL_EMP,
    "emp": ROL_EMP,
    "auditor": ROL_AUD,
    "aud": ROL_AUD,
    "comite": ROL_COM,
    "comité": ROL_COM,
    "comite de certificacion": ROL_COM,
    "com": ROL_COM,
    "publico": ROL_PUB,
    "público": ROL_PUB,
    "pub": ROL_PUB,
}


def normalizar_rol(nombre_rol: str | None) -> str | None:
    """Convierte cualquier variante escrita del rol a su nombre real."""
    if not nombre_rol:
        return None
    return ALIAS_ROLES.get(nombre_rol.strip().lower())


def columna_de_rol(nombre_rol: str | None) -> str | None:
    """Devuelve la columna de la matriz que le aplica a un rol."""
    return ROLES_A_COLUMNA.get(normalizar_rol(nombre_rol))


# ============================================================
# MATRIZ DE PERMISOS — BLOQUES 1 A 7
# ============================================================
# Transcripción literal de la hoja de cálculo.
# Cada fila: código -> (descripción, valores en el orden de COLUMNAS_MATRIZ)

V = NivelPermiso.CONCEDIDO
F = NivelPermiso.DENEGADO
REQ = NivelPermiso.REQUIERE_APROBACION
SA = NivelPermiso.SOLO_SUPERADMIN

PERMISOS_M5: dict[str, tuple[str, tuple[NivelPermiso, ...]]] = {
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-001": ("Crear solicitud",                    (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-002": ("Guardar borrador",                   (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-003": ("Editar borrador",                    (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-004": ("Eliminar borrador",                  (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-005": ("Radicar solicitud formalmente",      (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-006": ("Consultar solicitud radicada",       (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-007": ("Descargar solicitud en PDF",         (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-008": ("Duplicar solicitud",                 (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-009": ("Cancelar solicitud antes de revisión",(V, F,  F,  V,  F,  F,  F,  F)),
    "SOL-010": ("Consultar estado de solicitud",      (V,  V,  V,  V,  V,  V,  V,  F)),

    # ---- BLOQUE 2: información general (SOL-011 a SOL-020) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-011": ("Registrar norma ISO solicitada",     (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-012": ("Editar norma ISO",                   (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-013": ("Registrar alcance técnico",          (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-014": ("Editar alcance",                     (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-015": ("Registrar procesos clave",           (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-016": ("Editar procesos",                    (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-017": ("Registrar número de empleados",      (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-018": ("Editar número de empleados",         (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-019": ("Registrar número de sedes",          (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-020": ("Consultar información general",      (V,  V,  V,  V,  V,  V,  V,  F)),

    # ---- BLOQUE 3: sedes de la solicitud (SOL-021 a SOL-030) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-021": ("Agregar sede a la solicitud",        (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-022": ("Editar sede en solicitud",           (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-023": ("Eliminar sede de la solicitud",      (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-024": ("Registrar dirección de sede",        (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-025": ("Editar dirección de sede",           (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-026": ("Registrar ciudad de la sede",        (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-027": ("Registrar departamento",             (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-028": ("Consultar sedes añadidas",           (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-029": ("Validar sedes (Administración)",     (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-030": ("Exportar sedes a Excel",             (V,  V,  V,  V,  F,  F,  F,  F)),

    # ---- BLOQUE 4: documentos adjuntos (SOL-031 a SOL-040) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-031": ("Subir documento requerido",          (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-032": ("Reemplazar documento legal",         (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-033": ("Eliminar documento técnico",         (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-034": ("Descargar documento adjunto",        (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-035": ("Consultar documento en visor",       (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-036": ("Validar formato (Automático)",       (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-037": ("Rechazar documento",                 (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-038": ("Aprobar documento adjunto",          (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-039": ("Solicitar corrección",               (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-040": ("Consultar historial documental",     (V,  V,  V,  V,  F,  F,  V,  F)),

    # ---- BLOQUE 5: asignación de auditores (SOL-041 a SOL-050) ----
    # La búsqueda y los filtros los hace la administración sobre el banco de
    # auditores de M4; la empresa nunca elige quién la audita.
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-041": ("Buscar auditores competentes",       (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-042": ("Filtrar por norma ISO",              (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-043": ("Filtrar por sector IAF",             (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-044": ("Filtrar por ciudad",                 (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-045": ("Filtrar por disponibilidad",         (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-046": ("Filtrar descartando conflictos",     (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-047": ("Proponer auditor para el servicio",  (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-048": ("Aprobar asignación de auditor",      (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-049": ("Reasignar auditor",                  (SA, F,  REQ,F,  F,  F,  F,  F)),
    "SOL-050": ("Cancelar asignación",                (V,  V,  REQ,F,  F,  F,  F,  F)),

    # ---- BLOQUE 6: trazabilidad y cierre (SOL-051 a SOL-060) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-051": ("Consultar historial de solicitud",   (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-052": ("Registrar observación de control",   (V,  V,  V,  F,  V,  F,  F,  F)),
    "SOL-053": ("Consultar observaciones",            (V,  V,  V,  V,  V,  V,  V,  F)),
    "SOL-054": ("Cambiar estado de solicitud",        (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-055": ("Consultar bitácora inmutable",       (V,  V,  V,  F,  F,  F,  V,  F)),
    "SOL-056": ("Exportar historial de solicitudes",  (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-057": ("Imprimir solicitud completa",        (V,  V,  V,  V,  F,  F,  F,  F)),
    "SOL-058": ("Compartir expediente con Comité",    (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-059": ("Generar reporte del módulo",         (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-060": ("Cerrar solicitud definitivamente",   (V,  V,  REQ,F,  F,  F,  F,  F)),

    # ---- BLOQUE 7: cálculo del tiempo de auditoría (SOL-061 a SOL-070) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-061": ("Registrar variables para cálculo",   (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-062": ("Calcular tiempo (Fórmula)",          (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-063": ("Recalcular tiempo de auditoría",     (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-064": ("Consultar resultado del cálculo",    (V,  V,  V,  F,  V,  V,  V,  F)),
    "SOL-065": ("Justificar ajustes de tiempo",       (V,  SA, REQ,F,  F,  F,  F,  F)),
    "SOL-066": ("Modificar variables base",           (V,  SA, F,  F,  F,  F,  F,  F)),
    "SOL-067": ("Consultar historial matemático",     (V,  V,  V,  F,  F,  F,  V,  F)),
    "SOL-068": ("Exportar desglose de cálculo",       (V,  V,  REQ,F,  F,  F,  F,  F)),
    "SOL-069": ("Validar cálculo antes de asignar",   (V,  V,  V,  F,  F,  F,  F,  F)),
    "SOL-070": ("Bloquear cambios tras aprobación",   (V,  V,  V,  V,  V,  V,  V,  F)),
}


def nivel_permiso(codigo: str, nombre_rol: str | None) -> NivelPermiso:
    """Devuelve el nivel que la matriz asigna a `nombre_rol` para `codigo`."""
    if codigo not in PERMISOS_M5:
        raise KeyError(f"El permiso {codigo} no existe en la matriz de M5.")

    columna = columna_de_rol(nombre_rol)
    if columna is None:
        return NivelPermiso.DENEGADO

    _, valores = PERMISOS_M5[codigo]
    return valores[COLUMNAS_MATRIZ.index(columna)]


def tiene_permiso(codigo: str, nombre_rol: str | None) -> bool:
    """True si el rol puede ejecutar la acción (aunque requiera aprobación)."""
    nivel = nivel_permiso(codigo, nombre_rol)

    if nivel is NivelPermiso.DENEGADO:
        return False

    if nivel is NivelPermiso.SOLO_SUPERADMIN:
        return normalizar_rol(nombre_rol) == ROL_SUPERADM

    return True


def _permiso_denegado(codigo: str, nombre_rol: str | None) -> HTTPException:
    """403 que indica exactamente qué permiso faltó y para qué rol."""
    descripcion = PERMISOS_M5[codigo][0]
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Permiso {codigo} ({descripcion}) denegado "
            f"para el rol '{nombre_rol or 'sin rol'}'."
        ),
    )


def exigir_permisos(usuario: dict, *codigos: str) -> None:
    """
    Verifica permisos adicionales desde dentro de una operación.

    `requiere_permiso` protege cada endpoint con un único código, pero algunas
    acciones ejecutan varios permisos de la hoja a la vez: agregar una sede
    nueva (SOL-021) también registra su dirección (SOL-024) y su ciudad
    (SOL-026).
    """
    nombre_rol = usuario.get("role_name")
    for codigo in codigos:
        if not tiene_permiso(codigo, nombre_rol):
            raise _permiso_denegado(codigo, nombre_rol)


def requiere_permiso(codigo: str):
    """
    Fábrica de dependencias de FastAPI que protege un endpoint con un código
    de la matriz.

        @router.post("/")
        async def crear(usuario: dict = Depends(requiere_permiso("SOL-001"))):

    Se usa como dependencia con `Depends(...)` para que el usuario autenticado
    quede disponible en el endpoint.
    """

    async def verificar(current_user: dict = Depends(get_current_user)) -> dict:
        # `get_current_user` expone el rol como `role_name`.
        nombre_rol = current_user.get("role_name")

        if not tiene_permiso(codigo, nombre_rol):
            raise _permiso_denegado(codigo, nombre_rol)

        # Se adjunta el nivel para que el servicio sepa si la acción queda
        # pendiente de aprobación (REQ) o se aplica de inmediato (V / SA).
        return {
            **current_user,
            "permiso_codigo": codigo,
            "permiso_nivel": nivel_permiso(codigo, nombre_rol).value,
        }

    return verificar
