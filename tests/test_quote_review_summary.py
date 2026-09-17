from decimal import Decimal
from types import SimpleNamespace

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
            SimpleNamespace(price=Decimal("10000000")),
            SimpleNamespace(price=Decimal("14000000")),
            SimpleNamespace(price=Decimal("12000000")),
        ),
        reference_candidates=(SimpleNamespace(price=Decimal("9000000")),),
    )

    rows = summary.build_purchase_review_summary_rows(state)

    assert len(rows) == 1
    row = rows[0]
    assert row.strict_count == 3
    assert row.reference_count == 1
    assert row.observed_low == Decimal("10000000")
    assert row.observed_median == Decimal("12000000")
    assert row.observed_high == Decimal("14000000")
    assert row.review_status == "조건대조·승인 전"
    assert row.market_status == "동일성 거래 확인"


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

    assert row.review_status == "품목 원문 확인 필요"
    assert row.market_status == "거래가격 DB 연결 확인"
    assert row.observed_median is None


def test_summary_counts_only_current_item_pair_approvals(monkeypatch) -> None:
    state = QuoteReviewState()
    state.items = [_item()]
    state.item_confirmed = {0: True}
    state.track_b_db[0] = SimpleNamespace(
        status="success",
        candidates=(SimpleNamespace(price=Decimal("12000000")),),
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
    assert row.review_status == "담당자 승인 근거 있음"
