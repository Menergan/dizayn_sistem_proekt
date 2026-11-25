
import os

from redis.asyncio import Redis

from app.ports.cache import Cache


class RedisCache(Cache):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, url: str) -> "RedisCache":
        redis = Redis.from_url(
            url,
            decode_responses=False,
            max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", "200")),
            socket_connect_timeout=float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "0.2")),
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "0.2")),
            health_check_interval=int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL_SECONDS", "30")),
        )
        return cls(redis)

    async def get(self, key: str) -> bytes | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
