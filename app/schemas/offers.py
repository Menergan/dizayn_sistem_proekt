from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class CreateOfferRequest(BaseModel):
    station_id: str
    user_id: str


class OfferResponse(BaseModel):
    offer_id: UUID
    station_id: str
    user_id: str
    country: str
    currency: str
    price_per_hour: Decimal
    free_period_min: int
    deposit: Decimal
    expires_at: datetime
