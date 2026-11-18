from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from modules.auth.dependencies import require_admin_access_con
from modules.permisos_auxiliar.regla_auxiliar import exigir_permiso_auxiliar
from modules.administrar_auditores.administrar_auditores_service import AdministrarAuditoresService

router = APIRouter(prefix="/administradores/auditores", tags=["Administración de Auditores"])

# Acciones del banco que el Auxiliar solo puede hacer con permiso delegado
# (REQ en documentacion/permisos.xlsx; catálogo de permisos_auxiliar).
PERMISO_POR_ESTADO = {
    "Aprobado": "AUD-013",
    "Rechazado": "AUD-014",
}
PERMISO_VALIDAR_COMPETENCIA = "AUD-030"
# Estados que el Auxiliar pone con un permiso V delegado (sin aprobación).
PERMISO_V_POR_ESTADO = {
    "En Revisión": "AUD-012",
    "Correcciones": "AUD-015",
}


async def _exigir_permiso_delegado(usuario: dict, db: AsyncSession, codigo: str, detalle: str) -> None:
    """El Coordinador siempre puede; el Auxiliar solo con el permiso vigente."""
    from fastapi import HTTPException
    from core.security import es_coordinador
    from modules.permisos_auxiliar.permisos_auxiliar_service import usar_permiso_delegado

    if es_coordinador(usuario):
        return
    if await usar_permiso_delegado(db, usuario, codigo, detalle):
        return
    raise HTTPException(
        403,
        f"Esta acción requiere el permiso delegado {codigo}. "
        "Solicítelo al Coordinador.",
    )


@router.get("/conflictos")
async def listar_conflictos_general(
    usuario: dict = Depends(require_admin_access_con("AUD-033")),
    db: AsyncSession = Depends(get_db),
):
    return {
        "conflictos": await AdministrarAuditoresService(db).listar_conflictos_general()
    }

@router.get("/solicitudes")
async def listar_solicitudes(
    estado: str | None = Query(None),
    usuario: dict = Depends(require_admin_access_con("AUD-011")),
    db: AsyncSession = Depends(get_db),
):
    return await AdministrarAuditoresService(db).listar_solicitudes(estado)

@router.get("/solicitudes/{id_postulacion}")
async def obtener_solicitud(
    id_postulacion: UUID,
    usuario: dict = Depends(require_admin_access_con("AUD-011", "AUD-012")),
    db: AsyncSession = Depends(get_db),
):
    return await AdministrarAuditoresService(db).obtener_solicitud(id_postulacion)

@router.post("/documentos/{id_documento}/revision")
async def revisar_documento(
    id_documento: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-012")),
    db: AsyncSession = Depends(get_db),
):
    estado = str(data.get("estado_revision", "")).strip()
    observacion = str(data.get("observacion", "") or "")
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al coordinador.")
    return await AdministrarAuditoresService(db).revisar_documento(
        id_documento=id_documento,
        estado_revision=estado,
        observacion=observacion,
        id_usuario_actor=UUID(str(actor)),
    )

@router.post("/competencias/{id_competencia}/revision")
async def revisar_competencia(
    id_competencia: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-012", "AUD-030")),
    db: AsyncSession = Depends(get_db),
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al coordinador.")
    estado = str(data.get("estado_validacion", "")).strip()
    observacion = str(data.get("observacion", "") or "")
    if estado in ("Aprobado", "Validado", "Rechazado"):
        await _exigir_permiso_delegado(
            usuario, db, PERMISO_VALIDAR_COMPETENCIA,
            f"{PERMISO_VALIDAR_COMPETENCIA} competencia {id_competencia}",
        )
    return await AdministrarAuditoresService(db).revisar_validacion_competencia(
        id_competencia=id_competencia,
        estado_validacion=estado,
        observacion=observacion,
        id_usuario_actor=UUID(str(actor)),
    )

@router.patch("/solicitudes/{id_postulacion}/revision")
async def pasar_revision_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-012")),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="En Revisión",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/correcciones")
async def solicitar_correcciones_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-015")),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Correcciones",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/aprobar")
async def aprobar_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-013")),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Aprobado",
        data=data,
        usuario=usuario,
        db=db,
    )

@router.patch("/solicitudes/{id_postulacion}/rechazar")
async def rechazar_alias(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-014")),
    db: AsyncSession = Depends(get_db),
):
    return await _ejecutar_alias_estado(
        id_postulacion=id_postulacion,
        nuevo_estado="Rechazado",
        data=data,
        usuario=usuario,
        db=db,
    )

async def _ejecutar_alias_estado(
    id_postulacion: UUID,
    nuevo_estado: str,
    data: dict,
    usuario: dict,
    db: AsyncSession,
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al coordinador.")
    observaciones = str(data.get("observaciones") or "")
    if nuevo_estado in PERMISO_V_POR_ESTADO:
        exigir_permiso_auxiliar(usuario, PERMISO_V_POR_ESTADO[nuevo_estado])
    if nuevo_estado in PERMISO_POR_ESTADO:
        codigo = PERMISO_POR_ESTADO[nuevo_estado]
        await _exigir_permiso_delegado(usuario, db, codigo, f"{codigo} postulación {id_postulacion}")
    return await AdministrarAuditoresService(db).cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado=nuevo_estado,
        observaciones=observaciones,
        id_usuario_actor=UUID(str(actor)),
        **_confirmacion_sin_competencias(data, usuario),
    )


def _confirmacion_sin_competencias(data: dict, usuario: dict) -> dict:
    """Marca explícita para aprobar un auditor sin competencias validadas.

    Quien llega aquí con estado Aprobado ya pasó el permiso AUD-013 (el
    Coordinador siempre; el Auxiliar solo con el permiso delegado), así que
    se registra con qué rol se confirmó.
    """
    from core.security import es_coordinador

    confirmar = data.get("confirmar_sin_competencias") is True
    return {
        "confirmar_sin_competencias": confirmar,
        "justificacion_sin_competencias": str(data.get("justificacion_sin_competencias") or ""),
        "rol_confirmacion": (
            "Coordinador" if es_coordinador(usuario)
            else f"Auxiliar con permiso delegado {PERMISO_POR_ESTADO['Aprobado']}"
        ),
    }

@router.post("/solicitudes/{id_postulacion}/estado")
async def cambiar_estado(
    id_postulacion: UUID,
    data: dict,
    usuario: dict = Depends(require_admin_access_con("AUD-012", "AUD-013", "AUD-014", "AUD-015")),
    db: AsyncSession = Depends(get_db),
):
    actor = usuario.get("id_usuario") or usuario.get("sub")
    if not actor:
        from fastapi import HTTPException
        raise HTTPException(401, "No fue posible identificar al coordinador.")
    nuevo_estado = str(data.get("nuevo_estado", "")).strip()
    if nuevo_estado in PERMISO_V_POR_ESTADO:
        exigir_permiso_auxiliar(usuario, PERMISO_V_POR_ESTADO[nuevo_estado])
    if nuevo_estado in PERMISO_POR_ESTADO:
        codigo = PERMISO_POR_ESTADO[nuevo_estado]
        await _exigir_permiso_delegado(usuario, db, codigo, f"{codigo} postulación {id_postulacion}")
    return await AdministrarAuditoresService(db).cambiar_estado(
        id_postulacion=id_postulacion,
        nuevo_estado=nuevo_estado,
        observaciones=str(data.get("observaciones", "") or ""),
        id_usuario_actor=UUID(str(actor)),
        **_confirmacion_sin_competencias(data, usuario),
    )
