from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.ui.quote_review_state import QuoteReviewState


def test_default_g2b_lookback_is_three_years() -> None:
    assert G2B_DEFAULT_LOOKBACK_DAYS == 1095
    assert G2B_DEFAULT_LOOKBACK_DAYS in G2B_LOOKBACK_OPTIONS
    assert g2b_lookback_label(G2B_DEFAULT_LOOKBACK_DAYS) == "최근 3년 (기본)"


def test_quote_review_uses_shared_three_year_default() -> None:
    assert QuoteReviewState().lookback_days == G2B_DEFAULT_LOOKBACK_DAYS


def test_one_year_remains_available_but_is_not_default() -> None:
    assert 365 in G2B_LOOKBACK_OPTIONS
    assert g2b_lookback_label(365) == "최근 1년"
