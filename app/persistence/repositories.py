from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities import Offer, PaymentOperation, Rental, StationEvent
from app.domain.enums import OfferStatus, PaymentOperationStatus, RentalStatus
from app.persistence.models import OfferModel, PaymentOperationModel, RentalModel, StationEventModel


def _offer_from_model(model: OfferModel) -> Offer:
    return Offer(
        id=model.id,
        user_id=model.user_id,
        station_id=model.station_id,
        country=model.country,
        currency=model.currency,
        price_per_hour=model.price_per_hour,
        free_period_min=model.free_period_min,
        deposit=model.deposit,
        created_at=model.created_at,
        expires_at=model.expires_at,
        status=OfferStatus(model.status),
    )


def _rental_from_model(model: RentalModel) -> Rental:
    return Rental(
        id=model.id,
        user_id=model.user_id,
        start_station_id=model.start_station_id,
        country=model.country,
        currency=model.currency,
        price_per_hour=model.price_per_hour,
        free_period_min=model.free_period_min,
        deposit=model.deposit,
        started_at=model.started_at,
        status=RentalStatus(model.status),
        powerbank_id=model.powerbank_id,
        finish_station_id=model.finish_station_id,
        finished_at=model.finished_at,
        total_amount=model.total_amount,
        delete_after=model.delete_after,
    )


class SqlAlchemyOfferRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, offer: Offer) -> None:
        async with self._session_factory.begin() as session:
            await session.merge(
                OfferModel(
                    id=offer.id,
                    user_id=offer.user_id,
                    station_id=offer.station_id,
                    country=offer.country,
                    currency=offer.currency,
                    price_per_hour=offer.price_per_hour,
                    free_period_min=offer.free_period_min,
                    deposit=offer.deposit,
                    created_at=offer.created_at,
                    expires_at=offer.expires_at,
                    status=offer.status.value,
                )
            )

    async def claim_available(self, offer_id: UUID, now: datetime) -> Offer | None:
        statement = (
            update(OfferModel)
            .where(
                OfferModel.id == offer_id,
                OfferModel.status == OfferStatus.AVAILABLE.value,
                OfferModel.expires_at > now,
            )
            .values(status=OfferStatus.USED.value)
            .returning(OfferModel)
        )
        async with self._session_factory.begin() as session:
            model = (await session.execute(statement)).scalar_one_or_none()
        return _offer_from_model(model) if model is not None else None

    async def delete_expired(self, before: datetime, limit: int) -> int:
        candidate_ids = (
            select(OfferModel.id)
            .where(
                OfferModel.expires_at <= before,
                OfferModel.status == OfferStatus.AVAILABLE.value,
            )
            .limit(limit)
        )
        statement = delete(OfferModel).where(OfferModel.id.in_(candidate_ids))
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
        return result.rowcount or 0


class SqlAlchemyRentalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, rental: Rental) -> None:
        async with self._session_factory.begin() as session:
            await session.merge(
                RentalModel(
                    id=rental.id,
                    user_id=rental.user_id,
                    start_station_id=rental.start_station_id,
                    country=rental.country,
                    currency=rental.currency,
                    price_per_hour=rental.price_per_hour,
                    free_period_min=rental.free_period_min,
                    deposit=rental.deposit,
                    started_at=rental.started_at,
                    status=rental.status.value,
                    powerbank_id=rental.powerbank_id,
                    finish_station_id=rental.finish_station_id,
                    finished_at=rental.finished_at,
                    total_amount=rental.total_amount,
                    delete_after=rental.delete_after,
                )
            )

    async def get(self, rental_id: UUID) -> Rental | None:
        async with self._session_factory() as session:
            model = await session.get(RentalModel, rental_id)
        return _rental_from_model(model) if model is not None else None

    async def find_active_by_powerbank(self, powerbank_id: str) -> Rental | None:
        statement = select(RentalModel).where(
            RentalModel.powerbank_id == powerbank_id,
            RentalModel.status == RentalStatus.ACTIVE.value,
        )
        async with self._session_factory() as session:
            model = (await session.execute(statement)).scalar_one_or_none()
        return _rental_from_model(model) if model is not None else None

    async def change_status(self, rental_id: UUID, status: RentalStatus) -> Rental:
        statement = (
            update(RentalModel)
            .where(RentalModel.id == rental_id)
            .values(status=status.value)
            .returning(RentalModel)
        )
        async with self._session_factory.begin() as session:
            model = (await session.execute(statement)).scalar_one()
        return _rental_from_model(model)

    async def delete_expired(self, before: datetime, limit: int) -> int:
        candidate_ids = (
            select(RentalModel.id)
            .where(RentalModel.delete_after.is_not(None), RentalModel.delete_after <= before)
            .limit(limit)
        )
        statement = delete(RentalModel).where(RentalModel.id.in_(candidate_ids))
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
        return result.rowcount or 0


class SqlAlchemyPaymentOperationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_or_create_key(
        self, rental_id: UUID, operation_type: str, amount: Decimal
    ) -> str:
        key = f"rental:{rental_id}:{operation_type.lower()}"
        statement = (
            insert(PaymentOperationModel)
            .values(
                rental_id=rental_id,
                operation_type=operation_type,
                idempotency_key=key,
                amount=amount,
                status=PaymentOperationStatus.PENDING.value,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_payment_operations_rental_operation")
            .returning(PaymentOperationModel.idempotency_key)
        )
        async with self._session_factory.begin() as session:
            saved_key = (await session.execute(statement)).scalar_one_or_none()
            if saved_key is not None:
                return saved_key
            existing = await session.scalar(
                select(PaymentOperationModel).where(
                    PaymentOperationModel.rental_id == rental_id,
                    PaymentOperationModel.operation_type == operation_type,
                )
            )
        if existing is None:
            raise RuntimeError("Payment operation was not saved")
        if existing.amount != amount:
            raise ValueError("Payment operation amount differs from the saved amount")
        return existing.idempotency_key

    async def save_result(
        self,
        rental_id: UUID,
        operation_type: str,
        status: str,
        external_operation_id: str | None,
        external_response: dict[str, object] | None,
    ) -> None:
        statement = (
            update(PaymentOperationModel)
            .where(
                PaymentOperationModel.rental_id == rental_id,
                PaymentOperationModel.operation_type == operation_type,
            )
            .values(
                status=status,
                external_operation_id=external_operation_id,
                external_response=external_response,
            )
        )
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
        if result.rowcount != 1:
            raise LookupError("Payment operation was not found")

    async def get(
        self, rental_id: UUID, operation_type: str
    ) -> PaymentOperation | None:
        statement = select(PaymentOperationModel).where(
            PaymentOperationModel.rental_id == rental_id,
            PaymentOperationModel.operation_type == operation_type,
        )
        async with self._session_factory() as session:
            model = (await session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return PaymentOperation(
            rental_id=model.rental_id,
            operation_type=model.operation_type,
            idempotency_key=model.idempotency_key,
            amount=model.amount,
            status=model.status,
            external_operation_id=model.external_operation_id,
            external_response=model.external_response,
        )


class SqlAlchemyStationEventRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_if_new(self, event: StationEvent) -> bool:
        statement = (
            insert(StationEventModel)
            .values(
                id=event.id,
                station_id=event.station_id,
                powerbank_id=event.powerbank_id,
                returned_at=event.returned_at,
                rental_id=event.rental_id,
                received_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[StationEventModel.id])
            .returning(StationEventModel.id)
        )
        async with self._session_factory.begin() as session:
            return (await session.execute(statement)).scalar_one_or_none() is not None
