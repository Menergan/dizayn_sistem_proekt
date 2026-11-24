from dataclasses import dataclass
from datetime import datetime

from app.ports.repositories import OfferRepository, RentalRepository


@dataclass(frozen=True)
class CleanupResult:
    deleted_offers: int
    deleted_rentals: int


class PersistenceCleanupWorker:
    def __init__(
        self,
        offer_repository: OfferRepository,
        rental_repository: RentalRepository,
        batch_size: int = 1_000,
    ) -> None:
        self._offer_repository = offer_repository
        self._rental_repository = rental_repository
        self._batch_size = batch_size

    async def run_once(self, now: datetime) -> CleanupResult:
        deleted_offers = await self._offer_repository.delete_expired(now, self._batch_size)
        deleted_rentals = await self._rental_repository.delete_expired(now, self._batch_size)
        return CleanupResult(deleted_offers=deleted_offers, deleted_rentals=deleted_rentals)
