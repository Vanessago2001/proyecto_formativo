"""M9 - Matriz de permisos para certificados."""

from fastapi import Depends, HTTPException, status

from core.security import get_current_user
from modules.solicitudes.solicitud_permissions import (
    COLUMNAS_MATRIZ,
    NivelPermiso,
    columna_de_rol,
    normalizar_rol,
)

V = NivelPermiso.CONCEDIDO
F = NivelPermiso.DENEGADO
REQ = NivelPermiso.REQUIERE_APROBACION
SA = NivelPermiso.SOLO_SUPERADMIN

PERMISOS_M9: dict[str, tuple[str, tuple[NivelPermiso, ...]]] = {
    #                                              SUPERADM ADM AUX EMP AUD COM APR PUB
    "CER-001": ("Generar certificado",                    (V, V, V, F, F, F, F, F)),
    "CER-002": ("Generar código único de radicado",       (V, V, V, F, F, F, F, F)),
    "CER-003": ("Asignar número correlativo",              (V, V, V, F, F, F, F, F)),
    "CER-004": ("Registrar fecha de emisión",              (V, V, V, F, F, F, F, F)),
    "CER-005": ("Registrar fecha de vencimiento",          (V, V, V, F, F, F, F, F)),
    "CER-006": ("Asociar empresa titular",                 (V, V, V, F, F, F, F, F)),
    "CER-007": ("Asociar norma ISO",                        (V, V, V, F, F, F, F, F)),
    "CER-008": ("Asociar alcance técnico",                  (V, V, V, F, F, F, F, F)),
    "CER-009": ("Generar archivo PDF oficial",              (V, V, V, F, F, F, F, F)),
    "CER-010": ("Firmar digitalmente certificado",          (V, V, REQ, F, F, F, F, F)),
    "CER-011": ("Consultar certificado expedido",           (V, V, V, V, V, V, F, V)),
    "CER-012": ("Descargar certificado PDF",                (V, V, V, V, V, V, F, V)),
    "CER-013": ("Reenviar certificado por correo",          (V, V, V, V, V, F, F, F)),
    "CER-014": ("Renovar certificado por ciclo",            (V, V, REQ, F, F, F, F, F)),
    "CER-015": ("Suspender certificado",                    (V, V, REQ, F, F, F, F, F)),
    "CER-016": ("Reactivar certificado suspendido",         (SA, V, F, F, F, V, F, F)),
    "CER-017": ("Cancelar o retirar certificado",           (SA, V, F, F, F, V, F, F)),
    "CER-018": ("Registrar motivo de suspensión",            (V, V, V, F, F, V, F, F)),
    "CER-019": ("Registrar motivo de cancelación",           (V, V, REQ, F, F, V, F, F)),
    "CER-020": ("Consultar historial de estados",            (V, V, V, V, V, F, F, V)),
    "CER-021": ("Publicar en portal de consulta",            (V, V, V, F, F, F, F, F)),
    "CER-022": ("Retirar del portal público",                (SA, F, F, F, F, F, F, F)),
    "CER-023": ("Actualizar estado público",                 (V, V, V, F, F, F, F, F)),
    "CER-024": ("Consultar publicación y métricas",          (V, V, V, F, F, F, F, V)),
    "CER-025": ("Exportar base de certificados",             (V, V, REQ, F, F, F, F, F)),
    "CER-026": ("Generar listado oficial de empresas",       (V, V, V, F, F, F, F, F)),
    "CER-027": ("Alertas de próximos vencimientos",          (V, V, V, V, V, F, F, F)),
    "CER-028": ("Notificar vencimiento por correo",          (V, V, V, V, V, F, F, F)),
    "CER-029": ("Registrar renovación en plataforma",        (V, V, REQ, F, F, F, F, F)),
    "CER-030": ("Registrar cambios de alcance",              (SA, F, F, F, F, F, F, F)),
}


def nivel_permiso(codigo: str, nombre_rol: str | None) -> NivelPermiso:
    if codigo not in PERMISOS_M9:
        raise KeyError(f"El permiso {codigo} no existe en la matriz de M9.")
    columna = columna_de_rol(nombre_rol)
    if columna is None:
        return F
    return PERMISOS_M9[codigo][1][COLUMNAS_MATRIZ.index(columna)]


def tiene_permiso(codigo: str, nombre_rol: str | None) -> bool:
    nivel = nivel_permiso(codigo, nombre_rol)
    if nivel is F:
        return False
    if nivel is SA:
        return normalizar_rol(nombre_rol) == "Super Administrador"
    return True


def requiere_permiso(codigo: str):
    async def verificar(current_user: dict = Depends(get_current_user)) -> dict:
        nivel = nivel_permiso(codigo, current_user.get("role_name"))
        if not tiene_permiso(codigo, current_user.get("role_name")):
            descripcion = PERMISOS_M9[codigo][0]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso {codigo} ({descripcion}) denegado para el rol.",
            )
        current_user["requiere_aprobacion"] = nivel is NivelPermiso.REQUIERE_APROBACION
        return current_user

    return verificar


def marcar_aprobacion(respuesta: dict, usuario: dict) -> dict:
    if usuario.get("requiere_aprobacion"):
        return {**respuesta, "requiere_aprobacion": True}
    return respuesta