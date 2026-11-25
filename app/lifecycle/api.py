import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request
from app.main import app
from app.integrations.http import ExternalServiceError
from app.lifecycle.runtime import runtime
from app.lifecycle.service import Conflict
from app.schemas.rentals import StartRentalRequest, RentalResponse
from app.schemas.station_events import PowerbankReturnedEvent
from app.services.rental_read import RentalReadService

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    if not os.getenv("STATION_CALLBACK_TOKEN"):
        raise RuntimeError("STATION_CALLBACK_TOKEN is required")
    async with original_lifespan(application):
        async with runtime(application) as service:
            application.state.lifecycle = service
            yield


app.router.lifespan_context = lifespan


async def respond(command):
    try:
        rental = await command
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(503, "External operation pending; retry the same command") from exc
    return RentalReadService._to_response(rental, datetime.now(UTC))


@app.post("/rentals", response_model=RentalResponse)
async def start_rental(body: StartRentalRequest, request: Request):
    return await respond(request.app.state.lifecycle.start(body.offer_id))


@app.post("/station-events/powerbank-returned", response_model=RentalResponse)
async def powerbank_returned(body: PowerbankReturnedEvent, request: Request,
                             authorization: str = Header(default="")):
    expected = os.getenv("STATION_CALLBACK_TOKEN", "")
    if not expected or not secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Station authentication required")
    return await respond(request.app.state.lifecycle.returned(body))
