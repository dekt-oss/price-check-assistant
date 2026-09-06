from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import G2BUnmappedDiscoveryResult


@dataclass(frozen=True)
class MarketReferenceSummary:
    candidate_count: int
    model_candidate_count: int
    manufacturer_candidate_count: int
    classification_candidate_count: int
    low: Decimal | None
    median: Decimal | None
    high: Decimal | None

    @property
    def has_prices(self) -> bool:
        return self.candidate_count > 0 and self.median is not None


def should_run_broad_research(query: ProductQuery, *, g2b_enabled: bool) -> bool:
    """Broad market research is allowed from a product keyword alone.

    This deliberately does not require a verified mapping, model, manufacturer, specification,
    or quote-condition confirmation. Those fields improve ranking/precision but must not block
    market discovery.
    """

    return bool(g2b_enabled and query.product_name.strip())


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def summarize_g2b_research(discovery: G2BUnmappedDiscoveryResult | None) -> MarketReferenceSummary:
    if discovery is None:
        return MarketReferenceSummary(0, 0, 0, 0, None, None, None)

    candidates = tuple(discovery.candidates)
    prices = [candidate.price for candidate in candidates if candidate.price > 0]
    model_count = sum(candidate.relevance == "모델 표기 후보" for candidate in candidates)
    manufacturer_count = sum(candidate.relevance == "제조사 표기 후보" for candidate in candidates)
    classification_count = len(candidates) - model_count - manufacturer_count

    return MarketReferenceSummary(
        candidate_count=len(candidates),
        model_candidate_count=model_count,
        manufacturer_candidate_count=manufacturer_count,
        classification_candidate_count=classification_count,
        low=min(prices) if prices else None,
        median=_median(prices),
        high=max(prices) if prices else None,
    )


def quote_delta_from_market_median(
    quote_unit_price: Decimal | None,
    summary: MarketReferenceSummary,
) -> Decimal | None:
    """Return a descriptive percentage delta, never an approval/verdict.

    The research median may contain related-category candidates, so this value is display-only and
    must not be used as a QuoteComparableApproval or pricing gate.
    """

    if quote_unit_price is None or summary.median is None or summary.median <= 0:
        return None
    return ((quote_unit_price - summary.median) / summary.median) * Decimal("100")
