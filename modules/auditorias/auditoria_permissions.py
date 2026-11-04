"""
M7 — AUDITORÍAS
Catálogo de permisos y matriz de roles.

Igual que en M5, la fuente de verdad es la hoja "M7 — AUDITORÍAS" del archivo
documentacion/permisos.xlsx, y esta matriz es su transcripción literal: una
prueba compara celda por celda las dos, así que si el Excel cambia, la prueba
avisa.

Bloque 1: AUT-001 a AUT-010 (ejecución de la auditoría de campo).
Bloque 2: AUT-011 a AUT-020 (evaluación por requisito).
Bloque 3: AUT-021 a AUT-030 (hallazgos).
Bloque 4: AUT-031 a AUT-040 (evidencias).
Bloque 5: AUT-041 a AUT-050 (informe de auditoría).
Bloque 6: AUT-051 a AUT-060 (seguimiento y cierre).
Bloque 7: AUT-061 a AUT-070 (jornadas, firma y envío al Comité).

AVISO SOBRE LA HOJA
-------------------
En la hoja de M7, la columna COM concede 62 de los 70 permisos y la columna
AUD solo 12: la auditoría de campo (iniciarla, evaluar requisitos, registrar
hallazgos) queda a nombre del Comité y no del Auditor. En la hoja de M8 pasa
lo simétrico: la columna COM no concede ninguno de sus 30 permisos. Todo
apunta a que en esas dos hojas se desplazaron las columnas al llenarlas.

Aquí se transcribe lo que dice el Excel, sin corregirlo por cuenta propia:
el día que la institución ajuste la hoja, basta con volver a transcribirla y
la prueba de contraste lo confirma. Mientras tanto, `ROLES_EJECUTAN_CAMPO`
deja ver de un vistazo quién puede ejecutar la auditoría según la matriz.
"""


from fastapi import Depends, HTTPException, status

from core.security import get_current_user
from modules.solicitudes.solicitud_permissions import (
    COLUMNAS_MATRIZ,
    NivelPermiso,
    ROL_SUPERADM,
    columna_de_rol,
    normalizar_rol,
)

V = NivelPermiso.CONCEDIDO
F = NivelPermiso.DENEGADO
REQ = NivelPermiso.REQUIERE_APROBACION
SA = NivelPermiso.SOLO_SUPERADMIN


PERMISOS_M7: dict[str, tuple[str, tuple[NivelPermiso, ...]]] = {
    # ---- BLOQUE 1: ejecución de la auditoría de campo (AUT-001 a AUT-010) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-001": ("Iniciar auditoría de campo",       (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-002": ("Consultar solicitud asignada",     (V  , F  , F  , F  , F  , V  , F  , V)),
    "AUT-003": ("Consultar info de la empresa",     (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-004": ("Consultar sedes añadidas",         (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-005": ("Consultar alcance certificación",  (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-006": ("Consultar procesos empresariales", (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-007": ("Descargar expediente previo",      (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-008": ("Confirmar inicio formal",          (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-009": ("Registrar observaciones iniciales", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-010": ("Suspender auditoría por anomalía", (SA , F  , REQ, F  , F  , V  , F  , F)),

    # ---- BLOQUE 2: evaluación por requisito (AUT-011 a AUT-020) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-011": ("Registrar evaluación por requisito", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-012": ("Editar evaluación (Autoguardado)", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-013": ("Eliminar evaluación pendiente",    (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-014": ("Registrar requisito de control",   (V  , V  , REQ, F  , F  , F  , F  , F)),
    "AUT-015": ('Marcar "Cumple" el requisito',     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-016": ('Marcar "No Cumple" el requisito',  (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-017": ('Marcar "No Aplica" el requisito',  (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-018": ("Registrar mejora (OFI)",           (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-019": ("Registrar comentario técnico",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-020": ("Consultar evaluación tiempo real", (V  , V  , V  , F  , F  , V  , F  , V)),

    # ---- BLOQUE 3: hallazgos (AUT-021 a AUT-030) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-021": ("Registrar hallazgo específico",    (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-022": ("Editar hallazgo registrado",       (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-023": ("Eliminar hallazgo pendiente",      (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-024": ("Clasificar hallazgo (Mayor / Menor)", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-025": ("Registrar no conformidad formal",  (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-026": ("Registrar observación formal",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-027": ("Registrar oportunidad de mejora",  (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-028": ("Adjuntar requisito relacionado",   (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-029": ("Consultar hallazgos consolidados", (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-030": ("Exportar hallazgos a inf. preliminar", (V  , V  , V  , F  , F  , V  , F  , F)),

    # ---- BLOQUE 4: evidencias (AUT-031 a AUT-040) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-031": ("Subir evidencia (Fotos/PDF)",      (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-032": ("Descargar evidencia cargada",      (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-033": ("Reemplazar evidencia técnica",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-034": ("Eliminar evidencia pendiente",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-035": ("Consultar evidencia online",       (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-036": ("Asociar evidencia al requisito",   (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-037": ("Validar integridad de evidencia",  (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-038": ("Registrar observaciones evidencia", (V  , V  , V  , F  , F  , V  , F  , F)),
    "AUT-039": ("Exportar paquete de evidencias",   (V  , V  , REQ, F  , F  , V  , F  , F)),
    "AUT-040": ("Ver historial de carga",           (V  , V  , V  , F  , F  , V  , F  , V)),

    # ---- BLOQUE 5: informe de auditoría (AUT-041 a AUT-050) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-041": ("Generar borrador del informe",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-042": ("Editar informe final en redacción", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-043": ("Guardar borrador del informe",     (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-044": ("Finalizar informe (Inmutabilidad)", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-045": ("Descargar informe definitivo PDF", (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-046": ("Imprimir informe técnico",         (V  , V  , V  , V  , V  , V  , F  , F)),
    "AUT-047": ("Enviar informe oficial al Comité", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-048": ("Consultar informe de auditoría final", (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-049": ("Exportar informe PDF firmado",     (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-050": ("Firmar electrónicamente (Auditor)", (V  , F  , F  , F  , F  , V  , F  , F)),

    # ---- BLOQUE 6: seguimiento y cierre (AUT-051 a AUT-060) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-051": ("Consultar auditorías (Historial)", (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-052": ("Consultar historial inmutable",    (V  , V  , V  , F  , F  , F  , F  , V)),
    "AUT-053": ("Registrar acciones seguimiento",   (V  , V  , V  , F  , F  , V  , F  , F)),
    "AUT-054": ("Consultar acciones seguimiento",   (V  , V  , V  , V  , V  , V  , F  , V)),
    "AUT-055": ("Registrar acciones correctivas",   (V  , F  , F  , F  , V  , F  , F  , F)),
    "AUT-056": ("Consultar plan acciones corr.",    (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-057": ("Cerrar auditoría formalmente",     (V  , V  , REQ, F  , F  , F  , F  , F)),
    "AUT-058": ("Reabrir auditoría (Justificado)",  (SA , F  , F  , F  , F  , F  , F  , F)),
    "AUT-059": ("Generar estadísticas de hallazgos", (V  , V  , V  , F  , F  , F  , F  , F)),
    "AUT-060": ("Exportar estadísticas del módulo", (V  , V  , REQ, F  , F  , F  , F  , F)),

    # ---- BLOQUE 7: jornadas, firma y envío al Comité (AUT-061 a AUT-070) ----
    #                                          SUPERADM ADM AUX EMP AUD COM APR PUB
    "AUT-061": ("Registrar hora de inicio en campo", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-062": ("Registrar hora finalización diaria", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-063": ("Consultar duración total",         (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-064": ("Registrar incidencias en sitio",   (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-065": ("Registrar observaciones de cierre", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-066": ("Adjuntar anexos al cierre",        (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-067": ("Verificar integridad digital",     (V  , V  , V  , F  , F  , V  , F  , V)),
    "AUT-068": ("Confirmar envío formal al Comité", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-069": ("Registrar firma digital del auditor", (V  , F  , F  , F  , F  , V  , F  , F)),
    "AUT-070": ("Cerrar expediente para votación",  (V  , V  , REQ, F  , F  , F  , F  , F)),
}


def nivel_permiso(codigo: str, nombre_rol: str | None) -> NivelPermiso:
    """Nivel que la matriz asigna a `nombre_rol` para `codigo`."""
    if codigo not in PERMISOS_M7:
        raise KeyError(f"El permiso {codigo} no existe en la matriz de M7.")

    columna = columna_de_rol(nombre_rol)
    if columna is None:
        return NivelPermiso.DENEGADO

    _, valores = PERMISOS_M7[codigo]
    return valores[COLUMNAS_MATRIZ.index(columna)]


def tiene_permiso(codigo: str, nombre_rol: str | None) -> bool:
    """True si el rol puede ejecutar la acción (aunque requiera aprobación)."""
    nivel = nivel_permiso(codigo, nombre_rol)

    if nivel is NivelPermiso.DENEGADO:
        return False

    if nivel is NivelPermiso.SOLO_SUPERADMIN:
        return normalizar_rol(nombre_rol) == ROL_SUPERADM

    return True


# Quién ejecuta la auditoría de campo según la matriz vigente (AUT-001).
ROLES_EJECUTAN_CAMPO = tuple(
    columna
    for columna, nivel in zip(COLUMNAS_MATRIZ, PERMISOS_M7["AUT-001"][1])
    if nivel is not NivelPermiso.DENEGADO
)


def _permiso_denegado(codigo: str, nombre_rol: str | None) -> HTTPException:
    descripcion = PERMISOS_M7[codigo][0]
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Permiso {codigo} ({descripcion}) denegado "
            f"para el rol '{nombre_rol or 'sin rol'}'."
        ),
    )


def exigir_permisos(usuario: dict, *codigos: str) -> None:
    """Verifica permisos adicionales desde dentro de una operación."""
    nombre_rol = usuario.get("role_name")
    for codigo in codigos:
        if not tiene_permiso(codigo, nombre_rol):
            raise _permiso_denegado(codigo, nombre_rol)


def requiere_permiso(codigo: str):
    """Dependencia de FastAPI que protege un endpoint con un código de M7."""

    async def verificar(current_user: dict = Depends(get_current_user)) -> dict:
        nombre_rol = current_user.get("role_name")

        if not tiene_permiso(codigo, nombre_rol):
            raise _permiso_denegado(codigo, nombre_rol)

        return {
            **current_user,
            "permiso_codigo": codigo,
            "permiso_nivel": nivel_permiso(codigo, nombre_rol).value,
        }

    return verificar
