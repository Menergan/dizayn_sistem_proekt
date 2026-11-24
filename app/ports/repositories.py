from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.domain.entities import Offer, PaymentOperation, Rental, StationEvent
from app.domain.enums import RentalStatus


class OfferRepository(Protocol):
    async def save(self, offer: Offer) -> None: ...

    async def claim_available(self, offer_id: UUID, now: datetime) -> Offer | None: ...

    async def delete_expired(self, before: datetime, limit: int) -> int: ...


class RentalRepository(Protocol):
    async def save(self, rental: Rental) -> None: ...

    async def get(self, rental_id: UUID) -> Rental | None: ...

    async def find_active_by_powerbank(self, powerbank_id: str) -> Rental | None: ...

    async def change_status(self, rental_id: UUID, status: RentalStatus) -> Rental: ...

    async def delete_expired(self, before: datetime, limit: int) -> int: ...


class PaymentOperationRepository(Protocol):
    async def get_or_create_key(
        self, rental_id: UUID, operation_type: str, amount: Decimal
    ) -> str: ...

    async def save_result(
        self,
        rental_id: UUID,
        operation_type: str,
        status: str,
        external_operation_id: str | None,
        external_response: dict[str, object] | None,
    ) -> None: ...

    async def get(
        self, rental_id: UUID, operation_type: str
    ) -> PaymentOperation | None: ...


class StationEventRepository(Protocol):
    async def save_if_new(self, event: StationEvent) -> bool: ...
