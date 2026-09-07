from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class G2BResearchSource(StrEnum):
    BID_NOTICE = "bid_notice"
    BID_ITEM = "bid_item"
    AWARD = "award"
    PRESPEC = "prespec"
    CONTRACT = "contract"
    LIFECYCLE = "lifecycle"
    SHOPPING = "shopping"


class ResearchAmountType(StrEnum):
    """Meaning of a monetary value observed during broad research.

    Only UNIT_PRICE is inherently a per-item price. All totals, budget values and estimates remain
    research context until a separate evidence-promotion step verifies quantity and comparability.
    """

    UNIT_PRICE = "unit_price"
    ESTIMATED_UNIT_PRICE = "estimated_unit_price"
    ESTIMATED_PRICE = "estimated_price"
    BASIC_AMOUNT = "basic_amount"
    BUDGET_AMOUNT = "budget_amount"
    AWARD_TOTAL = "award_total"
    CONTRACT_TOTAL = "contract_total"
    UNKNOWN = "unknown"


class ResearchSourceStatus(StrEnum):
    SUCCESS = "success"
    SUCCESS_0 = "success_0"
    PARTIAL = "partial"
    FAILURE = "failure"
    NOT_CONFIGURED = "not_configured"
    NOT_AUTHORIZED = "not_authorized"


@dataclass(frozen=True)
class ResearchAttachment:
    name: str | None
    url: str


@dataclass(frozen=True)
class G2BResearchRecord:
    """Research-only G2B observation.

    This type intentionally does not inherit from or convert itself to CollectedPrice. Broad bid,
    award and pre-specification discovery can contain related products, totals or estimates; those
    records must pass a separate identity/amount evidence gate before pricing code can see them.
    """

    source_type: G2BResearchSource
    source_record_id: str
    title: str | None = None
    institution: str | None = None
    published_date: date | None = None
    bid_notice_no: str | None = None
    bid_notice_order: str | None = None
    prespec_no: str | None = None
    contract_no: str | None = None
    product_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    amount: Decimal | None = None
    amount_type: ResearchAmountType = ResearchAmountType.UNKNOWN
    supplier: str | None = None
    source_url: str | None = None
    attachments: tuple[ResearchAttachment, ...] = ()
    search_term: str | None = None

    @property
    def is_direct_unit_price(self) -> bool:
        return self.amount is not None and self.amount_type == ResearchAmountType.UNIT_PRICE


@dataclass(frozen=True)
class ResearchSourceResult:
    source: G2BResearchSource
    status: ResearchSourceStatus
    records: tuple[G2BResearchRecord, ...] = ()
    request_count: int = 0
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class MarketResearchBundle:
    query_terms: tuple[str, ...]
    sources: tuple[ResearchSourceResult, ...]
    records: tuple[G2BResearchRecord, ...] = field(default_factory=tuple)

    @property
    def failures(self) -> tuple[ResearchSourceResult, ...]:
        return tuple(
            source
            for source in self.sources
            if source.status in {ResearchSourceStatus.FAILURE, ResearchSourceStatus.NOT_AUTHORIZED}
        )
