from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from app.domain.entities import Rental
from app.domain.enums import RentalStatus
from app.services.rental_read import RentalReadService, RentalReadUnavailableError
from tests.fakes import FakeRentalRepository


class BrokenCache:
    async def get(self, key: str) -> bytes | None:
        raise ConnectionError("Redis unavailable")

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        raise ConnectionError("Redis unavailable")

    async def delete(self, key: str) -> None:
        raise ConnectionError("Redis unavailable")


def rental() -> Rental:
    return Rental(
        id=uuid4(),
        user_id="user",
        start_station_id="station",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50"),
        free_period_min=5,
        deposit=Decimal("300"),
        started_at=datetime.now(UTC),
        status=RentalStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_cache_connection_error_falls_back_to_repository() -> None:
    repository = FakeRentalRepository()
    item = rental()
    await repository.save(item)
    service = RentalReadService(repository, BrokenCache())

    response = await service.get(item.id)

    assert response.rental_id == item.id


@pytest.mark.asyncio
async def test_rejects_database_fallback_when_all_slots_are_busy() -> None:
    repository = FakeRentalRepository()
    service = RentalReadService(
        repository,
        BrokenCache(),
        database_fallback_limit=1,
    )
    await service._database_fallback.acquire()

    with pytest.raises(RentalReadUnavailableError):
        await service.get(uuid4())

    service._database_fallback.release()
