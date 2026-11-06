"""
Página de error común para el navegador.

Cuando el navegador pide una página (petición GET que acepta HTML) y algo
falla, se responde con `static/error.html`: el mismo diseño del sistema y un
mensaje claro de qué pasó y qué hacer.

Las llamadas al API (`fetch` del frontend, que no piden HTML) siguen
recibiendo el JSON de siempre con `detail`, así que las pantallas existentes
no cambian su forma de leer los errores.
"""

from html import escape
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logger import logger

PLANTILLA = Path(__file__).resolve().parent.parent / "static" / "error.html"

# Texto de cada error: (título, qué pasó, qué puede hacer).
MENSAJES: dict[int, tuple[str, str, str]] = {
    400: (
        "La dirección no es válida",
        "La página no se pudo abrir porque la dirección tiene datos incorrectos o incompletos.",
        "Revise la dirección o vuelva a la página anterior y abra la opción desde el menú.",
    ),
    401: (
        "Debe iniciar sesión",
        "Para ver esta página necesita iniciar sesión, o su sesión ya expiró.",
        "Inicie sesión de nuevo y vuelva a intentarlo.",
    ),
    403: (
        "No tiene permiso para ver esta página",
        "Su cuenta no tiene acceso a esta sección de CertiSENA.",
        "Si cree que debería tener acceso, pida al administrador que revise los permisos de su cuenta.",
    ),
    404: (
        "No encontramos esta página",
        "La dirección que abrió no existe o la página fue movida.",
        "Revise que la dirección esté bien escrita o vuelva al inicio y abra la opción desde el menú.",
    ),
    405: (
        "Esta página no se puede abrir así",
        "La dirección existe, pero no se puede abrir directamente desde el navegador.",
        "Vuelva a la página anterior y use el botón o la opción del menú correspondiente.",
    ),
    408: (
        "La página tardó demasiado",
        "El servidor no recibió la solicitud completa a tiempo.",
        "Revise su conexión a internet e intente de nuevo.",
    ),
    429: (
        "Demasiadas solicitudes",
        "Se hicieron muchas solicitudes en poco tiempo y el sistema las detuvo por seguridad.",
        "Espere un minuto y vuelva a intentarlo.",
    ),
    500: (
        "Ocurrió un error en el sistema",
        "La página no se pudo cargar por un problema interno de CertiSENA. No es un error suyo.",
        "Intente de nuevo en unos minutos. Si el problema continúa, comunique al soporte el código de referencia que aparece abajo.",
    ),
    502: (
        "El servicio no respondió correctamente",
        "Un servicio que CertiSENA necesita respondió con un error.",
        "Intente de nuevo en unos minutos.",
    ),
    503: (
        "El sistema no está disponible por ahora",
        "CertiSENA está en mantenimiento o no puede conectarse a la base de datos en este momento.",
        "Intente de nuevo en unos minutos.",
    ),
    504: (
        "El sistema tardó demasiado en responder",
        "La página no se cargó a tiempo.",
        "Intente de nuevo en unos minutos.",
    ),
}


def _mensajes(codigo: int) -> tuple[str, str, str]:
    if codigo in MENSAJES:
        return MENSAJES[codigo]
    return MENSAJES[500] if codigo >= 500 else MENSAJES[400]


def es_peticion_de_pagina(request: Request) -> bool:
    """El navegador abre una página: GET/HEAD que acepta HTML.

    `fetch` envía por defecto `Accept: */*`, así que las llamadas al API no
    entran aquí y siguen recibiendo JSON.
    """
    if request.method not in ("GET", "HEAD"):
        return False
    return "text/html" in request.headers.get("accept", "").lower()


def respuesta_pagina_error(
    request: Request,
    codigo: int,
    referencia: str | None = None,
    headers: dict | None = None,
) -> HTMLResponse:
    """Rellena la plantilla con textos escapados y responde con `codigo`."""
    titulo, mensaje, sugerencia = _mensajes(codigo)
    valores = {
        "codigo": str(codigo),
        "titulo": titulo,
        "mensaje": mensaje,
        "sugerencia": sugerencia,
        "ruta": request.url.path,
        "referencia": referencia or "",
        "tipo": "servidor" if codigo >= 500 else "cliente",
    }
    try:
        html = PLANTILLA.read_text(encoding="utf-8")
    except OSError:
        # Sin plantilla se responde una versión mínima, nunca un error dentro del error.
        html = "<!doctype html><meta charset='utf-8'><title>{{titulo}}</title><h1>Error {{codigo}}: {{titulo}}</h1><p>{{mensaje}}</p><p>{{sugerencia}}</p><p><a href='/'>Ir al inicio</a></p>"
    for clave, valor in valores.items():
        html = html.replace("{{" + clave + "}}", escape(valor))
    html = html.replace("{{ocultar_referencia}}", "" if referencia else "hidden")
    html = html.replace("{{ocultar_reintentar}}", "" if codigo >= 500 or codigo in (408, 429) else "hidden")
    html = html.replace("{{ocultar_login}}", "" if codigo in (401, 403) else "hidden")

    # Los encabezados de la excepción (p. ej. WWW-Authenticate) se conservan;
    # el tipo de contenido lo fija HTMLResponse.
    extra = {k: v for k, v in (headers or {}).items() if k.lower() != "content-type"}
    return HTMLResponse(html, status_code=codigo, headers=extra or None)


def _nueva_referencia() -> str:
    return uuid4().hex[:8].upper()


def registrar_paginas_error(app: FastAPI) -> None:
    """Conecta la página de error a la aplicación."""

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if es_peticion_de_pagina(request):
            return respuesta_pagina_error(request, exc.status_code, headers=getattr(exc, "headers", None))
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        # Una página con un parámetro mal formado (p. ej. un id que no es UUID)
        # es una dirección no válida para quien navega.
        if es_peticion_de_pagina(request):
            return respuesta_pagina_error(request, 400)
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception):
        referencia = _nueva_referencia()
        logger.exception(
            "Error no controlado [ref %s] en %s %s: %s",
            referencia, request.method, request.url.path, exc,
        )
        if es_peticion_de_pagina(request):
            return respuesta_pagina_error(request, 500, referencia=referencia)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Ocurrió un error interno en el sistema. Intente de nuevo en unos minutos.",
                "referencia": referencia,
            },
        )
