"""
Rutas del portal público de consultas (M11).

Ninguno de estos endpoints pide autenticación: son la cara pública del sitio.
Por eso el router entero lleva el límite de peticiones por IP como dependencia.

Las páginas del portal las sirve `paginas_router.py`, en este mismo módulo.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.consultas_p.constancia_pdf import generar_pdf_constancia
from modules.consultas_p.consultas_service import ConsultasPublicasService
from modules.consultas_p.rate_limit import limitar_consultas

router = APIRouter(
    prefix="/api/consultas-publicas",
    tags=["Consultas públicas"],
    dependencies=[Depends(limitar_consultas)],
)


@router.get(
    "/empresa/{nit}",
    summary="Buscar empresa por NIT (público)",
)
async def buscar_empresa_por_nit(
    nit: str,
    db: AsyncSession = Depends(get_db),
):
    """Devuelve la tarjeta pública de la empresa: si está certificada, su
    última solicitud y los conteos de trámites, sedes y documentos."""
    return await ConsultasPublicasService(db).buscar_por_nit(nit)


@router.get(
    "/documentos",
    summary="Consultar trámite por radicado o NIT (público)",
)
async def consulta_documentos(
    codigo: str = "",
    nit: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Busca por número de radicado, código de verificación o NIT y devuelve el
    estado del trámite (`CERTIFICADA`, `EN TRAMITE - x` o `REGISTRADA`)."""
    return await ConsultasPublicasService(db).consulta_publica(codigo=codigo, nit=nit)


@router.get(
    "/validar",
    summary="Validar autenticidad por código de verificación (público)",
)
async def validar_autenticidad(
    codigo: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Responde si el código existe (`autentico`) y a qué certificado, empresa y
    trámite corresponde. Siempre 200: un código inexistente es una respuesta
    válida ("no auténtico"), no un error del servidor."""
    return await ConsultasPublicasService(db).validar_autenticidad(codigo)


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
    empresas = await ConsultasPublicasService(db).buscar_por_nit(nit)
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
