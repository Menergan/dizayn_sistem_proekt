from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import RentalStatus


class StartRentalRequest(BaseModel):
    offer_id: UUID


class RentalResponse(BaseModel):
    rental_id: UUID
    user_id: str
    powerbank_id: str | None
    status: RentalStatus
    start_station_id: str
    finish_station_id: str | None
    country: str
    currency: str
    started_at: datetime
    finished_at: datetime | None
    deposit: Decimal
    accumulated_amount: Decimal
    total_amount: Decimal | None
