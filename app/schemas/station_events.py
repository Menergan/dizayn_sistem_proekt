from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PowerbankReturnedEvent(BaseModel):
    station_id: str
    powerbank_id: str
    returned_at: datetime
    station_event_id: UUID
