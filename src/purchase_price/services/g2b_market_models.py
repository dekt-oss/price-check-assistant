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
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class ResearchAttachment:
    name: str | None
    url: str


@dataclass(frozen=True)
class G2BResearchRecord:
    """Research-only G2B observation with loss-minimizing procurement provenance.

    This type intentionally does not inherit from or convert itself to CollectedPrice. Broad bid,
    award, pre-specification and contract discovery can contain related products, totals or
    estimates; those records must pass a separate identity/amount evidence gate before pricing code
    can see them. Raw identity/specification fields are preserved for later fingerprinting without
    changing that promotion rule.
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
    product_id: str | None = None
    detail_product_code: str | None = None
    item_sequence: str | None = None
    original_specification: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    amount: Decimal | None = None
    amount_type: ResearchAmountType = ResearchAmountType.UNKNOWN
    original_amount_text: str | None = None
    supplier: str | None = None
    delivery_condition: str | None = None
    record_change_order: str | None = None
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
    coverage_start: date | None = None
    coverage_end: date | None = None
    requested_lookback_days: int = 0
    search_strategy: str = ""


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
