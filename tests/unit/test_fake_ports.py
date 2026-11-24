from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.entities import Offer
from app.domain.enums import OfferStatus
from tests.fakes import FakeOfferRepository


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
