"""
Rutas de reportes (M12).

Todo el módulo exige sesión iniciada: no hay ningún reporte público. El control
de acceso es por rol y por reporte, y el recorte de filas según quién consulta
lo hace `reportes_service.py`, no este router.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import _normalize_role_name, get_current_user
from modules.reportes import reportes_roles as roles_m12
from modules.reportes.reportes_service import ReportesService

router = APIRouter(
    prefix="/api/reportes",
    tags=["Reportes"],
)


@router.get(
    "",
    summary="Reportes disponibles para el rol de la sesión",
)
async def catalogo_de_reportes(usuario: dict = Depends(get_current_user)):
    """El menú de reportes que le corresponde al rol: nada más."""
    rol = _normalize_role_name(usuario.get("role_name"))
    return roles_m12.catalogo_para_rol(rol)


@router.get(
    "/{codigo}",
    summary="Ejecutar un reporte por código",
)
async def ejecutar_reporte(
    codigo: str,
    usuario: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    datos = roles_m12.reporte_o_none(codigo)
    if datos is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El reporte '{codigo}' no existe.",
        )

    rol = _normalize_role_name(usuario.get("role_name"))
    if rol not in datos["roles"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"El rol de la sesión no puede ejecutar '{datos['titulo']}'.",
        )

    filas = await ReportesService(db, usuario).ejecutar(codigo)

    return {
        "codigo": codigo,
        "titulo": datos["titulo"],
        "descripcion": datos["descripcion"],
        "rol": rol,
        "generado_el": datetime.now(timezone.utc).isoformat(),
        "total": len(filas),
        "filas": filas,
    }
