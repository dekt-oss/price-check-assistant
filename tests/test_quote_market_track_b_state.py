from decimal import Decimal

from purchase_price.domain import MatchGrade
from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBIdentitySuggestion,
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
    TrackBReferenceCandidate,
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
    quote_market_research._ensure_track_b_comparison(state)
    assert calls == [("MA-045DT", Decimal("100"))]
    assert state.track_b_db[0] is expected

    state.mfds_workspace[0] = object()
    quote_market_research._clear_research(state)
    assert state.track_b_db == {}
    assert state.mfds_workspace == {}


def test_track_b_table_exposes_purchase_transaction_context() -> None:
    candidate = TrackBQuoteCandidate(
        source_record_id="delivery:1|change:00|line:1",
        product_title="제습기, 제조사, MODEL",
        price=Decimal("90"),
        match_grade=MatchGrade.A,
        match_note="exact",
        delta_percent=Decimal("11.1"),
        raw_object_key="raw/key",
        amount_check="consistent",
        transaction_date="2026-09-01",
        supplier="공급사A",
        demand_institution="구매기관B",
        quantity=Decimal("2"),
        unit="대",
    )

    rows = quote_market_research._track_b_candidate_rows((candidate,))

    assert rows[0]["가격"] == "90원"
    assert rows[0]["판매처"] == "공급사A"
    assert rows[0]["구매처"] == "구매기관B"
    assert rows[0]["거래일"] == "2026-09-01"
    assert rows[0]["수량/단위"] == "2 대"
    assert rows[0]["거래기록"] == "나라장터 납품요구"
    assert rows[0]["비교수준"] == "동일 모델"


def test_reference_rows_expose_price_but_make_reference_scope_explicit() -> None:
    candidate = TrackBReferenceCandidate(
        source_record_id="delivery:2|change:00|line:1",
        product_title="마취기, Maquet, FLOW-C",
        price=Decimal("60000000"),
        reference_reason="품명 키워드 참고 · 마취기",
        raw_object_key="raw/key2",
        transaction_date="2026-08-01",
        supplier="공급사C",
        demand_institution="병원D",
        quantity=Decimal("1"),
        unit="SET",
        model_name="FLOW-C",
    )

    rows = quote_market_research._track_b_reference_rows((candidate,))

    assert rows[0]["가격"] == "60,000,000원"
    assert rows[0]["판매처"] == "공급사C"
    assert rows[0]["구매처"] == "병원D"
    assert rows[0]["비교수준"] == "품명 키워드 참고 · 마취기"
    assert rows[0]["견적 대비"] == "참고만"


def test_similar_identity_rows_never_expose_price() -> None:
    suggestion = TrackBIdentitySuggestion(
        product_title="제습기, 제조사, MA-045DT",
        manufacturer="제조사",
        model_name="MA-045DT",
        transaction_date="2026-09-01",
        match_reason="모델명 편집거리 1 — 식별 확인 필요",
    )

    rows = quote_market_research._track_b_suggestion_rows((suggestion,))

    assert rows[0]["모델명"] == "MA-045DT"
    assert "가격" not in rows[0]
    assert "견적 대비" not in rows[0]


def test_money_input_uses_comma_separators() -> None:
    assert quote_market_research._money_input(Decimal("66000000")) == "66,000,000"
    assert quote_market_research._money_input(None) == ""



def test_quote_flow_auto_checks_mfds_after_track_b(monkeypatch) -> None:
    state = QuoteReviewState(items=[QuoteItem(
        source_sheet="sheet",
        source_row=1,
        product_name="심장충격기",
        model_name="Efficia DFM100",
        unit_price=Decimal("12500000"),
    )])
    track_b = TrackBQuoteComparison("success_0", (), 0)
    state.track_b_db[0] = track_b
    expected = object()
    calls = []

    def research(query, comparison):
        calls.append((query.product_name, query.model_name, comparison))
        return expected

    monkeypatch.setattr(quote_market_research, "research_mfds_for_workspace", research)

    quote_market_research._ensure_mfds_workspace(state)

    assert calls == [("심장충격기", "Efficia DFM100", track_b)]
    assert state.mfds_workspace[0] is expected

    quote_market_research._ensure_mfds_workspace(state)
    assert len(calls) == 1
