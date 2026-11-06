"""
Límite de peticiones para las rutas públicas de PQRS (sin sesión).

Mismo enfoque que modules/consultas_p/rate_limit.py: registro en memoria por
proceso y por IP (request.client.host, nunca X-Forwarded-For, que lo pone el
cliente). Va aparte para que radicar PQRS no gaste el cupo de las consultas
públicas de certificados ni al revés. Si se despliega con varios workers hay
que pasarlo a Redis (core/redis_client.py).
"""

from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status

# (peticiones permitidas, ventana en segundos) por tipo de operación.
LIMITES = {
    "radicar": (5, 600),       # 5 radicaciones cada 10 minutos por IP
    "consultar": (20, 60),     # 20 consultas por minuto por IP
    "adjuntar": (10, 600),
    "reabrir": (5, 600),
}
MAX_IPS_REGISTRADAS = 5000

registro: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def reiniciar() -> None:
    """Vacía los contadores (lo usan las pruebas)."""
    registro.clear()


def _olvidar_inactivas(ahora: float) -> None:
    if len(registro) < MAX_IPS_REGISTRADAS:
        return
    for clave in [c for c, marcas in registro.items() if not marcas or ahora - marcas[-1] > 600]:
        del registro[clave]


def limitar(operacion: str):
    permitidas, ventana = LIMITES[operacion]

    async def dependencia(request: Request) -> None:
        ip = request.client.host if request.client else "desconocida"
        ahora = monotonic()
        marcas = registro[(operacion, ip)]
        while marcas and ahora - marcas[0] > ventana:
            marcas.popleft()
        if len(marcas) >= permitidas:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes seguidas. Espera unos minutos e intenta de nuevo.",
            )
        marcas.append(ahora)
        _olvidar_inactivas(ahora)

    return dependencia
