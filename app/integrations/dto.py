from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class StationDTO(BaseModel):
    id: str
    tariff_id: str
    country: str
    available_powerbanks: int = Field(ge=0)


class TariffDTO(BaseModel):
    id: str
    currency: str
    price_per_hour: Decimal = Field(ge=0)
    free_period_min: int = Field(ge=0)
    default_deposit: Decimal = Field(ge=0)


class UserDTO(BaseModel):
    id: str
    has_subscription: bool
    trusted: bool


class ConfigDTO(BaseModel):
    last_banks_increase: Decimal = Field(gt=0)
    tariffs_ttl_seconds: int = Field(ge=1, le=600)
    retention_days_by_country: dict[str, int] = Field(default_factory=dict)

    @field_validator("retention_days_by_country")
    @classmethod
    def validate_retention(cls, value: dict[str, int]) -> dict[str, int]:
        if any(days <= 0 for days in value.values()):
            raise ValueError("retention days must be positive")
        return value


class EjectDTO(BaseModel):
    powerbank_id: str | None
    successful: bool


class PaymentDTO(BaseModel):
    operation_id: str
    successful: bool
