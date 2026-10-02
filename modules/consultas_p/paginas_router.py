"""
Páginas del portal público (M11).

El módulo sirve sus propias vistas para que la interfaz y los endpoints que la
alimentan vivan juntos y se muevan juntos. La ruta `/buscar_empresa` conserva su
camino histórico porque el menú público ya enlaza a ella.

Van en un router aparte del de la API y sin límite de peticiones: entregan HTML
estático, igual que las demás páginas del sitio.
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["Consultas públicas — páginas"])


@router.get("/buscar_empresa", response_class=HTMLResponse)
async def pagina_buscar_empresa():
    """Buscador público de empresa por NIT."""
    return FileResponse("static/buscar_e.html")


@router.get("/consulta-norma", response_class=HTMLResponse)
async def pagina_consulta_norma():
    """Consulta pública de la norma evaluada, por NIT o número de radicado."""
    return FileResponse("static/consulta_norma.html")


@router.get("/vigencia", response_class=HTMLResponse)
async def pagina_vigencia():
    """Vigencia del certificado y plazos del trámite, por NIT o radicado."""
    return FileResponse("static/vigencia.html")


@router.get("/validar", response_class=HTMLResponse)
async def pagina_validar():
    """Validación de autenticidad por código de verificación."""
    return FileResponse("static/validar.html")


@router.get("/constancia", response_class=HTMLResponse)
async def pagina_constancia():
    """Descarga de la constancia pública en PDF, por NIT."""
    return FileResponse("static/constancia.html")
