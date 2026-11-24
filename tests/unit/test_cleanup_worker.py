from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.entities import Offer, Rental, StationEvent
from app.domain.enums import RentalStatus
from app.workers import PersistenceCleanupWorker
from tests.fakes import FakeOfferRepository, FakeRentalRepository, FakeStationEventRepository


@pytest.mark.asyncio
async def test_cleanup_worker_deletes_expired_records() -> None:
    now = datetime.now(UTC)
    offers = FakeOfferRepository()
    rentals = FakeRentalRepository()
    offer = Offer(
        id=uuid4(),
        user_id="user-1",
        station_id="station-1",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    rental = Rental(
        id=uuid4(),
        user_id="user-1",
        start_station_id="station-1",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        started_at=now - timedelta(days=366),
        status=RentalStatus.COMPLETED,
        delete_after=now - timedelta(days=1),
    )
    await offers.save(offer)
    await rentals.save(rental)

    result = await PersistenceCleanupWorker(offers, rentals).run_once(now)

    assert result.deleted_offers == 1
    assert result.deleted_rentals == 1
    assert await rentals.get(rental.id) is None


@pytest.mark.asyncio
async def test_station_event_is_saved_once() -> None:
    repository = FakeStationEventRepository()
    event = StationEvent(
        id="station-event-1",
        station_id="station-1",
        powerbank_id="powerbank-1",
        returned_at=datetime.now(UTC),
    )

    assert await repository.save_if_new(event) is True
    assert await repository.save_if_new(event) is False
