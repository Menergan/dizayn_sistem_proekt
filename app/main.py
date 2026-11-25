
import os
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.cache.redis import RedisCache
from app.integrations.cache import CachedConfigClient, CachedTariffClient, FallbackUserClient
from app.integrations.http import (
    ExternalServiceError,
    HTTPConfigClient,
    HTTPPaymentClient,
    HTTPStationClient,
    HTTPTariffClient,
    HTTPUserClient,
)
from app.persistence.database import create_session_factory
from app.persistence.repositories import SqlAlchemyOfferRepository, SqlAlchemyRentalRepository
from app.schemas.offers import CreateOfferRequest, OfferResponse
from app.schemas.rentals import RentalResponse
from app.services.offers import OfferService, OfferUnavailableError
from app.services.rental_read import (
    RentalNotFoundError,
    RentalReadUnavailableError,
    RentalReadService,
)

from time import perf_counter
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.observability.metrics import (
    HTTP_REQUESTS,
    HTTP_REQUEST_DURATION,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    session_factory = create_session_factory(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://rental:rental@localhost:5432/rental",
        )
    )
    cache = RedisCache.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    base_url = os.getenv("EXTERNAL_SERVICES_URL", "http://localhost:3629")
    http_client = httpx.AsyncClient()
    configs = CachedConfigClient(
        HTTPConfigClient(http_client, os.getenv("CONFIGS_URL", base_url))
    )

    repository = SqlAlchemyRentalRepository(session_factory)
    app.state.session_factory = session_factory
    app.state.cache = cache
    app.state.http_client = http_client
    app.state.config_client = configs
    app.state.station_client = HTTPStationClient(
        http_client, os.getenv("STATIONS_URL", base_url)
    )
    app.state.payment_client = HTTPPaymentClient(
        http_client, os.getenv("PAYMENTS_URL", base_url)
    )

    app.state.rental_read_service = RentalReadService(
        repository=repository,
        cache=cache,
    )
    await configs.start()
    app.state.offer_service = OfferService(
        repository=SqlAlchemyOfferRepository(session_factory),
        stations=app.state.station_client,
        tariffs=CachedTariffClient(
            HTTPTariffClient(http_client, os.getenv("TARIFFS_URL", base_url)),
            configs,
        ),
        users=FallbackUserClient(
            HTTPUserClient(http_client, os.getenv("USERS_URL", base_url))
        ),
        configs=configs,
    )

    yield

    await configs.close()
    await http_client.aclose()
    await cache.close()
    await session_factory.kw["bind"].dispose()


app = FastAPI(
    title="Rental API",
    version="0.1.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def collect_http_metrics(request: Request, call_next):
    start = perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")

        if path != "/metrics":
            HTTP_REQUESTS.labels(
                method=request.method,
                path=path,
                status=str(status_code),
            ).inc()

            HTTP_REQUEST_DURATION.labels(
                method=request.method,
                path=path,
            ).observe(perf_counter() - start)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/offers", response_model=OfferResponse, status_code=201)
async def create_offer(
    body: CreateOfferRequest,
    request: Request,
) -> OfferResponse:
    service: OfferService = request.app.state.offer_service
    try:
        return await service.create(body.station_id, body.user_id)
    except OfferUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=503, detail="Offer dependencies unavailable") from exc


@app.get(
    "/rentals/{rental_id}",
    response_model=RentalResponse,
)
async def get_rental(
    rental_id: UUID,
    request: Request,
) -> RentalResponse:
    service: RentalReadService = request.app.state.rental_read_service

    try:
        return await service.get(rental_id)
    except RentalNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Rental not found",
        )
    except RentalReadUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Rental storage is busy") from exc

@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
