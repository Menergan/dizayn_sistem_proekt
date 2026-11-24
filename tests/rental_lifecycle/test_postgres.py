"""Run on a migrated, dedicated PostgreSQL database via LIFECYCLE_TEST_DATABASE_URL."""
import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from app.domain.entities import Offer
from app.domain.enums import RentalStatus
from app.lifecycle.store import LifecycleStore
from app.lifecycle.service import Conflict
from app.persistence.database import create_session_factory
from app.persistence.models import OfferModel, RentalModel, StationEventModel
from app.persistence.repositories import SqlAlchemyOfferRepository
from app.schemas.station_events import PowerbankReturnedEvent

pytestmark = pytest.mark.skipif(not os.getenv("LIFECYCLE_TEST_DATABASE_URL"), reason="Dedicated migrated PostgreSQL required")


@pytest_asyncio.fixture
async def store():
    factory = create_session_factory(os.environ["LIFECYCLE_TEST_DATABASE_URL"])
    store = LifecycleStore(factory)
    try:
        yield store
    finally:
        await store.lock_engine.dispose()
        await factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_atomic_start_return_and_conflicting_event(store):
    now = datetime.now(UTC)
    offer = Offer(uuid4(), "lifecycle-test", "s", "RU", "RUB", Decimal("50"), 5,
                  Decimal("300"), now, now + timedelta(minutes=5))
    repo = SqlAlchemyOfferRepository(store.factory)
    await repo.save(offer)
    rental_id = None
    event_id = uuid4()
    try:
        ids = await asyncio.gather(*(store.start(offer.id, now) for _ in range(8)))
        assert len(set(ids)) == 1
        rental_id = ids[0]
        rental, phase = await store.load(rental_id)
        assert rental.status == RentalStatus.CREATING and phase == "reserve"
        assert await repo.claim_available(offer.id, now) is None
        rental.status, rental.powerbank_id = RentalStatus.ACTIVE, str(uuid4())
        await store.save(rental, "eject")
        event = PowerbankReturnedEvent(station_id="finish", powerbank_id=rental.powerbank_id,
                                      returned_at=now, station_event_id=event_id)
        assert await asyncio.gather(*(store.returned(event, now) for _ in range(8))) == [rental_id] * 8
        assert (await store.load(rental_id))[0].status == RentalStatus.RETURNING
        with pytest.raises(Conflict):
            await store.returned(event.model_copy(update={"station_id": "other"}), now)
    finally:
        async with store.factory.begin() as session:
            await session.execute(delete(StationEventModel).where(StationEventModel.id == str(event_id)))
            if rental_id:
                await session.execute(delete(RentalModel).where(RentalModel.id == rental_id))
            await session.execute(delete(OfferModel).where(OfferModel.id == offer.id))


@pytest.mark.asyncio
async def test_expired_offer_cannot_start(store):
    now = datetime.now(UTC)
    offer = Offer(uuid4(), "lifecycle-test", "s", "RU", "RUB", Decimal("50"), 5,
                  Decimal("300"), now - timedelta(minutes=6), now - timedelta(minutes=1))
    await SqlAlchemyOfferRepository(store.factory).save(offer)
    try:
        with pytest.raises(Conflict):
            await store.start(offer.id, now)
    finally:
        async with store.factory.begin() as session:
            await session.execute(delete(OfferModel).where(OfferModel.id == offer.id))


@pytest.mark.asyncio
async def test_service_with_postgres_and_emulator(store):
    import httpx
    from app.domain.entities import AppConfig
    from app.integrations.http import HTTPPaymentClient, HTTPStationClient
    from app.lifecycle.service import LifecycleService
    from tests.fakes.clients import FakeConfigClient
    from tests.fakes.cache import FakeCache
    from external_services.main import app, failures

    failures.clear()
    now = datetime.now(UTC)
    offer = Offer(uuid4(), "lifecycle-test", str(uuid4()), "RU", "RUB", Decimal("50"), 5,
                  Decimal("300"), now, now + timedelta(minutes=5))
    await SqlAlchemyOfferRepository(store.factory).save(offer)
    rental_id, event_id = None, uuid4()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://emulator") as client:
            service = LifecycleService(store, HTTPPaymentClient(client, "http://emulator"),
                HTTPStationClient(client, "http://emulator"),
                FakeConfigClient(AppConfig(Decimal("1"), 300)), FakeCache())
            rental = await service.start(offer.id)
            rental_id = rental.id
            assert rental.status == RentalStatus.ACTIVE
            assert (await service.start(offer.id)).id == rental_id
            event = PowerbankReturnedEvent(station_id="finish", powerbank_id=rental.powerbank_id,
                returned_at=datetime.now(UTC), station_event_id=event_id)
            result = await service.returned(event)
            assert result.status == RentalStatus.COMPLETED
            assert (await service.returned(event)).total_amount == result.total_amount
            assert (await store.operations.get(rental_id, "CAPTURE")).status == "SUCCEEDED"
            assert rental_id not in await store.pending(100)
    finally:
        async with store.factory.begin() as session:
            await session.execute(delete(StationEventModel).where(StationEventModel.id == str(event_id)))
            if rental_id:
                await session.execute(delete(RentalModel).where(RentalModel.id == rental_id))
            await session.execute(delete(OfferModel).where(OfferModel.id == offer.id))
