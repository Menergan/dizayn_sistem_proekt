import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from app.domain.entities import Offer
from app.ports.clients import ConfigClient, StationClient, TariffClient, UserClient
from app.ports.repositories import OfferRepository
from app.schemas.offers import OfferResponse


class OfferUnavailableError(ValueError):
    pass


class OfferService:
    def __init__(
        self,
        repository: OfferRepository,
        stations: StationClient,
        tariffs: TariffClient,
        users: UserClient,
        configs: ConfigClient,
    ) -> None:
        self._repository = repository
        self._stations = stations
        self._tariffs = tariffs
        self._users = users
        self._configs = configs

    async def create(
        self,
        station_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> OfferResponse:
        station, user, config = await asyncio.gather(
            self._stations.get_station(station_id),
            self._users.get_user(user_id),
            self._configs.get_config(),
        )
        if station.available_powerbanks == 0:
            raise OfferUnavailableError("No powerbanks available at station")

        tariff = await self._tariffs.get_tariff(station.tariff_id)

        price_per_hour = tariff.price_per_hour
        if station.available_powerbanks <= 2:
            price_per_hour = (price_per_hour * config.last_banks_increase).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        created_at = now or datetime.now(UTC)
        offer = Offer(
            id=uuid4(),
            user_id=user_id,
            station_id=station.id,
            country=station.country,
            currency=tariff.currency,
            price_per_hour=price_per_hour,
            free_period_min=max(tariff.free_period_min, 30)
            if user.has_subscription
            else tariff.free_period_min,
            deposit=Decimal("0") if user.trusted else tariff.default_deposit,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=5),
        )
        await self._repository.save(offer)
        return self._to_response(offer)

    @staticmethod
    def _to_response(offer: Offer) -> OfferResponse:
        return OfferResponse(
            offer_id=offer.id,
            station_id=offer.station_id,
            user_id=offer.user_id,
            country=offer.country,
            currency=offer.currency,
            price_per_hour=offer.price_per_hour,
            free_period_min=offer.free_period_min,
            deposit=offer.deposit,
            expires_at=offer.expires_at,
        )
