from uuid import uuid4

import httpx
import pytest
from app.lifecycle.api import app
from app.lifecycle.service import Conflict
from app.domain.entities import Rental
from app.domain.enums import RentalStatus
from datetime import UTC, datetime
from decimal import Decimal
from app.schemas.offers import OfferResponse


class Service:
    async def start(self, offer_id):
        return Rental(uuid4(), "u", "s", "RU", "RUB", Decimal("50"), 5,
                      Decimal("300"), datetime.now(UTC), RentalStatus.ACTIVE, powerbank_id="pb")

    async def returned(self, event):
        raise Conflict("No active rental")


class OfferService:
    async def create(self, station_id, user_id):
        return OfferResponse(
            offer_id=uuid4(),
            station_id=station_id,
            user_id=user_id,
            country="RU",
            currency="RUB",
            price_per_hour=Decimal("50"),
            free_period_min=5,
            deposit=Decimal("300"),
            expires_at=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_routes_and_callback_auth(monkeypatch):
    monkeypatch.setenv("STATION_CALLBACK_TOKEN", "test-token")
    monkeypatch.setattr(app.state, "lifecycle", Service(), raising=False)
    monkeypatch.setattr(app.state, "offer_service", OfferService(), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        offer = await client.post("/offers", json={"station_id": "s", "user_id": "u"})
        assert offer.status_code == 201 and offer.json()["station_id"] == "s"
        result = await client.post("/rentals", json={"offer_id": str(uuid4())})
        assert result.status_code == 200 and result.json()["status"] == "ACTIVE"
        event = {"station_id": "finish", "powerbank_id": "pb", "returned_at": datetime.now(UTC).isoformat(), "station_event_id": str(uuid4())}
        assert (await client.post("/station-events/powerbank-returned", json=event)).status_code == 401
        result = await client.post("/station-events/powerbank-returned", json=event, headers={"Authorization": "Bearer test-token"})
        assert result.status_code == 409


@pytest.mark.asyncio
async def test_emulator_passes_callback_token(monkeypatch):
    import external_services.main as emulator
    captured = []
    original_client = httpx.AsyncClient

    async def callback(request):
        captured.append(request.headers.get("authorization"))
        return httpx.Response(200, json={})

    monkeypatch.setenv("STATION_CALLBACK_TOKEN", "station-secret")
    monkeypatch.setattr(emulator.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(callback), **kwargs))
    emulator.failures.clear()
    event = emulator.ReturnEvent(station_id="s", powerbank_id="pb", returned_at=datetime.now(UTC), station_event_id=uuid4())
    assert (await emulator.send_return_event(event))["callback_status"] == 200
    assert captured == ["Bearer station-secret"]
