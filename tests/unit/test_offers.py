from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.entities import AppConfig, EjectResponse, StationData, TariffData, UserProfile
from app.services.offers import OfferService, OfferUnavailableError
from tests.fakes import FakeOfferRepository, FakeStationClient, FakeTariffClient, FakeUserClient
from tests.fakes.clients import FakeConfigClient


@pytest.mark.asyncio
async def test_offer_preserves_calculated_terms() -> None:
    repository = FakeOfferRepository()
    service = OfferService(
        repository,
        FakeStationClient(
            StationData("station", "tariff", "RU", 2),
            EjectResponse(None, False),
        ),
        FakeTariffClient(TariffData("tariff", "RUB", Decimal("50"), 5, Decimal("300"))),
        FakeUserClient(UserProfile("user", has_subscription=True, trusted=True)),
        FakeConfigClient(AppConfig(Decimal("1.5"), 300)),
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    response = await service.create("station", "user", now)

    assert response.price_per_hour == Decimal("75.00")
    assert response.free_period_min == 30
    assert response.deposit == Decimal("0")
    assert response.expires_at == now + timedelta(minutes=5)
    assert repository.offers[response.offer_id].country == "RU"


@pytest.mark.asyncio
async def test_offer_is_not_created_for_empty_station() -> None:
    service = OfferService(
        FakeOfferRepository(),
        FakeStationClient(
            StationData("station", "tariff", "RU", 0),
            EjectResponse(None, False),
        ),
        FakeTariffClient(TariffData("tariff", "RUB", Decimal("50"), 5, Decimal("300"))),
        FakeUserClient(UserProfile("user", has_subscription=False, trusted=False)),
        FakeConfigClient(AppConfig(Decimal("1.5"), 300)),
    )

    with pytest.raises(OfferUnavailableError):
        await service.create("station", "user")
