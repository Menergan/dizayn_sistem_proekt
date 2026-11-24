import asyncio
import logging
import os
from app.lifecycle.runtime import runtime


async def main():
    interval = float(os.getenv("LIFECYCLE_INTERVAL_SECONDS", "5"))
    if interval <= 0:
        raise ValueError("Reconciliation interval must be positive")
    async with runtime() as service:
        while True:
            try:
                await service.reconcile()
            except Exception:
                logging.exception("lifecycle_scan_failed")
            await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
