import asyncio
import os
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.integrations.dto import ConfigDTO, EjectDTO, PaymentDTO, StationDTO, TariffDTO, UserDTO

app = FastAPI(title="External services emulator")
failures: dict[str, str] = {}
ejections: dict[str, tuple[str, EjectDTO]] = {}
payments: dict[str, tuple[tuple, PaymentDTO]] = {}
inventory: dict[str, list[str]] = {}
events: dict[str, dict] = {}


class Failure(BaseModel):
    mode: str = Field(pattern="^(none|error|timeout|error_after|timeout_after)$")


@app.put("/admin/failures/{service}")
async def set_failure(service: str, failure: Failure):
    if service not in {"stations", "payments", "users", "tariffs", "configs"}:
        raise HTTPException(404, "Unknown service")
    failures[service] = failure.mode
    return {"service": service, "mode": failure.mode}


async def maybe_fail(service: str):
    mode = failures.get(service)
    if mode == "error":
        raise HTTPException(500, f"Simulated {service} failure")
    if mode == "timeout":
        await asyncio.sleep(float(os.getenv("EMULATOR_TIMEOUT_SECONDS", "3")))


async def maybe_fail_after(service: str):
    mode = failures.get(service)
    if mode == "error_after":
        raise HTTPException(500, f"Simulated {service} failure after commit")
    if mode == "timeout_after":
        await asyncio.sleep(float(os.getenv("EMULATOR_TIMEOUT_SECONDS", "3")))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/stations/{station_id}", response_model=StationDTO)
async def station(station_id: str):
    await maybe_fail("stations")
    banks = inventory.setdefault(station_id, [] if station_id == "empty-station-id" else [f"{station_id}-bank-{i}" for i in range(1, 4)])
    return StationDTO(id=station_id, tariff_id="tariff18", country="RU", available_powerbanks=len(banks))


class EjectRequest(BaseModel):
    operation_id: str = Field(min_length=1)


@app.post("/stations/{station_id}/eject", response_model=EjectDTO)
async def eject(station_id: str, request: EjectRequest):
    await maybe_fail("stations")
    existing = ejections.get(request.operation_id)
    if existing:
        if existing[0] != station_id:
            raise HTTPException(409, "Operation ID belongs to another station")
        await maybe_fail_after("stations")
        return existing[1]
    banks = inventory.setdefault(station_id, [] if station_id == "empty-station-id" else [f"{station_id}-bank-{i}" for i in range(1, 4)])
    result = EjectDTO(successful=bool(banks), powerbank_id=banks.pop() if banks else None)
    ejections[request.operation_id] = (station_id, result)
    await maybe_fail_after("stations")
    return result


class PaymentRequest(BaseModel):
    user_id: str = Field(min_length=1)
    rental_id: UUID
    amount: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=1)


@app.post("/payments/{operation}", response_model=PaymentDTO)
async def payment(operation: str, request: PaymentRequest):
    await maybe_fail("payments")
    if operation not in {"reserve", "capture", "release"}:
        raise HTTPException(404, "Unknown payment operation")
    payload = (operation, request.user_id, request.rental_id, request.amount)
    existing = payments.get(request.idempotency_key)
    if existing:
        if existing[0] != payload:
            raise HTTPException(409, "Idempotency key reused with different data")
        await maybe_fail_after("payments")
        return existing[1]
    result = PaymentDTO(operation_id=str(uuid4()), successful=True)
    payments[request.idempotency_key] = (payload, result)
    await maybe_fail_after("payments")
    return result


@app.get("/tariffs/{tariff_id}", response_model=TariffDTO)
async def tariff(tariff_id: str):
    await maybe_fail("tariffs")
    return TariffDTO(id=tariff_id, currency="RUB", price_per_hour=Decimal("50"), free_period_min=5, default_deposit=Decimal("300"))


@app.get("/users/{user_id}", response_model=UserDTO)
async def user(user_id: str):
    await maybe_fail("users")
    return UserDTO(id=user_id, has_subscription=False, trusted=False)


@app.get("/configs", response_model=ConfigDTO)
async def config():
    await maybe_fail("configs")
    return ConfigDTO(last_banks_increase=Decimal("1.5"), tariffs_ttl_seconds=300, retention_days_by_country={"RU": 365})


class ReturnEvent(BaseModel):
    station_id: str = Field(min_length=1)
    powerbank_id: str = Field(min_length=1)
    returned_at: datetime
    station_event_id: UUID


@app.post("/admin/return-events")
async def send_return_event(event: ReturnEvent):
    await maybe_fail("stations")
    payload = event.model_dump(mode="json")
    event_id = str(event.station_event_id)
    previous = events.get(event_id)
    if previous is not None and previous != payload:
        raise HTTPException(409, "Event ID reused with different data")
    if previous is None:
        events[event_id] = payload
    url = os.getenv("RENTAL_CALLBACK_URL", "http://rental-api:8000/station-events/powerbank-returned")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Rental callback failed; retry with the same event ID") from exc
    return {"station_event_id": event_id, "callback_status": response.status_code}
