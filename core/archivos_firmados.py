"""Enlaces firmados de corta duración para los archivos de ``uploads/``.

Antes ``/uploads`` se montaba como carpeta pública: cualquiera que conociera
(o adivinara) la ruta descargaba los PDF y las fotos de los auditores sin
iniciar sesión. Ahora la carpeta no se publica y cada archivo se entrega por
``GET /archivos/<exp>/<firma>/<ruta>``:

* ``ruta``  : ruta relativa dentro de ``uploads/`` (p. ej. ``auditores/x.pdf``).
* ``exp``   : instante de vencimiento (segundos Unix).
* ``firma`` : HMAC-SHA256 de ``"<ruta>|<exp>"`` con ``SECRET_KEY``.

La firma va en la ruta y no en la query para que la URL siga terminando en
``.pdf``/``.jpg``: las pantallas deciden si muestran un visor de PDF o una
imagen mirando la extensión del final de la URL, y algunas añaden ``?v=``.

Las pantallas usan ``<img src>``, ``<iframe src>`` y ``<a target=_blank>``,
que no envían el header ``Authorization``; por eso la sesión se valida antes,
cuando el backend entrega la URL:

1. Las respuestas JSON de la API que traen ``"/uploads/..."`` (así están
   guardadas en la base) se reescriben al vuelo con un enlace firmado
   (``FirmarUploadsMiddleware``). Solo responden con esas rutas endpoints que
   ya exigen sesión y rol; el middleware firma lo que ese endpoint ya decidió
   mostrar. La base no se modifica.
2. ``GET /archivos/firmar?ruta=...`` firma una ruta suelta validando la sesión
   y las reglas de ``modules/archivos/archivos_router.py``.

Cuando el navegador devuelve una de esas URL al guardar (p. ej. el perfil
reenvía ``foto_url``), ``url_canonica`` la convierte otra vez en
``/uploads/...`` para que en la base nunca quede un enlace firmado.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from pathlib import Path
from urllib.parse import quote, unquote

from core.config import settings

RAIZ_PROYECTO = Path(__file__).resolve().parents[1]
RAIZ_UPLOADS = (RAIZ_PROYECTO / "uploads").resolve()

PREFIJO_PUBLICO = "/archivos"
# Vigencia del enlace: suficiente para abrir la pantalla y consultar los
# documentos; un enlace copiado deja de servir a los pocos minutos.
VIGENCIA_SEGUNDOS = 15 * 60

_RE_FIRMADA = re.compile(r"^/archivos/(\d{1,12})/([0-9a-f]{64})/(.+)$")


def _firma(ruta: str, exp: int) -> str:
    mensaje = f"{ruta}|{exp}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


def ruta_relativa(url: str | None) -> str | None:
    """Ruta relativa dentro de uploads/ para '/uploads/x', 'uploads/x' o un enlace firmado.

    Devuelve None si la URL no apunta a uploads/ o intenta salir de la carpeta.
    """
    if not url:
        return None
    limpio = str(url).strip().split("#", 1)[0].split("?", 1)[0]
    firmada = _RE_FIRMADA.match(limpio)
    if firmada:
        relativo = firmada.group(3)
    elif limpio.startswith("/uploads/"):
        relativo = limpio[len("/uploads/"):]
    elif limpio.startswith("uploads/"):
        relativo = limpio[len("uploads/"):]
    else:
        return None
    relativo = unquote(relativo).replace("\\", "/").lstrip("/")
    partes = [p for p in relativo.split("/") if p not in ("", ".")]
    if not partes or any(p == ".." for p in partes):
        return None
    return "/".join(partes)


def url_canonica(url: str | None) -> str | None:
    """Convierte un enlace firmado (o 'uploads/x') en la forma guardada '/uploads/x'."""
    if url is None:
        return None
    texto = str(url).strip()
    relativo = ruta_relativa(texto)
    if relativo is None:
        return texto
    return f"/uploads/{relativo}"


def firmar_url(url: str | None, vigencia: int = VIGENCIA_SEGUNDOS, ahora: float | None = None) -> str | None:
    """'/uploads/a/b.pdf' -> '/archivos/<exp>/<firma>/a/b.pdf'. Otras URL se devuelven igual."""
    relativo = ruta_relativa(url)
    if relativo is None:
        return url
    exp = int((ahora if ahora is not None else time.time()) + vigencia)
    return f"{PREFIJO_PUBLICO}/{exp}/{_firma(relativo, exp)}/{quote(relativo)}"


def verificar(ruta: str, exp: int, firma: str, ahora: float | None = None) -> bool:
    if exp < (ahora if ahora is not None else time.time()):
        return False
    return hmac.compare_digest(_firma(ruta, exp), (firma or "").lower())


def resolver_en_uploads(relativo: str) -> Path | None:
    """Ruta real del archivo, o None si no existe o queda fuera de uploads/."""
    candidato = (RAIZ_UPLOADS / relativo).resolve()
    try:
        candidato.relative_to(RAIZ_UPLOADS)
    except ValueError:
        return None
    return candidato if candidato.is_file() else None


# ----------------------------------------------------------------------
# Reescritura de las respuestas JSON
# ----------------------------------------------------------------------

# "/uploads/..." o "uploads/..." como valor completo de una cadena JSON.
_RE_JSON_UPLOADS = re.compile(rb'"(/?uploads/[^"\\]+)"')


def firmar_en_json(cuerpo: bytes, ahora: float | None = None) -> bytes:
    if b"uploads/" not in cuerpo:
        return cuerpo

    def _reemplazo(m: re.Match) -> bytes:
        original = m.group(1).decode("utf-8", "replace")
        firmada = firmar_url(original, ahora=ahora)
        return b'"' + (firmada or original).encode("utf-8") + b'"'

    return _RE_JSON_UPLOADS.sub(_reemplazo, cuerpo)


class FirmarUploadsMiddleware:
    """ASGI: firma las rutas '/uploads/...' de las respuestas application/json."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inicio: dict | None = None
        partes: list[bytes] = []
        es_json = False

        async def _send(mensaje):
            nonlocal inicio, es_json
            if mensaje["type"] == "http.response.start":
                cabeceras = dict(mensaje.get("headers") or [])
                tipo = cabeceras.get(b"content-type", b"").lower()
                es_json = tipo.startswith(b"application/json")
                if not es_json:
                    await send(mensaje)
                    return
                inicio = mensaje
                return
            if mensaje["type"] == "http.response.body" and es_json:
                partes.append(mensaje.get("body", b""))
                if mensaje.get("more_body", False):
                    return
                cuerpo = firmar_en_json(b"".join(partes))
                cabeceras = [
                    (k, v) for k, v in (inicio.get("headers") or []) if k.lower() != b"content-length"
                ]
                cabeceras.append((b"content-length", str(len(cuerpo)).encode()))
                await send({**inicio, "headers": cabeceras})
                await send({"type": "http.response.body", "body": cuerpo, "more_body": False})
                return
            await send(mensaje)

        await self.app(scope, receive, _send)
