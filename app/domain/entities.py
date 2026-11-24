from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.enums import OfferStatus, RentalStatus


@dataclass(frozen=True)
class StationData:
    id: str
    tariff_id: str
    country: str
    available_powerbanks: int


@dataclass(frozen=True)
class TariffData:
    id: str
    currency: str
    price_per_hour: Decimal
    free_period_min: int
    default_deposit: Decimal


@dataclass(frozen=True)
class UserProfile:
    id: str
    has_subscription: bool
    trusted: bool


@dataclass(frozen=True)
class AppConfig:
    last_banks_increase: Decimal
    tariffs_ttl_seconds: int


@dataclass
class Offer:
    id: UUID
    user_id: str
    station_id: str
    country: str
    currency: str
    price_per_hour: Decimal
    free_period_min: int
    deposit: Decimal
    created_at: datetime
    expires_at: datetime
    status: OfferStatus = OfferStatus.AVAILABLE


@dataclass
class Rental:
    id: UUID
    user_id: str
    start_station_id: str
    country: str
    currency: str
    price_per_hour: Decimal
    free_period_min: int
    deposit: Decimal
    started_at: datetime
    status: RentalStatus
    powerbank_id: str | None = None
    finish_station_id: str | None = None
    finished_at: datetime | None = None
    total_amount: Decimal | None = None


@dataclass(frozen=True)
class PaymentResult:
    operation_id: str
    successful: bool


@dataclass(frozen=True)
class EjectResponse:
    powerbank_id: str | None
    successful: bool
