import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable

from app.domain.entities import AppConfig, TariffData, UserProfile
from app.integrations.http import ExternalServiceUnavailable
from app.ports.clients import ConfigClient, TariffClient, UserClient

logger = logging.getLogger(__name__)


class CachedConfigClient:
    def __init__(self, upstream: ConfigClient, interval: float = 60):
        if interval <= 0:
            raise ValueError("refresh interval must be positive")
        self.upstream, self.interval = upstream, interval
        self._config: AppConfig | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("config refresher already started")
        self._config = await self.upstream.get_config()
        self._task = asyncio.create_task(self._refresh_loop())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                self._config = await self.upstream.get_config()
            except Exception:
                logger.exception("config_refresh_failed", extra={"event": "config_refresh_failed", "service": "configs"})

    async def get_config(self) -> AppConfig:
        if self._config is None:
            raise RuntimeError("config cache has not been initialized")
        return self._config


class CachedTariffClient:
    def __init__(self, upstream: TariffClient, configs: ConfigClient, capacity: int = 1024, clock: Callable[[], float] = time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.upstream, self.configs, self.capacity, self.clock = upstream, configs, capacity, clock
        self._items: OrderedDict[str, tuple[float, TariffData]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[TariffData]] = {}

    async def _load(self, tariff_id: str) -> TariffData:
        try:
            value = await self.upstream.get_tariff(tariff_id)
            async with self._lock:
                self._items[tariff_id] = (self.clock(), value)
                self._items.move_to_end(tariff_id)
                if len(self._items) > self.capacity:
                    self._items.popitem(last=False)
            return value
        finally:
            async with self._lock:
                if self._inflight.get(tariff_id) is asyncio.current_task():
                    self._inflight.pop(tariff_id, None)

    async def get_tariff(self, tariff_id: str) -> TariffData:
        config = await self.configs.get_config()
        ttl = max(1, min(config.tariffs_ttl_seconds, 600))
        async with self._lock:
            item = self._items.get(tariff_id)
            if item is not None and self.clock() - item[0] < ttl:
                self._items.move_to_end(tariff_id)
                return item[1]
            self._items.pop(tariff_id, None)
            task = self._inflight.get(tariff_id)
            if task is None:
                task = asyncio.create_task(self._load(tariff_id))
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                self._inflight[tariff_id] = task
        return await asyncio.shield(task)


class FallbackUserClient:
    def __init__(self, upstream: UserClient):
        self.upstream = upstream

    async def get_user(self, user_id: str) -> UserProfile:
        try:
            return await self.upstream.get_user(user_id)
        except ExternalServiceUnavailable:
            logger.warning("user_fallback", extra={"event": "user_fallback", "service": "users", "user_id": user_id})
            return UserProfile(id=user_id, has_subscription=False, trusted=False)
