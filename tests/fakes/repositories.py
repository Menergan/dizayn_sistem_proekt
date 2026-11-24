from datetime import datetime
from uuid import UUID

from app.domain.entities import Offer, Rental
from app.domain.enums import OfferStatus, RentalStatus


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
