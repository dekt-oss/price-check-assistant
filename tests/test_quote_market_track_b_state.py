from decimal import Decimal

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.track_b_db_quote_comparison import TrackBQuoteComparison
from purchase_price.ui import quote_market_research
from purchase_price.ui.quote_review_state import QuoteReviewState


def test_auto_quote_flow_loads_db_comparison_and_invalidates_it(monkeypatch) -> None:
    state = QuoteReviewState(items=[QuoteItem(
        source_sheet="sheet", source_row=1, product_name="제습기",
        model_name="MA-045DT", unit_price=Decimal("100")
    )])
    state.search_runs[0] = object()  # Existing live search suppresses network calls in this test.
    calls = []
    expected = TrackBQuoteComparison("success_0", (), 0)

    def lookup(query, *, quote_unit_price):
        calls.append((query.model_name, quote_unit_price))
        return expected

    monkeypatch.setattr(quote_market_research, "lookup_track_b_quote", lookup)
    quote_market_research._ensure_market_research(state)
    assert calls == [("MA-045DT", Decimal("100"))]
    assert state.track_b_db[0] is expected

    quote_market_research._clear_research(state)
    assert state.track_b_db == {}
