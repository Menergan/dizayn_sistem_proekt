
import os
import random
from pathlib import Path

from locust import HttpUser, task, constant_throughput


IDS_FILE = Path(__file__).parent / "rental_ids.txt"
TASKS_PER_SECOND = float(os.getenv("LOCUST_TASKS_PER_SECOND", "10"))

with IDS_FILE.open(encoding="utf-8") as file:
    RENTAL_IDS = [line.strip() for line in file if line.strip()]

if not RENTAL_IDS:
    raise RuntimeError("No rental IDs found")


class RentalUser(HttpUser):
    wait_time = constant_throughput(TASKS_PER_SECOND)

    @task
    def read_rental(self):
        rental_id = random.choice(RENTAL_IDS)

        with self.client.get(
            f"/rentals/{rental_id}",
            name="/rentals/{rental_id}",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(
                    f"Unexpected status: {response.status_code}"
                )
