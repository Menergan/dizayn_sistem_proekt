import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.domain.enums import RentalStatus
from app.services.rental_read import RentalReadService

logger = logging.getLogger(__name__)


class Conflict(ValueError):
    pass


class LifecycleService:
    """Store serializes each rental across API instances and reconcilers.

    Each store write commits before the next external command. Unknown outcomes
    remain pending and are replayed with exactly the same external key.
    """
    def __init__(self, store, payments, stations, config, cache):
        self.store, self.payments, self.stations = store, payments, stations
        self.config, self.cache = config, cache

    async def invalidate(self, rental_id):
        try:
            await self.cache.delete(f"rental:{rental_id}")
        except Exception:
            logger.exception("lifecycle_cache_invalidation_failed")

    async def start(self, offer_id):
        rental_id = await self.store.start(offer_id, datetime.now(UTC))
        return await self.advance(rental_id)

    async def returned(self, event):
        now = datetime.now(UTC)
        if event.returned_at.tzinfo is None or event.returned_at > now:
            raise Conflict("Return timestamp must have a timezone and cannot be in the future")
        rental_id = await self.store.returned(event, now)
        await self.invalidate(rental_id)
        return await self.advance(rental_id)

    async def payment(self, rental, kind, amount):
        operation = await self.store.payment(rental.id, kind, amount)
        if operation.status == "SUCCEEDED":
            return True
        if operation.status == "FAILED" and kind == "reserve":
            return False
        result = await getattr(self.payments, kind)(
            rental.user_id, rental.id, operation.amount, operation.idempotency_key
        )
        await self.store.payment_result(rental.id, kind, result)
        return result.successful

    async def advance(self, rental_id):
        async with self.store.lock(rental_id):
            rental, phase = await self.store.load(rental_id)
            try:
                if rental.status == RentalStatus.CREATING:
                    if phase == "reserve":
                        if not await self.payment(rental, "reserve", rental.deposit):
                            rental.status = RentalStatus.FAILED
                        else:
                            phase = "eject"
                        await self.store.save(rental, phase)
                    if rental.status == RentalStatus.CREATING and phase == "eject":
                        result = await self.stations.eject(
                            rental.start_station_id, f"rental:{rental.id}:eject"
                        )
                        if result.successful:
                            if not result.powerbank_id:
                                raise RuntimeError("Successful eject without powerbank: outcome unknown")
                            rental.powerbank_id = result.powerbank_id
                            rental.started_at = datetime.now(UTC)
                            rental.status = RentalStatus.ACTIVE
                        else:
                            phase = "release"
                        await self.store.save(rental, phase)
                    if rental.status == RentalStatus.CREATING and phase == "release":
                        if await self.payment(rental, "release", rental.deposit):
                            rental.status = RentalStatus.FAILED
                            await self.store.save(rental, phase)
                if rental.status == RentalStatus.RETURNING:
                    if rental.total_amount is None:
                        rental.total_amount = RentalReadService._calculate_amount(
                            replace(rental, status=RentalStatus.ACTIVE), rental.finished_at
                        )
                        await self.store.save(rental, phase)
                    config = await self.config.get_config()
                    days = config.retention_days_by_country.get(rental.country, 365)
                    if days <= 0:
                        raise ValueError("Retention must be positive")
                    if await self.payment(rental, "capture", rental.total_amount):
                        rental.status = RentalStatus.COMPLETED
                        rental.delete_after = rental.finished_at + timedelta(days=days)
                        await self.store.save(rental, phase)
            finally:
                await self.invalidate(rental_id)
            return rental

    async def reconcile(self, limit=100):
        for rental_id in await self.store.pending(limit):
            try:
                await self.advance(rental_id)
            except Exception:
                logger.exception("lifecycle_reconciliation_pending", extra={"rental_id": str(rental_id)})
