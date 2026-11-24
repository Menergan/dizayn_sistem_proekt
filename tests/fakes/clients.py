from decimal import Decimal
from uuid import UUID

from app.domain.entities import (
    AppConfig,
    EjectResponse,
    PaymentResult,
    StationData,
    TariffData,
    UserProfile,
)


class FakeStationClient:
    def __init__(self, station: StationData, eject_response: EjectResponse) -> None:
        self.station = station
        self.eject_response = eject_response
        self.eject_operations: list[str] = []

    async def get_station(self, station_id: str) -> StationData:
        return self.station

    async def eject(self, station_id: str, operation_id: str) -> EjectResponse:
        self.eject_operations.append(operation_id)
        return self.eject_response


class FakePaymentClient:
    def __init__(self, successful: bool = True) -> None:
        self.successful = successful
        self.operations: list[tuple[str, str]] = []

    async def reserve(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        return self._result("reserve", idempotency_key)

    async def capture(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        return self._result("capture", idempotency_key)

    async def release(
        self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str
    ) -> PaymentResult:
        return self._result("release", idempotency_key)

    def _result(self, operation: str, idempotency_key: str) -> PaymentResult:
        self.operations.append((operation, idempotency_key))
        return PaymentResult(operation_id=idempotency_key, successful=self.successful)


class FakeUserClient:
    def __init__(self, profile: UserProfile) -> None:
        self.profile = profile

    async def get_user(self, user_id: str) -> UserProfile:
        return self.profile


class FakeTariffClient:
    def __init__(self, tariff: TariffData) -> None:
        self.tariff = tariff

    async def get_tariff(self, tariff_id: str) -> TariffData:
        return self.tariff


class FakeConfigClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def get_config(self) -> AppConfig:
        return self.config
