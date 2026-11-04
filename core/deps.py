from redis.asyncio import Redis
from core.redis_client import get_redis_client

async def get_redis() -> Redis:
    return get_redis_client()
