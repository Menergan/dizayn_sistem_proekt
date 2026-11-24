
from redis.asyncio import Redis

from app.ports.cache import Cache


class RedisCache(Cache):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, url: str) -> "RedisCache":
        redis = Redis.from_url(url, decode_responses=False)
        return cls(redis)

    async def get(self, key: str) -> bytes | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
