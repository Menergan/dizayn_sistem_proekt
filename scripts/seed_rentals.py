
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.persistence.database import create_session_factory
from app.persistence.models import RentalModel
from app.domain.enums import RentalStatus


async def main():
    count = int(os.getenv("SEED_COUNT", "10000"))

    factory = create_session_factory(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://rental:rental@localhost:5432/rental",
        )
    )

    now = datetime.now(timezone.utc)
    rental_ids = []

    async with factory.begin() as session:
        rentals = []

        for i in range(count):
            rental_id = uuid4()
            rental_ids.append(str(rental_id))

            rentals.append(
                RentalModel(
                    id=rental_id,
                    user_id=f"load-test-user-{i}",
                    start_station_id="load-test-station",
                    country="LV",
                    currency="EUR",
                    price_per_hour=2.50,
                    free_period_min=5,
                    deposit=10.00,
                    started_at=now - timedelta(hours=2),
                    status=RentalStatus.ACTIVE.value,
                    powerbank_id=f"load-test-powerbank-{i}",
                    finish_station_id=None,
                    finished_at=None,
                    total_amount=None,
                    delete_after=None,
                )
            )

        session.add_all(rentals)

    with open("rental_ids.txt", "w", encoding="utf-8") as file:
        file.write("\n".join(rental_ids))

    print(f"Created {count} test rentals")
    await factory.kw["bind"].dispose()


if __name__ == "__main__":
    asyncio.run(main())
