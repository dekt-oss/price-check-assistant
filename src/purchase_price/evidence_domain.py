from enum import StrEnum


class IdentityEvidenceStatus(StrEnum):
    """V3 semantic state for regulatory identity lookup."""

    FOUND = "FOUND"
    NOT_FOUND_IN_COVERAGE = "NOT_FOUND_IN_COVERAGE"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class PriceEvidenceStatus(StrEnum):
    """V3 semantic state for direct procurement-price evidence."""

    FOUND = "FOUND"
    ZERO = "ZERO"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    PARTIAL = "PARTIAL"


class SafetyEvidenceStatus(StrEnum):
    """V3 semantic state for official safety-information checks."""

    NOT_CONNECTED = "NOT_CONNECTED"
    CHECK_FAILED = "CHECK_FAILED"
    CHECKED_NONE = "CHECKED_NONE"
    AMBER = "AMBER"
    RED = "RED"


class MfdsItemAuthorizationType(StrEnum):
    """User-facing MFDS item-number type."""

    PERMIT = "허가"
    CERTIFICATION = "인증"
    NOTIFICATION = "신고"
    UNKNOWN = "미확인"


class UnitPriceBasis(StrEnum):
    """Whether a displayed unit price came from the source or arithmetic."""

    SOURCE_UNIT_PRICE = "source_unit_price"
    CALCULATED_UNIT_PRICE = "calculated_unit_price"
    UNKNOWN = "unknown"
