from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Offer, Rental
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


class PaymentOperationRepository(Protocol):
    async def get_or_create_key(self, rental_id: UUID, operation_type: str) -> str: ...
