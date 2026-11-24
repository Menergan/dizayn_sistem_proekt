import asyncio
import os
from datetime import UTC, datetime

from app.persistence import SqlAlchemyOfferRepository, SqlAlchemyRentalRepository, create_session_factory
from app.workers.cleanup import PersistenceCleanupWorker


async def run() -> None:
    database_url = os.environ["DATABASE_URL"]
    interval_seconds = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))
    batch_size = int(os.getenv("CLEANUP_BATCH_SIZE", "1000"))
    session_factory = create_session_factory(database_url)
    worker = PersistenceCleanupWorker(
        SqlAlchemyOfferRepository(session_factory),
        SqlAlchemyRentalRepository(session_factory),
        batch_size=batch_size,
    )
    while True:
        await worker.run_once(datetime.now(UTC))
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    asyncio.run(run())
