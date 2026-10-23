import redis.asyncio as redis
from core.config import settings

redis_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)

def get_redis_client() -> redis.Redis:
    return redis.Redis(connection_pool=redis_pool)