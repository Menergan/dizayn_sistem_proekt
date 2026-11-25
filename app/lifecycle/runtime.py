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
async def runtime(application=None):
    owns_resources = application is None
    if owns_resources:
        factory = create_session_factory(os.getenv("DATABASE_URL", "postgresql+asyncpg://rental:rental@localhost:5432/rental"))
        cache = RedisCache.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        base = os.getenv("EXTERNAL_SERVICES_URL", "http://localhost:3629")
        client = httpx.AsyncClient()
        config = CachedConfigClient(HTTPConfigClient(client, os.getenv("CONFIGS_URL", base)))
        stations = HTTPStationClient(client, os.getenv("STATIONS_URL", base))
        payments = HTTPPaymentClient(client, os.getenv("PAYMENTS_URL", base))
        await config.start()
    else:
        factory = application.state.session_factory
        cache = application.state.cache
        config = application.state.config_client
        stations = application.state.station_client
        payments = application.state.payment_client
    store = LifecycleStore(factory)
    try:
        yield LifecycleService(store, payments, stations, config, cache)
    finally:
        await store.lock_engine.dispose()
        if owns_resources:
            await config.close()
            await client.aclose()
            await cache.close()
            await factory.kw["bind"].dispose()
