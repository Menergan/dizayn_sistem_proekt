import asyncio
import logging
import os
from decimal import Decimal
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.domain.entities import AppConfig, EjectResponse, PaymentResult, StationData, TariffData, UserProfile
from app.integrations.dto import ConfigDTO, EjectDTO, PaymentDTO, StationDTO, TariffDTO, UserDTO


logger = logging.getLogger(__name__)


class ExternalServiceError(Exception):
    pass

    def __init__(self, service: str, message: str, status_code: int | None = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status_code = status_code


class ExternalServiceUnavailable(ExternalServiceError):
    pass


class ExternalOperationUnknown(ExternalServiceUnavailable):
    pass


def timeout_from_env(service: str) -> httpx.Timeout:
    prefix = service.upper()
    connect = float(os.getenv(f"{prefix}_CONNECT_TIMEOUT_SECONDS", "0.2"))
    read = float(os.getenv(f"{prefix}_READ_TIMEOUT_SECONDS", "0.5"))
    if connect <= 0 or read <= 0:
        raise ValueError(f"{prefix} timeouts must be positive")
    return httpx.Timeout(connect=connect, read=read, write=read, pool=connect)


class _HTTPAdapter:
    def __init__(self, client: httpx.AsyncClient, base_url: str, service: str, retries: int = 1):
        if retries < 0:
            raise ValueError("retries must be non-negative")
        self.client, self.base_url, self.service, self.retries = client, base_url.rstrip("/"), service, retries
        self.timeout = timeout_from_env(service)

    async def request(self, method: str, path: str, model, *, command: bool = False, **kwargs):
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
                if response.status_code >= 500 or response.status_code == 429:
                    raise ExternalServiceUnavailable(self.service, "upstream unavailable", response.status_code)
                if response.is_error:
                    logger.warning("integration_error", extra={"event": "integration_error", "service": self.service, "method": method, "status_code": response.status_code})
                    raise ExternalServiceError(self.service, "upstream rejected request", response.status_code)
                return model.model_validate(response.json())
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, ExternalServiceUnavailable) as exc:
                if attempt == self.retries:
                    logger.warning("integration_error", extra={"event": "integration_error", "service": self.service, "method": method, "error_type": type(exc).__name__})
                    if command:
                        status_code = exc.status_code if isinstance(exc, ExternalServiceUnavailable) else None
                        raise ExternalOperationUnknown(self.service, "command result unknown", status_code) from exc
                    if isinstance(exc, ExternalServiceUnavailable):
                        raise
                    raise ExternalServiceUnavailable(self.service, "network error or timeout") from exc
                await asyncio.sleep(0.05 * (attempt + 1))
            except (ValueError, ValidationError) as exc:
                logger.warning("integration_error", extra={"event": "integration_error", "service": self.service, "method": method, "error_type": "invalid_response"})
                if command:
                    raise ExternalOperationUnknown(self.service, "invalid command response; outcome unknown") from exc
                raise ExternalServiceError(self.service, "invalid upstream response") from exc


class HTTPStationClient(_HTTPAdapter):
    def __init__(self, client: httpx.AsyncClient, base_url: str, retries: int = 1):
        super().__init__(client, base_url, "stations", retries)

    async def get_station(self, station_id: str) -> StationData:
        from urllib.parse import quote
        result = await self.request("GET", f"/stations/{quote(station_id, safe='')}", StationDTO)
        if result.id != station_id:
            raise ExternalServiceError("stations", "station ID does not match request")
        return StationData(**result.model_dump())

    async def eject(self, station_id: str, operation_id: str) -> EjectResponse:
        from urllib.parse import quote
        if not operation_id:
            raise ValueError("station operation ID is required")
        result = await self.request("POST", f"/stations/{quote(station_id, safe='')}/eject", EjectDTO, command=True, json={"operation_id": operation_id})
        return EjectResponse(**result.model_dump())


class HTTPPaymentClient(_HTTPAdapter):
    def __init__(self, client: httpx.AsyncClient, base_url: str, retries: int = 1):
        super().__init__(client, base_url, "payments", retries)

    async def _operation(self, operation: str, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str) -> PaymentResult:
        if not idempotency_key:
            raise ValueError("payment idempotency key is required")
        result = await self.request("POST", f"/payments/{operation}", PaymentDTO, command=True, json={"user_id": user_id, "rental_id": str(rental_id), "amount": str(amount), "idempotency_key": idempotency_key})
        return PaymentResult(**result.model_dump())

    async def reserve(self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str) -> PaymentResult:
        return await self._operation("reserve", user_id, rental_id, amount, idempotency_key)

    async def capture(self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str) -> PaymentResult:
        return await self._operation("capture", user_id, rental_id, amount, idempotency_key)

    async def release(self, user_id: str, rental_id: UUID, amount: Decimal, idempotency_key: str) -> PaymentResult:
        return await self._operation("release", user_id, rental_id, amount, idempotency_key)


class HTTPUserClient(_HTTPAdapter):
    def __init__(self, client: httpx.AsyncClient, base_url: str, retries: int = 1):
        super().__init__(client, base_url, "users", retries)

    async def get_user(self, user_id: str) -> UserProfile:
        from urllib.parse import quote
        result = await self.request("GET", f"/users/{quote(user_id, safe='')}", UserDTO)
        if result.id != user_id:
            raise ExternalServiceError("users", "user ID does not match request")
        return UserProfile(**result.model_dump())


class HTTPTariffClient(_HTTPAdapter):
    def __init__(self, client: httpx.AsyncClient, base_url: str, retries: int = 1):
        super().__init__(client, base_url, "tariffs", retries)

    async def get_tariff(self, tariff_id: str) -> TariffData:
        from urllib.parse import quote
        result = await self.request("GET", f"/tariffs/{quote(tariff_id, safe='')}", TariffDTO)
        if result.id != tariff_id:
            raise ExternalServiceError("tariffs", "tariff ID does not match request")
        return TariffData(**result.model_dump())


class HTTPConfigClient(_HTTPAdapter):
    def __init__(self, client: httpx.AsyncClient, base_url: str, retries: int = 1):
        super().__init__(client, base_url, "configs", retries)

    async def get_config(self) -> AppConfig:
        result = await self.request("GET", "/configs", ConfigDTO)
        return AppConfig(**result.model_dump())
