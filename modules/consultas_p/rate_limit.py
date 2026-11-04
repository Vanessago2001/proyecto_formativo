"""
Límite de peticiones para las consultas públicas.

Estos endpoints responden sin autenticación, así que el límite por IP es la
única barrera contra el volcado masivo de la tabla `empresa`. El registro es
en memoria y por proceso: suficiente para un único uvicorn. Si se llegara a
desplegar con varios workers habría que pasarlo a Redis.
"""

from collections import defaultdict, deque

from fastapi import HTTPException, Request, status
from time import monotonic

PETICIONES_PERMITIDAS = 30
VENTANA_SEGUNDOS = 60

# Tope de IPs distintas que se conservan a la vez, para que el diccionario no
# crezca sin límite si muchas fuentes distintas consultan el portal.
MAX_IPS_REGISTRADAS = 5000

registro: dict[str, deque[float]] = defaultdict(deque)


def reiniciar() -> None:
    """Vacía el contador. Lo usan los tests entre caso y caso."""
    registro.clear()


def _olvidar_ips_inactivas(ahora: float) -> None:
    if len(registro) < MAX_IPS_REGISTRADAS:
        return
    vencidas = [
        ip
        for ip, marcas in registro.items()
        if not marcas or ahora - marcas[-1] > VENTANA_SEGUNDOS
    ]
    for ip in vencidas:
        del registro[ip]


async def limitar_consultas(request: Request) -> None:
    # Se usa request.client.host y no X-Forwarded-For: esa cabecera la pone el
    # cliente, así que rotar IPs falsas bastaría para saltarse el límite.
    ip = request.client.host if request.client else "desconocida"
    ahora = monotonic()

    marcas = registro[ip]
    while marcas and ahora - marcas[0] > VENTANA_SEGUNDOS:
        marcas.popleft()

    if len(marcas) >= PETICIONES_PERMITIDAS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas consultas seguidas. Espera un momento e intenta de nuevo.",
        )

    marcas.append(ahora)
    _olvidar_ips_inactivas(ahora)
