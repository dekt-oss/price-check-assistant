from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.ui import quote_market_research as module
from purchase_price.ui.quote_review_state import QuoteReviewState


def _item(name: str, model: str) -> QuoteItem:
    return QuoteItem(
        source_sheet="Sheet1",
        source_row=2,
        product_name=name,
        manufacturer="제조사",
        model_name=model,
        specification="",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("1000"),
    )


def test_track_b_failure_on_one_item_does_not_block_later_items(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item("품목A", "FAIL"), _item("품목B", "OK")])

    def fake_lookup(query, *, quote_unit_price):
        if query.model_name == "FAIL":
            raise RuntimeError("boom")
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(),
            suggestions=(),
        )

    monkeypatch.setattr(module, "lookup_track_b_quote", fake_lookup)

    module._ensure_track_b_comparison(state)

    assert 0 not in state.track_b_db
    assert 1 in state.track_b_db
    assert state.item_research_failures[0]["나라장터 가격"] == "RuntimeError"
    assert 1 not in state.item_research_failures


def test_mfds_failure_on_one_item_does_not_erase_other_item_results(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item("품목A", "FAIL"), _item("품목B", "OK")])
    state.track_b_db = {
        0: SimpleNamespace(status="success_0", candidates=(), reference_candidates=()),
        1: SimpleNamespace(status="success_0", candidates=(), reference_candidates=()),
    }

    def fake_mfds(query, track_b):
        if query.model_name == "FAIL":
            raise ValueError("bad mfds")
        return SimpleNamespace(status="success_0")

    monkeypatch.setattr(module, "research_mfds_for_workspace", fake_mfds)

    module._ensure_mfds_workspace(state)

    assert 0 not in state.mfds_workspace
    assert 1 in state.mfds_workspace
    assert state.item_research_failures[0]["식약처"] == "ValueError"


def test_clear_research_clears_failure_state_for_explicit_full_retry() -> None:
    state = QuoteReviewState(items=[_item("품목A", "A")])
    state.item_research_failures = {0: {"나라장터 가격": "RuntimeError"}}
    state.track_b_db = {0: SimpleNamespace(status="success_0")}

    module._clear_research(state)

    assert state.item_research_failures == {}
    assert state.track_b_db == {}


def test_successful_retry_clears_only_the_recovered_stage(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item("품목A", "A")])
    state.item_research_failures = {
        0: {
            "나라장터 가격": "RuntimeError",
            "추가 공개자료": "TimeoutError",
        }
    }

    monkeypatch.setattr(
        module,
        "lookup_track_b_quote",
        lambda query, *, quote_unit_price: SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(),
            suggestions=(),
        ),
    )

    module._ensure_track_b_comparison(state)

    assert "나라장터 가격" not in state.item_research_failures[0]
    assert state.item_research_failures[0]["추가 공개자료"] == "TimeoutError"


def test_quote_market_ui_exposes_partial_failure_and_retry_contract() -> None:
    from pathlib import Path

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "다른 품목의 결과는 유지" in source
    assert "실패 품목만 다시 조사" in source
    assert "state.item_research_failures" in source
    assert "_record_item_failure" in source
    assert "_clear_item_failure" in source
