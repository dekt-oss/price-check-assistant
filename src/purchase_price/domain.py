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


class MatchGrade(StrEnum):
    """How closely a source record matches the requested product."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"


class SourceType(StrEnum):
    PUBLIC_CONTRACT = "public_contract"
    PROCUREMENT = "procurement"
    MANUFACTURER = "manufacturer"
    B2B = "b2b"
    RETAIL = "retail"
    OTHER = "other"


class EvidenceType(StrEnum):
    """What the observed amount actually represents.

    MatchGrade answers "is this the same product?" while EvidenceType answers
    "what kind of monetary evidence is this?". Keeping the two axes separate
    prevents budgets or bid base amounts from entering the direct price range.
    """

    CONTRACT_UNIT_PRICE = "contract_unit_price"
    SHOPPING_CONTRACT_UNIT_PRICE = "shopping_contract_unit_price"
    DELIVERY_ORDER_UNIT_PRICE = "delivery_order_unit_price"
    PUBLIC_SALE_PRICE = "public_sale_price"
    BID_BASE_AMOUNT = "bid_base_amount"
    BUDGET_AMOUNT = "budget_amount"
    QUOTE_SAMPLE = "quote_sample"
    UNKNOWN = "unknown"


class ComparisonScope(StrEnum):
    """How an observation may be used in price analysis.

    `OBSERVED_ONLY` means the monetary evidence is real and traceable enough to show in an
    observed range, but commercial conditions are not sufficiently normalized to judge whether
    a user's quote is high or low. `QUOTE_COMPARABLE` is an explicit, fail-closed promotion that
    must only be used after the relevant VAT/unit/configuration/commercial conditions are checked.
    """

    OBSERVED_ONLY = "observed_only"
    QUOTE_COMPARABLE = "quote_comparable"
    REFERENCE_ONLY = "reference_only"
    EXCLUDE = "exclude"


DIRECT_PRICE_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.CONTRACT_UNIT_PRICE,
        EvidenceType.SHOPPING_CONTRACT_UNIT_PRICE,
        EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        EvidenceType.PUBLIC_SALE_PRICE,
    }
)
