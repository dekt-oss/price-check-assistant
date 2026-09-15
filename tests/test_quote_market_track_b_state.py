from decimal import Decimal

from purchase_price.domain import MatchGrade
from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
)
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


def test_track_b_table_exposes_amount_mismatch() -> None:
    candidate = TrackBQuoteCandidate(
        source_record_id="delivery:1|change:00|line:1",
        product_title="제습기, 제조사, MODEL",
        price=Decimal("90"),
        match_grade=MatchGrade.A,
        match_note="exact",
        delta_percent=Decimal("11.1"),
        raw_object_key="raw/key",
        amount_check="inconsistent",
        transaction_date="2026-09-01",
    )
    rows = quote_market_research._track_b_candidate_rows((candidate,))
    assert rows[0]["금액검산"] == "불일치"
