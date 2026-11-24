from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.entities import Offer
from app.domain.enums import OfferStatus
from tests.fakes import FakeOfferRepository, FakePaymentOperationRepository


@pytest.mark.asyncio
async def test_fake_offer_can_be_claimed_only_once() -> None:
    repository = FakeOfferRepository()
    now = datetime.now(UTC)
    offer = Offer(
        id=uuid4(),
        user_id="user-1",
        station_id="station-1",
        country="RU",
        currency="RUB",
        price_per_hour=Decimal("50.00"),
        free_period_min=5,
        deposit=Decimal("300.00"),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    await repository.save(offer)

    assert await repository.claim_available(offer.id, now) is offer
    assert offer.status is OfferStatus.USED
    assert await repository.claim_available(offer.id, now) is None


@pytest.mark.asyncio
async def test_fake_payment_operation_keeps_result() -> None:
    repository = FakePaymentOperationRepository()
    rental_id = uuid4()
    key = await repository.get_or_create_key(rental_id, "RESERVE", Decimal("300.00"))
    await repository.save_result(
        rental_id,
        "RESERVE",
        "SUCCEEDED",
        "external-reserve-1",
        {"successful": True},
    )
    operation = await repository.get(rental_id, "RESERVE")

    assert key == f"rental:{rental_id}:reserve"
    assert operation is not None
    assert operation.status == "SUCCEEDED"
