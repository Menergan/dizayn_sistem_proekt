import os
from contextlib import asynccontextmanager

import httpx
from app.cache.redis import RedisCache
from app.integrations.cache import CachedConfigClient
from app.integrations.http import HTTPConfigClient, HTTPPaymentClient, HTTPStationClient
from app.persistence.database import create_session_factory
from app.lifecycle.service import LifecycleService
from app.lifecycle.store import LifecycleStore


@asynccontextmanager
async def runtime():
    factory = create_session_factory(os.getenv("DATABASE_URL", "postgresql+asyncpg://rental:rental@localhost:5432/rental"))
    cache = RedisCache.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    base = os.getenv("EXTERNAL_SERVICES_URL", "http://localhost:3629")
    store = LifecycleStore(factory)
    async with httpx.AsyncClient() as client:
        config = CachedConfigClient(HTTPConfigClient(client, os.getenv("CONFIGS_URL", base)))
        try:
            await config.start()
            yield LifecycleService(store,
                HTTPPaymentClient(client, os.getenv("PAYMENTS_URL", base)),
                HTTPStationClient(client, os.getenv("STATIONS_URL", base)), config, cache)
        finally:
            await config.close()
            await cache.close()
            await store.lock_engine.dispose()
            await factory.kw["bind"].dispose()
