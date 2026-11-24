from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AppConfig,
    EjectResponse,
    PaymentResult,
    StationData,
    TariffData,
    UserProfile,
)


class StationClient(Protocol):
    async def get_station(self, station_id: str) -> StationData: ...

    async def eject(self, station_id: str, operation_id: str) -> EjectResponse: ...


class PaymentClient(Protocol):
    async def reserve(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult: ...

    async def capture(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult: ...

    async def release(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult: ...


class UserClient(Protocol):
    async def get_user(self, user_id: str) -> UserProfile: ...


class TariffClient(Protocol):
    async def get_tariff(self, tariff_id: str) -> TariffData: ...


class ConfigClient(Protocol):
    async def get_config(self) -> AppConfig: ...
