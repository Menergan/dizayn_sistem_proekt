from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, select, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.entities import Rental
from app.domain.enums import RentalStatus
from app.persistence.models import Base, OfferModel, RentalModel, StationEventModel
from app.persistence.repositories import SqlAlchemyPaymentOperationRepository, _rental_from_model
from app.lifecycle.service import Conflict


class LifecycleModel(Base):
    __tablename__ = "rental_lifecycle"
    rental_id: Mapped[UUID] = mapped_column(ForeignKey("rentals.id", ondelete="CASCADE"), primary_key=True)
    offer_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    station_operation_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)


class LifecycleStore:
    def __init__(self, factory):
        self.factory = factory
        self._scan_after = None
        self.operations = SqlAlchemyPaymentOperationRepository(factory)
        self.lock_engine = create_async_engine(factory.kw["bind"].url, poolclass=NullPool)
        self.lock_factory = async_sessionmaker(self.lock_engine)

    @asynccontextmanager
    async def lock(self, rental_id):
        # Separate connection: business writes can commit while this lock stays held.
        # Transaction-scoped lock is released on rollback even after cancellation.
        async with self.lock_factory.begin() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(rental_id)})
            yield

    async def start(self, offer_id, now):
        async with self.factory.begin() as session:
            offer = await session.scalar(select(OfferModel).where(OfferModel.id == offer_id).with_for_update())
            previous = await session.scalar(select(LifecycleModel).where(LifecycleModel.offer_id == offer_id))
            if previous:
                return previous.rental_id
            if offer is None or offer.status != "AVAILABLE" or offer.expires_at <= now:
                raise Conflict("Offer missing, expired or already used")
            rental_id = uuid4()
            session.add(RentalModel(
                id=rental_id, user_id=offer.user_id, start_station_id=offer.station_id,
                country=offer.country, currency=offer.currency, price_per_hour=offer.price_per_hour,
                free_period_min=offer.free_period_min, deposit=offer.deposit,
                started_at=now, status="CREATING",
            ))
            await session.flush()
            session.add(LifecycleModel(rental_id=rental_id, offer_id=offer_id,
                                       phase="reserve", station_operation_id=f"rental:{rental_id}:eject"))
            offer.status = "USED"
        return rental_id

    async def returned(self, event, now):
        async with self.factory() as session:
            previous = await session.get(StationEventModel, str(event.station_event_id))
            rental_id = previous.rental_id if previous else await session.scalar(
                select(RentalModel.id).where(RentalModel.powerbank_id == event.powerbank_id,
                                             RentalModel.status == "ACTIVE"))
        if rental_id is None:
            raise Conflict("No active rental for return")
        async with self.lock(rental_id):
            return await self._returned(event, now)

    async def _returned(self, event, now):
        async with self.factory.begin() as session:
            event_id = str(event.station_event_id)
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "event:" + event_id})
            previous = await session.get(StationEventModel, event_id)
            if previous:
                if (previous.station_id, previous.powerbank_id, previous.returned_at) != (event.station_id, event.powerbank_id, event.returned_at):
                    raise Conflict("Event ID reused with different payload")
                if previous.rental_id is None:
                    raise Conflict("Event has no rental")
                return previous.rental_id
            rental = await session.scalar(select(RentalModel).where(
                RentalModel.powerbank_id == event.powerbank_id, RentalModel.status == "ACTIVE"
            ).with_for_update())
            if rental is None or event.returned_at < rental.started_at:
                raise Conflict("No active rental or return precedes start")
            rental.status = "RETURNING"
            rental.finish_station_id = event.station_id
            rental.finished_at = event.returned_at
            session.add(StationEventModel(id=event_id, station_id=event.station_id,
                powerbank_id=event.powerbank_id, returned_at=event.returned_at,
                rental_id=rental.id, received_at=now))
            return rental.id

    async def load(self, rental_id):
        async with self.factory() as session:
            rental = await session.get(RentalModel, rental_id)
            state = await session.get(LifecycleModel, rental_id)
            if rental is None or state is None:
                raise Conflict("Rental lifecycle not found")
            return _rental_from_model(rental), state.phase

    async def save(self, rental, phase):
        async with self.factory.begin() as session:
            await session.merge(RentalModel(**asdict(rental)))
            state = await session.get(LifecycleModel, rental.id)
            state.phase = phase

    async def payment(self, rental_id, kind, amount):
        await self.operations.get_or_create_key(rental_id, kind.upper(), amount)
        return await self.operations.get(rental_id, kind.upper())

    async def payment_result(self, rental_id, kind, result):
        await self.operations.save_result(rental_id, kind.upper(),
            "SUCCEEDED" if result.successful else "FAILED", result.operation_id,
            {"successful": result.successful})

    async def pending(self, limit):
        # Rotate through pending IDs so permanent failures cannot starve later work.
        statement = select(RentalModel.id).join(LifecycleModel).where(
            RentalModel.status.in_(["CREATING", "RETURNING"])
        ).order_by(RentalModel.id).limit(limit)
        async with self.factory() as session:
            page = statement if self._scan_after is None else statement.where(
                RentalModel.id > self._scan_after)
            ids = list(await session.scalars(page))
            if not ids and self._scan_after is not None:
                ids = list(await session.scalars(statement))
        self._scan_after = ids[-1] if ids else None
        return ids
