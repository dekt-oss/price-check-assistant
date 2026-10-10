from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.ui import quote_review_summary as summary
from purchase_price.ui.quote_review_state import QuoteReviewState


def _item(**overrides):
    values = {
        "product_name": "FLOW-C",
        "model_name": "FLOW-C",
        "manufacturer": "Getinge",
        "specification": "",
        "quantity": Decimal("1"),
        "unit": "SET",
        "unit_price": Decimal("66000000"),
        "total_amount": Decimal("66000000"),
        "vat_status": "",
        "delivery_condition": "",
        "installation_condition": "",
        "option_condition": "",
        "warranty_condition": "",
        "maintenance_condition": "",
        "other_conditions": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_summary_reports_observed_range_and_median_without_fair_price_verdict() -> None:
    state = QuoteReviewState()
    state.items = [_item()]
    state.item_confirmed = {0: True}
    state.track_b_db[0] = SimpleNamespace(
        status="success",
        candidates=(
            SimpleNamespace(price=Decimal("10000000"), match_grade=MatchGrade.A),
            SimpleNamespace(price=Decimal("14000000"), match_grade=MatchGrade.B),
            SimpleNamespace(price=Decimal("12000000"), match_grade=MatchGrade.A),
            SimpleNamespace(price=Decimal("99000000"), match_grade=MatchGrade.C),
        ),
        reference_candidates=(SimpleNamespace(price=Decimal("9000000")),),
    )

    rows = summary.build_purchase_review_summary_rows(state)

    assert len(rows) == 1
    row = rows[0]
    assert row.strict_count == 3
    assert row.reference_count == 2
    assert row.observed_low == Decimal("10000000")
    assert row.observed_median == Decimal("12000000")
    assert row.observed_high == Decimal("14000000")
    assert row.review_status == "검증 전 · 거래 조건을 맞춰 보지 않음"
    assert row.market_status == "같은 모델 거래 있음"


def test_summary_surfaces_r2_unavailable_separately_from_review_progress() -> None:
    state = QuoteReviewState()
    state.items = [_item()]
    state.item_confirmed = {0: False}
    state.track_b_db[0] = SimpleNamespace(
        status="unavailable",
        candidates=(),
        reference_candidates=(),
    )

    row = summary.build_purchase_review_summary_rows(state)[0]

    assert row.review_status == "검증 전 · 견적서 원문과 맞춰 보지 않음"
    assert row.market_status == "나라장터 가격 자료를 지금은 쓸 수 없음"
    assert row.observed_median is None


def test_summary_counts_only_current_item_pair_approvals(monkeypatch) -> None:
    state = QuoteReviewState()
    state.items = [_item()]
    state.item_confirmed = {0: True}
    state.track_b_db[0] = SimpleNamespace(
        status="success",
        candidates=(SimpleNamespace(price=Decimal("12000000"), match_grade=MatchGrade.A),),
        reference_candidates=(),
    )
    state.comparability_context[0] = object()
    state.search_runs[0] = SimpleNamespace(
        results=(SimpleNamespace(pair_key="pair-a"), SimpleNamespace(pair_key="pair-b"))
    )
    state.approvals["pair-b"] = object()
    monkeypatch.setattr(
        summary,
        "quote_evidence_pair_key",
        lambda _context, evidence: evidence.pair_key,
    )
    monkeypatch.setattr(
        summary,
        "assess_prices",
        lambda _items, _quote: SimpleNamespace(observed_count=2),
    )

    row = summary.build_purchase_review_summary_rows(state)[0]

    assert row.approved_count == 1
    assert row.public_direct_count == 2
    assert row.review_status == "검증 완료"


def test_summary_cards_keep_every_column_of_the_old_table_and_wrap() -> None:
    from pathlib import Path

    state = QuoteReviewState()
    state.items = [_item(product_name="<b>FLOW-C</b>")]
    state.item_confirmed = {0: True}
    state.track_b_db[0] = SimpleNamespace(
        status="success",
        candidates=(
            SimpleNamespace(price=Decimal("10000000"), match_grade=MatchGrade.A),
            SimpleNamespace(price=Decimal("14000000"), match_grade=MatchGrade.B),
        ),
        reference_candidates=(),
    )
    rows = summary.build_purchase_review_summary_rows(state)

    html = summary.purchase_summary_html(rows)

    assert summary.QUOTE_REVIEW_SUMMARY_CARDS_V1 is True
    for label in (
        "견적 단가", "같은 모델 거래", "단위가 다른 거래", "이름이 비슷한 거래", "그 밖의 공개 가격 자료",
        "거래 가격대", "거래 가운데 값", "승인한 거래", "상세 검증", "거래 자료 상태",
    ):
        assert f"<dt>{label}</dt>" in html, label
    for value in ("66,000,000원", "2건", "10,000,000 ~ 14,000,000원", "같은 모델 거래 있음", "아직 찾지 않음"):
        assert value in html, value
    assert "&lt;b&gt;FLOW-C" in html and "<b>FLOW-C" not in html
    assert "<table" not in html and "nowrap" not in html and "max-width: 1200px" in html

    page = Path("pages/2_견적_검토.py").read_text(encoding="utf-8")
    assert '("purchase_price.ui.quote_review_summary", "QUOTE_REVIEW_SUMMARY_CARDS_V1")' in page
    assert '("purchase_price.ui.quote_market_research", "QUOTE_REVIEW_SUMMARY_CARDS_V1")' in page
    assert "st.dataframe" not in Path("src/purchase_price/ui/quote_review_summary.py").read_text(encoding="utf-8")
