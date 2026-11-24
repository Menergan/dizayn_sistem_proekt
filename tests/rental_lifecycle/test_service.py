import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.domain.entities import AppConfig, EjectResponse, PaymentOperation, PaymentResult, Rental
from app.domain.enums import RentalStatus
from app.lifecycle.service import LifecycleService, Conflict
from app.schemas.station_events import PowerbankReturnedEvent
from tests.fakes.cache import FakeCache
from tests.fakes.clients import FakeConfigClient


class Store:
    def __init__(self):
        self.rental = Rental(uuid4(), "u", "s", "RU", "RUB", Decimal("50"), 5,
                             Decimal("300"), datetime.now(UTC), RentalStatus.CREATING)
        self.phase = "reserve"
        self.operations = {}
        self.mutex = asyncio.Lock()
        self.events = {}

    @asynccontextmanager
    async def lock(self, rental_id):
        async with self.mutex:
            yield

    async def start(self, offer_id, now):
        return self.rental.id

    async def returned(self, event, now):
        if event.station_event_id not in self.events:
            if self.rental.status != RentalStatus.ACTIVE:
                raise Conflict("Not active")
            self.rental.status = RentalStatus.RETURNING
            self.rental.finished_at = event.returned_at
            self.rental.finish_station_id = event.station_id
            self.events[event.station_event_id] = event
        return self.rental.id

    async def load(self, rental_id):
        return deepcopy(self.rental), self.phase

    async def save(self, rental, phase):
        self.rental, self.phase = deepcopy(rental), phase

    async def payment(self, rental_id, kind, amount):
        if kind not in self.operations:
            self.operations[kind] = PaymentOperation(rental_id, kind, f"rental:{rental_id}:{kind}", amount, "PENDING")
        return self.operations[kind]

    async def payment_result(self, rental_id, kind, result):
        self.operations[kind] = replace(self.operations[kind], status="SUCCEEDED" if result.successful else "FAILED")

    async def pending(self, limit):
        return [self.rental.id] if self.rental.status in {RentalStatus.CREATING, RentalStatus.RETURNING} else []


class Payments:
    def __init__(self):
        self.effects, self.calls = {}, []
        self.timeout, self.fail = set(), set()

    async def call(self, kind, user, rental, amount, key):
        self.calls.append((kind, key, amount))
        result = self.effects.setdefault(key, PaymentResult(key, kind not in self.fail))
        if kind in self.timeout:
            self.timeout.remove(kind)
            raise TimeoutError("response lost after external commit")
        return result

    async def reserve(self, *args):
        return await self.call("reserve", *args)

    async def capture(self, *args):
        return await self.call("capture", *args)

    async def release(self, *args):
        return await self.call("release", *args)


class Stations:
    def __init__(self):
        self.calls, self.effects = [], {}
        self.timeout = False
        self.success = True

    async def eject(self, station, key):
        self.calls.append(key)
        result = self.effects.setdefault(key, EjectResponse("pb" if self.success else None, self.success))
        if self.timeout:
            self.timeout = False
            raise TimeoutError("response lost after physical eject")
        return result


@pytest.fixture
def setup():
    store, payments, stations = Store(), Payments(), Stations()
    cache = FakeCache()
    service = LifecycleService(store, payments, stations,
        FakeConfigClient(AppConfig(Decimal("1"), 300, {"RU": 30})), cache)
    return service, store, payments, stations


@pytest.mark.asyncio
async def test_happy_path_and_duplicate_commands(setup):
    service, store, payments, stations = setup
    offer = uuid4()
    results = await asyncio.gather(*(service.start(offer) for _ in range(5)))
    assert all(r.status == RentalStatus.ACTIVE for r in results)
    assert len(payments.calls) == len(stations.calls) == 1
    store.rental.started_at -= timedelta(hours=2)
    event = PowerbankReturnedEvent(station_id="finish", powerbank_id="pb", returned_at=datetime.now(UTC), station_event_id=uuid4())
    first = await service.returned(event)
    again = await service.returned(event)
    assert first.status == again.status == RentalStatus.COMPLETED
    assert first.total_amount == Decimal("100.00")
    assert first.delete_after == event.returned_at + timedelta(days=30)
    assert len([c for c in payments.calls if c[0] == "capture"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reserve", "eject", "release", "capture"])
async def test_lost_response_recovers_with_same_key(setup, kind):
    service, store, payments, stations = setup
    if kind == "capture":
        await service.start(uuid4())
        store.rental.status = RentalStatus.RETURNING
        store.rental.finished_at = datetime.now(UTC)
    if kind == "eject":
        stations.timeout = True
    else:
        payments.timeout.add(kind)
    if kind == "release":
        stations.success = False
    with pytest.raises(TimeoutError):
        await service.advance(store.rental.id)
    assert store.rental.status in {RentalStatus.CREATING, RentalStatus.RETURNING}
    # New service instance simulates process restart; persisted store survives.
    restarted = LifecycleService(store, payments, stations, service.config, service.cache)
    await restarted.reconcile()
    assert store.rental.status == {"reserve": RentalStatus.ACTIVE, "eject": RentalStatus.ACTIVE,
                                   "release": RentalStatus.FAILED, "capture": RentalStatus.COMPLETED}[kind]
    calls = stations.calls if kind == "eject" else [c[1] for c in payments.calls if c[0] == kind]
    assert len(calls) == 2 and calls[0] == calls[1]
    if kind == "eject":
        assert "release" not in store.operations


@pytest.mark.asyncio
async def test_station_decline_compensates(setup):
    service, store, payments, stations = setup
    stations.success = False
    result = await service.start(uuid4())
    assert result.status == RentalStatus.FAILED
    assert [c[0] for c in payments.calls] == ["reserve", "release"]


@pytest.mark.asyncio
async def test_reserve_decline_never_ejects(setup):
    service, store, payments, stations = setup
    payments.fail.add("reserve")
    assert (await service.start(uuid4())).status == RentalStatus.FAILED
    assert not stations.calls


@pytest.mark.asyncio
async def test_failed_capture_stays_returning(setup):
    service, store, payments, stations = setup
    await service.start(uuid4())
    payments.fail.add("capture")
    event = PowerbankReturnedEvent(station_id="finish", powerbank_id="pb", returned_at=datetime.now(UTC), station_event_id=uuid4())
    assert (await service.returned(event)).status == RentalStatus.RETURNING
    await service.reconcile()
    assert store.rental.status == RentalStatus.RETURNING
    assert len({c[1] for c in payments.calls if c[0] == "capture"}) == 1


@pytest.mark.asyncio
async def test_rejects_naive_return(setup):
    service, *_ = setup
    event = PowerbankReturnedEvent(station_id="finish", powerbank_id="pb", returned_at=datetime.now(), station_event_id=uuid4())
    with pytest.raises(Conflict):
        await service.returned(event)


@pytest.mark.asyncio
async def test_cache_invalidated_even_when_external_response_is_lost(setup):
    service, store, payments, stations = setup
    key = f"rental:{store.rental.id}"
    await service.cache.set(key, b"old", 300)
    stations.timeout = True
    with pytest.raises(TimeoutError):
        await service.start(uuid4())
    assert await service.cache.get(key) is None
