import asyncio
from datetime import datetime, timezone

from sqlalchemy import text
from core.database import AsyncSessionLocal
from core.redis_client import get_redis_client


def _a_naive_utc(valor: datetime) -> datetime:
    """Igual que el helper de AuthService: normaliza a UTC naive para comparar fechas."""
    if valor.tzinfo is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


async def migrar_tokens():
    redis_client = get_redis_client()

    async with AsyncSessionLocal() as session:
        # 1. Consultar solo los tokens NO utilizados (los usados no sirven para nada en caché)
        resultado = await session.execute(
            text("""
                SELECT usuario_id, token, fecha_expiracion
                FROM password_reset_tokens
                WHERE utilizado = FALSE
            """)
        )
        tokens = resultado.mappings().all()

        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        migrados = 0

        # 2. Recorrer cada token
        for fila in tokens:
            expiracion = _a_naive_utc(fila["fecha_expiracion"])
            segundos_restantes = int((expiracion - ahora).total_seconds())

            # 3. Si ya expiró, no lo migramos (dato basura)
            if segundos_restantes <= 0:
                continue

            # 4. Guardar en Redis: clave = token, valor = usuario_id, con TTL = tiempo restante
            clave = f"password_reset_token:{fila['token']}"
            await redis_client.set(clave, str(fila["usuario_id"]), ex=segundos_restantes)
            migrados += 1

        print(f"Migrados {migrados} tokens activos a Redis (de {len(tokens)} sin utilizar).")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(migrar_tokens())