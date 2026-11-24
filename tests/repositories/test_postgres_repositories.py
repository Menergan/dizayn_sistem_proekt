import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")

from app.domain.entities import Offer, Rental, StationEvent
from app.domain.enums import RentalStatus
from app.persistence import (
    SqlAlchemyOfferRepository,
    SqlAlchemyPaymentOperationRepository,
    SqlAlchemyRentalRepository,
    SqlAlchemyStationEventRepository,
    create_session_factory,
)
from app.workers import PersistenceCleanupWorker


DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="DATABASE_URL is required for PostgreSQL repository tests",
)


@pytest.fixture
def session_factory():
    return create_session_factory(DATABASE_URL)


def build_offer(expires_at: datetime) -> Offer:
    return Offer(
        id=uuid4(),
        user_id="repository-user",
        station_id="repository-station",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_offer_can_be_claimed_once_under_concurrency(session_factory) -> None:
    repository = SqlAlchemyOfferRepository(session_factory)
    offer = build_offer(datetime.now(UTC) + timedelta(minutes=5))
    await repository.save(offer)

    claimed = await asyncio.gather(
        repository.claim_available(offer.id, datetime.now(UTC)),
        repository.claim_available(offer.id, datetime.now(UTC)),
    )

    assert sum(item is not None for item in claimed) == 1


@pytest.mark.asyncio
async def test_payment_key_is_stable_for_retries(session_factory) -> None:
    rental_repository = SqlAlchemyRentalRepository(session_factory)
    payment_repository = SqlAlchemyPaymentOperationRepository(session_factory)
    now = datetime.now(UTC)
    rental = Rental(
        id=uuid4(),
        user_id="repository-user",
        start_station_id="repository-station",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        started_at=now,
        status=RentalStatus.CREATING,
    )
    await rental_repository.save(rental)

    keys = await asyncio.gather(
        payment_repository.get_or_create_key(rental.id, "RESERVE", rental.deposit),
        payment_repository.get_or_create_key(rental.id, "RESERVE", rental.deposit),
    )

    assert keys == [f"rental:{rental.id}:reserve", f"rental:{rental.id}:reserve"]
    await payment_repository.save_result(
        rental.id,
        "RESERVE",
        "SUCCEEDED",
        "external-reserve-1",
        {"successful": True},
    )
    saved_operation = await payment_repository.get(rental.id, "RESERVE")

    assert saved_operation is not None
    assert saved_operation.amount == rental.deposit
    assert saved_operation.status == "SUCCEEDED"
    assert saved_operation.external_operation_id == "external-reserve-1"
    assert saved_operation.external_response == {"successful": True}


@pytest.mark.asyncio
async def test_station_event_is_deduplicated(session_factory) -> None:
    repository = SqlAlchemyStationEventRepository(session_factory)
    event = StationEvent(
        id=f"event-{uuid4()}",
        station_id="repository-station",
        powerbank_id="repository-powerbank",
        returned_at=datetime.now(UTC),
    )

    assert await repository.save_if_new(event) is True
    assert await repository.save_if_new(event) is False


@pytest.mark.asyncio
async def test_cleanup_worker_deletes_expired_rows(session_factory) -> None:
    now = datetime.now(UTC)
    offer_repository = SqlAlchemyOfferRepository(session_factory)
    rental_repository = SqlAlchemyRentalRepository(session_factory)
    offer = build_offer(now - timedelta(minutes=1))
    rental = Rental(
        id=uuid4(),
        user_id="cleanup-user",
        start_station_id="cleanup-station",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        started_at=now - timedelta(days=366),
        status=RentalStatus.COMPLETED,
        delete_after=now - timedelta(minutes=1),
    )
    await offer_repository.save(offer)
    await rental_repository.save(rental)

    result = await PersistenceCleanupWorker(offer_repository, rental_repository).run_once(now)

    assert result.deleted_offers >= 1
    assert result.deleted_rentals >= 1
    assert await rental_repository.get(rental.id) is None
