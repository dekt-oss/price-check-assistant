from enum import StrEnum


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


DIRECT_PRICE_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.CONTRACT_UNIT_PRICE,
        EvidenceType.SHOPPING_CONTRACT_UNIT_PRICE,
        EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        EvidenceType.PUBLIC_SALE_PRICE,
    }
)
