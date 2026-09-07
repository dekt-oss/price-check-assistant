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
        """Whether a same-model research price range exists.

        Manufacturer/category/spec-similar candidates remain useful individual research evidence,
        but they must not silently become the quote comparison band.
        """

        return self.model_candidate_count > 0 and self.median is not None


def should_run_broad_research(query: ProductQuery, *, g2b_enabled: bool) -> bool:
    """Broad market research is allowed from a product keyword alone."""

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
    """Summarize broad candidates while aggregating only same-model-labelled prices."""

    if discovery is None:
        return MarketReferenceSummary(0, 0, 0, 0, None, None, None)

    candidates = tuple(discovery.candidates)
    model_candidates = tuple(
        candidate for candidate in candidates if candidate.relevance == "모델 표기 후보"
    )
    model_prices = [candidate.price for candidate in model_candidates if candidate.price > 0]
    model_count = len(model_candidates)
    manufacturer_count = sum(candidate.relevance == "제조사 표기 후보" for candidate in candidates)
    classification_count = len(candidates) - model_count - manufacturer_count

    return MarketReferenceSummary(
        candidate_count=len(candidates),
        model_candidate_count=model_count,
        manufacturer_candidate_count=manufacturer_count,
        classification_candidate_count=classification_count,
        low=min(model_prices) if model_prices else None,
        median=_median(model_prices),
        high=max(model_prices) if model_prices else None,
    )


def quote_delta_from_market_median(
    quote_unit_price: Decimal | None,
    summary: MarketReferenceSummary,
) -> Decimal | None:
    """Return a descriptive same-model percentage delta, never an approval/verdict."""

    if quote_unit_price is None or not summary.has_prices or summary.median is None or summary.median <= 0:
        return None
    return ((quote_unit_price - summary.median) / summary.median) * Decimal("100")
