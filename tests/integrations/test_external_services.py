import asyncio
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.domain.entities import AppConfig, TariffData
from app.integrations.cache import CachedConfigClient, CachedTariffClient, FallbackUserClient
from app.integrations.http import (
    ExternalOperationUnknown, ExternalServiceError, ExternalServiceUnavailable, HTTPConfigClient,
    HTTPPaymentClient, HTTPStationClient, HTTPTariffClient, HTTPUserClient,
)
from external_services.main import app, ejections, events, failures, inventory, payments


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def client():
    failures.clear(); ejections.clear(); inventory.clear(); payments.clear(); events.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://emulator") as session:
        yield session


@pytest.mark.asyncio
async def test_http_contracts_and_idempotency(client):
    url = "http://emulator"
    stations = HTTPStationClient(client, url)
    tariff = HTTPTariffClient(client, url)
    users = HTTPUserClient(client, url)
    config = HTTPConfigClient(client, url)
    payment = HTTPPaymentClient(client, url)
    station = await stations.get_station("a")
    assert station.available_powerbanks == 3
    assert (await tariff.get_tariff(station.tariff_id)).currency == "RUB"
    assert not (await users.get_user("u")).trusted
    assert (await config.get_config()).retention_days_by_country["RU"] == 365
    first = await stations.eject("a", "eject-1")
    assert await stations.eject("a", "eject-1") == first
    assert (await stations.get_station("a")).available_powerbanks == 2
    assert not (await stations.eject("empty-station-id", "empty-1")).successful
    rental_id = uuid4()
    result = await payment.reserve("u", rental_id, Decimal("300"), "key")
    assert await payment.reserve("u", rental_id, Decimal("300"), "key") == result
    with pytest.raises(ExternalServiceError) as error:
        await payment.reserve("u", rental_id, Decimal("301"), "key")
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_users_fallback_only_for_technical_failures(client, caplog):
    users = FallbackUserClient(HTTPUserClient(client, "http://emulator", retries=0))
    await client.put("/admin/failures/users", json={"mode": "error"})
    profile = await users.get_user("u")
    assert not profile.has_subscription and not profile.trusted
    assert any(getattr(record, "event", None) == "user_fallback" for record in caplog.records)
    async def missing(request):
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(missing)) as other:
        with pytest.raises(ExternalServiceError):
            await FallbackUserClient(HTTPUserClient(other, "http://emulator", retries=0)).get_user("u")


@pytest.mark.asyncio
async def test_timeout_retry_reuses_payment_key():
    calls = []
    async def handler(request):
        calls.append(request.content)
        if len(calls) == 1:
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"operation_id": "one", "successful": True})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HTTPPaymentClient(client, "http://emulator").reserve("u", uuid4(), Decimal("3"), "same-key")
    assert result.successful and len(calls) == 2 and calls[0] == calls[1]


@pytest.mark.asyncio
async def test_tariff_cache_lru_expiry_and_unavailability(client):
    now = [0.0]
    class Config:
        async def get_config(self):
            return AppConfig(Decimal("1.5"), 900)
    cache = CachedTariffClient(HTTPTariffClient(client, "http://emulator", retries=0), Config(), capacity=2, clock=lambda: now[0])
    await cache.get_tariff("a"); await cache.get_tariff("b"); await cache.get_tariff("a"); await cache.get_tariff("c")
    await client.put("/admin/failures/tariffs", json={"mode": "error"})
    assert (await cache.get_tariff("a")).id == "a"
    with pytest.raises(ExternalServiceUnavailable):
        await cache.get_tariff("b")
    now[0] = 600
    with pytest.raises(ExternalServiceUnavailable):
        await cache.get_tariff("a")


@pytest.mark.asyncio
async def test_config_initial_failure_and_refresh_fallback(client):
    upstream = HTTPConfigClient(client, "http://emulator", retries=0)
    cache = CachedConfigClient(upstream, interval=0.01)
    await client.put("/admin/failures/configs", json={"mode": "error"})
    with pytest.raises(ExternalServiceUnavailable):
        await cache.start()
    with pytest.raises(RuntimeError):
        await cache.get_config()
    await client.put("/admin/failures/configs", json={"mode": "none"})
    await cache.start()
    try:
        before = await cache.get_config()
        await client.put("/admin/failures/configs", json={"mode": "error"})
        await asyncio.sleep(0.03)
        assert await cache.get_config() == before
    finally:
        await cache.close()


@pytest.mark.asyncio
async def test_lost_responses_do_not_repeat_mutations(client):
    url = "http://emulator"
    stations = HTTPStationClient(client, url, retries=0)
    payment = HTTPPaymentClient(client, url, retries=0)
    rental_id = uuid4()
    await client.put("/admin/failures/stations", json={"mode": "error_after"})
    with pytest.raises(ExternalServiceUnavailable):
        await stations.eject("s", "eject-unknown")
    await client.put("/admin/failures/stations", json={"mode": "none"})
    first = await stations.eject("s", "eject-unknown")
    assert first.successful
    assert (await stations.get_station("s")).available_powerbanks == 2

    await client.put("/admin/failures/payments", json={"mode": "error_after"})
    with pytest.raises(ExternalServiceUnavailable):
        await payment.reserve("u", rental_id, Decimal("300"), "reserve-unknown")
    await client.put("/admin/failures/payments", json={"mode": "none"})
    first_payment = await payment.reserve("u", rental_id, Decimal("300"), "reserve-unknown")
    assert await payment.reserve("u", rental_id, Decimal("300"), "reserve-unknown") == first_payment
    assert len(payments) == 1


@pytest.mark.asyncio
async def test_callback_repeats_same_payload_and_rejects_conflict(client, monkeypatch):
    import external_services.main as emulator
    sent = []

    class CallbackClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            sent.append((url, json))
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(emulator.httpx, "AsyncClient", CallbackClient)
    event = {"station_id": "s", "powerbank_id": "b", "returned_at": "2026-11-24T10:00:00Z", "station_event_id": "c702c35f-704f-4c50-8c87-92cb6711dba1"}
    assert (await client.post("/admin/return-events", json=event)).status_code == 200
    assert (await client.post("/admin/return-events", json=event)).status_code == 200
    assert sent[0] == sent[1]
    assert (await client.post("/admin/return-events", json={**event, "powerbank_id": "other"})).status_code == 409


def test_config_ttl_matches_adr():
    from pydantic import ValidationError
    from app.integrations.dto import ConfigDTO
    for ttl in (1, 600):
        assert ConfigDTO.model_validate({"last_banks_increase": "1.5", "tariffs_ttl_seconds": ttl}).tariffs_ttl_seconds == ttl
    for ttl in (0, 601):
        with pytest.raises(ValidationError):
            ConfigDTO.model_validate({"last_banks_increase": "1.5", "tariffs_ttl_seconds": ttl})


@pytest.mark.asyncio
async def test_unrelated_cache_hit_does_not_wait_for_slow_miss():
    started, finish = asyncio.Event(), asyncio.Event()
    class Config:
        async def get_config(self):
            return AppConfig(Decimal("1.5"), 300)
    class Upstream:
        def __init__(self):
            self.calls = []
        async def get_tariff(self, tariff_id):
            self.calls.append(tariff_id)
            if tariff_id == "slow":
                started.set()
                await finish.wait()
            return TariffData(tariff_id, "RUB", Decimal("50"), 5, Decimal("300"))
    upstream = Upstream()
    cache = CachedTariffClient(upstream, Config())
    await cache.get_tariff("warm")
    slow = asyncio.create_task(cache.get_tariff("slow"))
    same = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        same = asyncio.create_task(cache.get_tariff("slow"))
        assert (await asyncio.wait_for(cache.get_tariff("warm"), 1)).id == "warm"
        finish.set()
        assert (await slow).id == "slow"
        assert (await same).id == "slow"
        assert upstream.calls.count("slow") == 1
    finally:
        finish.set()
        await asyncio.gather(slow, *( [same] if same else [] ), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("client_type,method,payload", [
    (HTTPUserClient, "get_user", {"id": "other", "has_subscription": True, "trusted": True}),
    (HTTPTariffClient, "get_tariff", {"id": "other", "currency": "RUB", "price_per_hour": "50", "free_period_min": 5, "default_deposit": "300"}),
    (HTTPStationClient, "get_station", {"id": "other", "tariff_id": "t", "country": "RU", "available_powerbanks": 1}),
])
async def test_mismatched_upstream_identity_is_rejected(client_type, method, payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        with pytest.raises(ExternalServiceError, match="ID does not match"):
            await getattr(client_type(http, "http://emulator"), method)("requested")


@pytest.mark.asyncio
async def test_return_event_contract(client, monkeypatch):
    import external_services.main as emulator
    from app.schemas.station_events import PowerbankReturnedEvent
    class CallbackClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            PowerbankReturnedEvent.model_validate(json)
            return httpx.Response(200, request=httpx.Request("POST", url))
    monkeypatch.setattr(emulator.httpx, "AsyncClient", CallbackClient)
    event = {"station_id": "empty-station-id", "powerbank_id": "returned-bank", "returned_at": "2026-11-24T10:00:00Z", "station_event_id": str(uuid4())}
    assert (await client.post("/admin/return-events", json={**event, "station_event_id": "bad"})).status_code == 422
    assert (await client.post("/admin/return-events", json=event)).status_code == 200
    assert (await client.post("/admin/return-events", json=event)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('method,payload', [
    ('reserve', {'operation_id': 7}),
    ('eject', {'successful': True}),
])
async def test_invalid_command_response_has_unknown_outcome(method, payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        with pytest.raises(ExternalOperationUnknown):
            if method == 'reserve':
                await HTTPPaymentClient(http, 'http://emulator', retries=0).reserve('u', uuid4(), Decimal('50'), 'key')
            else:
                await HTTPStationClient(http, 'http://emulator', retries=0).eject('station', 'key')


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reserve", "capture", "release"])
async def test_payment_commands_are_idempotent(client, operation):
    payment = HTTPPaymentClient(client, "http://emulator", retries=0)
    rental_id = uuid4()
    method = getattr(payment, operation)
    first = await method("u", rental_id, Decimal("100"), "same-key")
    assert first.successful
    assert await method("u", rental_id, Decimal("100"), "same-key") == first
    with pytest.raises(ExternalServiceError) as exc:
        await method("u", rental_id, Decimal("101"), "same-key")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_real_http_timeout_and_user_fallback(monkeypatch):
    import os
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'EMULATOR_TIMEOUT_SECONDS': '0.5'}
    process = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'external_services.main:app', '--host', '127.0.0.1', '--port', str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f'http://127.0.0.1:{port}'
    try:
        async with httpx.AsyncClient(timeout=1.0) as http:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = await http.get(url + '/health')
                    if response.status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError('emulator did not start')
                await asyncio.sleep(0.05)
            assert (await http.put(url + '/admin/failures/users', json={'mode': 'timeout'})).status_code == 200
            monkeypatch.setenv('USERS_READ_TIMEOUT_SECONDS', '0.05')
            users = FallbackUserClient(HTTPUserClient(http, url, retries=0))
            profile = await users.get_user('u')
            assert not profile.has_subscription and not profile.trusted
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.asyncio
async def test_integration_failures_include_structured_log_fields(caplog):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as http:
        with pytest.raises(ExternalServiceUnavailable):
            await HTTPTariffClient(http, "http://emulator", retries=0).get_tariff("a")
    records = [record for record in caplog.records if getattr(record, "event", None) == "integration_error"]
    assert records and records[-1].service == "tariffs" and records[-1].method == "GET"
