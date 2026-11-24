from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OfferModel(Base):
    __tablename__ = "offers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    station_id: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_per_hour: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    free_period_min: Mapped[int] = mapped_column(Integer, nullable=False)
    deposit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class RentalModel(Base):
    __tablename__ = "rentals"
    __table_args__ = (
        Index("ix_rentals_active_powerbank", "powerbank_id", "status"),
        Index("ix_rentals_user_id", "user_id"),
        Index("ix_rentals_delete_after", "delete_after"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    start_station_id: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_per_hour: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    free_period_min: Mapped[int] = mapped_column(Integer, nullable=False)
    deposit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    powerbank_id: Mapped[str | None] = mapped_column(String(128))
    finish_station_id: Mapped[str | None] = mapped_column(String(128))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentOperationModel(Base):
    __tablename__ = "payment_operations"
    __table_args__ = (
        UniqueConstraint("rental_id", "operation_type", name="uq_payment_operations_rental_operation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rental_id: Mapped[UUID] = mapped_column(ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    external_operation_id: Mapped[str | None] = mapped_column(String(160))
    external_response: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StationEventModel(Base):
    __tablename__ = "station_events"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    station_id: Mapped[str] = mapped_column(String(128), nullable=False)
    powerbank_id: Mapped[str] = mapped_column(String(128), nullable=False)
    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rental_id: Mapped[UUID | None] = mapped_column(ForeignKey("rentals.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
