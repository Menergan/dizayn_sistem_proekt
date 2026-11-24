from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.entities import Offer, PaymentOperation, Rental, StationEvent
from app.domain.enums import OfferStatus, PaymentOperationStatus, RentalStatus


class FakeOfferRepository:
    def __init__(self) -> None:
        self.offers: dict[UUID, Offer] = {}

    async def save(self, offer: Offer) -> None:
        self.offers[offer.id] = offer

    async def claim_available(self, offer_id: UUID, now: datetime) -> Offer | None:
        offer = self.offers.get(offer_id)
        if offer is None or offer.status is not OfferStatus.AVAILABLE:
            return None
        if offer.expires_at <= now:
            offer.status = OfferStatus.EXPIRED
            return None
        offer.status = OfferStatus.USED
        return offer

    async def delete_expired(self, before: datetime, limit: int) -> int:
        expired = [
            offer_id
            for offer_id, offer in self.offers.items()
            if offer.expires_at <= before and offer.status is OfferStatus.AVAILABLE
        ][:limit]
        for offer_id in expired:
            del self.offers[offer_id]
        return len(expired)


class FakeRentalRepository:
    def __init__(self) -> None:
        self.rentals: dict[UUID, Rental] = {}

    async def save(self, rental: Rental) -> None:
        self.rentals[rental.id] = rental

    async def get(self, rental_id: UUID) -> Rental | None:
        return self.rentals.get(rental_id)

    async def find_active_by_powerbank(self, powerbank_id: str) -> Rental | None:
        return next(
            (
                rental
                for rental in self.rentals.values()
                if rental.powerbank_id == powerbank_id
                and rental.status is RentalStatus.ACTIVE
            ),
            None,
        )

    async def change_status(self, rental_id: UUID, status: RentalStatus) -> Rental:
        rental = self.rentals[rental_id]
        rental.status = status
        return rental

    async def delete_expired(self, before: datetime, limit: int) -> int:
        expired = [
            rental_id
            for rental_id, rental in self.rentals.items()
            if rental.delete_after is not None and rental.delete_after <= before
        ][:limit]
        for rental_id in expired:
            del self.rentals[rental_id]
        return len(expired)


class FakeStationEventRepository:
    def __init__(self) -> None:
        self.events: dict[str, StationEvent] = {}

    async def save_if_new(self, event: StationEvent) -> bool:
        if event.id in self.events:
            return False
        self.events[event.id] = event
        return True


class FakePaymentOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[tuple[UUID, str], PaymentOperation] = {}

    async def get_or_create_key(
        self, rental_id: UUID, operation_type: str, amount: Decimal
    ) -> str:
        operation_key = (rental_id, operation_type)
        operation = self.operations.get(operation_key)
        if operation is not None:
            if operation.amount != amount:
                raise ValueError("Payment operation amount differs from the saved amount")
            return operation.idempotency_key
        idempotency_key = f"rental:{rental_id}:{operation_type.lower()}"
        self.operations[operation_key] = PaymentOperation(
            rental_id=rental_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            amount=amount,
            status=PaymentOperationStatus.PENDING.value,
        )
        return idempotency_key

    async def save_result(
        self,
        rental_id: UUID,
        operation_type: str,
        status: str,
        external_operation_id: str | None,
        external_response: dict[str, object] | None,
    ) -> None:
        operation_key = (rental_id, operation_type)
        operation = self.operations.get(operation_key)
        if operation is None:
            raise LookupError("Payment operation was not found")
        self.operations[operation_key] = replace(
            operation,
            status=status,
            external_operation_id=external_operation_id,
            external_response=external_response,
        )

    async def get(
        self, rental_id: UUID, operation_type: str
    ) -> PaymentOperation | None:
        return self.operations.get((rental_id, operation_type))
