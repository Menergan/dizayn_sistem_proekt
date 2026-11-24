from app.observability.metrics import (
    RENTAL_CACHE_ERRORS,
    RENTAL_CACHE_REQUESTS,
)

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from app.domain.entities import Rental
from app.domain.enums import RentalStatus
from app.ports.cache import Cache
from app.ports.repositories import RentalRepository
from app.schemas.rentals import RentalResponse


CACHE_TTL_SECONDS = 300
CACHE_KEY_PREFIX = "rental:"


class RentalNotFoundError(Exception):
    pass


class RentalReadService:
    def __init__(
        self,
        repository: RentalRepository,
        cache: Cache,
    ) -> None:
        self._repository = repository
        self._cache = cache

    async def get(
        self,
        rental_id: UUID,
        now: datetime | None = None,
    ) -> RentalResponse:
        now = now or datetime.now(timezone.utc)
        key = f"{CACHE_KEY_PREFIX}{rental_id}"

        rental = None

        # Redis is an optimization, not a source of truth.
        try:
            cached = await self._cache.get(key)

            if cached is not None:
                rental = self._deserialize(cached)
                RENTAL_CACHE_REQUESTS.labels(result="hit").inc()
            else:
                RENTAL_CACHE_REQUESTS.labels(result="miss").inc()

        except Exception:
            RENTAL_CACHE_ERRORS.labels(operation="get").inc()
            rental = None

        if rental is None:
            rental = await self._repository.get(rental_id)

            if rental is None:
                raise RentalNotFoundError(str(rental_id))

            try:
                await self._cache.set(
                    key,
                    self._serialize(rental),
                    CACHE_TTL_SECONDS,
                )
            except Exception:
                pass

        return self._to_response(rental, now)

    @staticmethod
    def _serialize(rental: Rental) -> bytes:
        data = {
            "id": str(rental.id),
            "user_id": rental.user_id,
            "start_station_id": rental.start_station_id,
            "country": rental.country,
            "currency": rental.currency,
            "price_per_hour": str(rental.price_per_hour),
            "free_period_min": rental.free_period_min,
            "deposit": str(rental.deposit),
            "started_at": rental.started_at.isoformat(),
            "status": rental.status.value,
            "powerbank_id": rental.powerbank_id,
            "finish_station_id": rental.finish_station_id,
            "finished_at": (
                rental.finished_at.isoformat()
                if rental.finished_at else None
            ),
            "total_amount": (
                str(rental.total_amount)
                if rental.total_amount is not None else None
            ),
        }
        return json.dumps(data).encode("utf-8")

    @staticmethod
    def _deserialize(raw: bytes) -> Rental:
        data = json.loads(raw.decode("utf-8"))

        return Rental(
            id=UUID(data["id"]),
            user_id=data["user_id"],
            start_station_id=data["start_station_id"],
            country=data["country"],
            currency=data["currency"],
            price_per_hour=Decimal(data["price_per_hour"]),
            free_period_min=int(data["free_period_min"]),
            deposit=Decimal(data["deposit"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            status=RentalStatus(data["status"]),
            powerbank_id=data["powerbank_id"],
            finish_station_id=data["finish_station_id"],
            finished_at=(
                datetime.fromisoformat(data["finished_at"])
                if data["finished_at"] else None
            ),
            total_amount=(
                Decimal(data["total_amount"])
                if data["total_amount"] is not None else None
            ),
        )

    @staticmethod
    def _calculate_amount(rental: Rental, now: datetime) -> Decimal:
        if rental.status != RentalStatus.ACTIVE:
            return rental.total_amount or Decimal("0")

        started_at = rental.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        duration_seconds = max(
            0,
            (now - started_at).total_seconds(),
        )

        if duration_seconds < rental.free_period_min * 60:
            return Decimal("0")

        # Preserve the original business rule:
        # charge for each complete hour of the rental duration.
        full_hours = int(duration_seconds // 3600)
        amount = Decimal(full_hours) * rental.price_per_hour

        return amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    @classmethod
    def _to_response(
        cls,
        rental: Rental,
        now: datetime,
    ) -> RentalResponse:
        amount = cls._calculate_amount(rental, now)

        return RentalResponse(
            rental_id=rental.id,
            user_id=rental.user_id,
            powerbank_id=rental.powerbank_id,
            status=rental.status,
            start_station_id=rental.start_station_id,
            finish_station_id=rental.finish_station_id,
            country=rental.country,
            currency=rental.currency,
            started_at=rental.started_at,
            finished_at=rental.finished_at,
            deposit=rental.deposit,
            accumulated_amount=amount,
            total_amount=rental.total_amount,
        )
