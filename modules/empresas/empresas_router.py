from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from modules.empresas.constancia_pdf import generar_pdf_constancia
from modules.empresas.empresas_service import EmpresasService

router = APIRouter(prefix="/empresas", tags=["Empresas"])


@router.get("/all")
async def read_empresas(
    db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    if current_user.get("role_name") != "Administrador":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso exclusivo para administradores.")
    return await EmpresasService(db).get_all_empresas()

@router.get("/consulta-publica")
async def consulta_publica(
    codigo: str = "",
    nit: str = "",
    db: AsyncSession = Depends(get_db),
):
    return await EmpresasService(db).consulta_publica(codigo=codigo, nit=nit)


@router.get("/buscar/{nit}")
async def buscar_empresa_por_nit(
    nit: str,
    db: AsyncSession = Depends(get_db),
):
    return await EmpresasService(db).buscar_por_nit(nit)


@router.get(
    "/constancia/{nit}/pdf",
    summary="Descargar constancia de la empresa en PDF (público)",
    response_class=Response,
)
async def descargar_constancia_pdf(
    nit: str,
    db: AsyncSession = Depends(get_db),
):
    """Devuelve la constancia con los datos de la tarjeta como PDF descargable."""
    empresas = await EmpresasService(db).buscar_por_nit(nit)
    if not empresas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay empresas registradas con ese NIT.",
        )
    empresa = empresas[0]
    pdf = generar_pdf_constancia(empresa)
    nombre_archivo = f"constancia-{empresa.get('nit') or 'empresa'}.pdf"

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
        },
    )
