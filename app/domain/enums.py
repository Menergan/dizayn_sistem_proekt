from enum import StrEnum


class OfferStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    USED = "USED"
    EXPIRED = "EXPIRED"


class RentalStatus(StrEnum):
    CREATING = "CREATING"
    ACTIVE = "ACTIVE"
    RETURNING = "RETURNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaymentOperationType(StrEnum):
    RESERVE = "RESERVE"
    CAPTURE = "CAPTURE"
    RELEASE = "RELEASE"
