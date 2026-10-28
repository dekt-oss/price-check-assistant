"""Review D-02: the conclusion card does not wait for the same-품목 models unless it shows them."""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.domain import MatchGrade
from purchase_price.services import price_metrics as price_metrics_service
from purchase_price.ui.track_b_transactions import grade_ab_candidates, strict_comparison_candidates

DASHBOARD = Path(__file__).resolve().parents[1] / "pages" / "1_대시보드.py"
FIXTURES = Path(__file__).parent / "fixtures" / "price"
SOURCE = DASHBOARD.read_text(encoding="utf-8")


def _function(name: str):
    """Load one top-level function of the page script without running the page."""

    tree = ast.parse(SOURCE)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {
        "Any": object,
        "price_metrics_service": price_metrics_service,
        "grade_ab_candidates": grade_ab_candidates,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(DASHBOARD), "exec"), namespace)
    return namespace[name]


def _track_b(name: str) -> SimpleNamespace:
    """The golden price fixture as track_b candidates (same shape as test_price_metrics.Case)."""

    rows = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["trades"]
    return SimpleNamespace(
        candidates=tuple(
            SimpleNamespace(
                source_record_id=row["record_id"],
                price=Decimal(row["unit_price"]),
                unit=row["unit"],
                quantity=Decimal(row["quantity"]),
                total_amount=Decimal(row["total_amount"]),
                transaction_date=row["trade_date"],
                demand_institution=row["institution"],
                supplier=row["supplier"],
                match_grade=MatchGrade(row["grade"]),
            )
            for row in rows
        ),
        reference_candidates=(),
    )


def _function_source(name: str) -> str:
    tree = ast.parse(SOURCE)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SOURCE, node) or ""


@pytest.mark.parametrize(
    ("name", "needed"),
    [("zero_trades", True), ("few_trades", True), ("many_single_unit", False)],
)
def test_card_waits_for_the_same_item_market_only_when_it_shows_it(name: str, needed: bool) -> None:
    needed_before_card = _function("_same_item_needed_before_card")
    track_b = _track_b(name)

    any_direct = bool(strict_comparison_candidates(track_b))
    assert needed_before_card(track_b, any_direct=any_direct, preferred_unit=None) is needed


def test_search_records_the_same_item_work_instead_of_doing_it() -> None:
    search = _function_source("_execute_search")

    assert "_build_category_market(" not in search
    assert "_build_mfds_procurement_crosslinks(\n            same_product_identity" not in search
    assert '"same_item_pending": same_item_pending' in search


def test_result_builds_the_rest_after_the_conclusion_card_once() -> None:
    render = _function_source("_render_search_result")
    card_marker = render.index('id="purchase-render-timings-v1"')
    early = render.index("_same_item_needed_before_card(")
    late = render.index("_ensure_same_item_market(state)", card_marker)

    assert early < card_marker < late
    ensure = _function_source("_ensure_same_item_market")
    assert 'state["same_item_pending"] = None' in ensure


def _cache_namespace(calls: list[str]):
    """The deferred builder from the page script with stub index and builders; the real cache module."""

    import contextlib
    from time import monotonic

    from purchase_price.ui import same_item_cache

    same_item_cache.clear()
    wanted = {"_same_item_cache_key", "_ensure_same_item_market", "_SameItemCached"}
    tree = ast.parse(SOURCE)
    nodes = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted
    ]
    state = {"file": "a" * 64}

    @contextlib.contextmanager
    def open_snapshot():
        yield SimpleNamespace(status="available", path=Path(f"{state['file']}.sqlite"), data_as_of="2026-10-27")

    def crosslinks(records, *, track_b_snapshot, current_model, stats_out):
        calls.append("crosslinks")
        return [{"모델": "HeartOn A16-DS", "나라장터 직접거래": 92}]

    def category(snapshot, **_kwargs):
        calls.append("category")
        return "MARKET"

    def build_namespace():
        namespace = {
            "Any": object,
            "monotonic": monotonic,
            "same_item_cache": same_item_cache,
            "_track_b_runtime": lambda: (SimpleNamespace(open_track_b_serving_snapshot=open_snapshot), None),
            "_build_mfds_procurement_crosslinks": crosslinks,
            "_build_category_market": category,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(DASHBOARD), "exec"), namespace)
        return namespace

    return build_namespace, state


def _search_state() -> dict:
    record = SimpleNamespace(
        permit_number="제허 15-127 호", model_name="HeartOn A16-DS", registered_company="(주)메디아나",
        product_name="저출력심장충격기", udi_di="",
    )
    return {
        "same_item_pending": {"identity_product": "저출력심장충격기", "current_model": "HeartOn A16-DS"},
        "same_product_identity": (record,),
        "search_timings_seconds": {},
    }


def test_same_item_result_survives_a_page_rerun_for_the_same_index_file() -> None:
    calls: list[str] = []
    build_namespace, index = _cache_namespace(calls)

    first = _search_state()
    build_namespace()["_ensure_same_item_market"](first)
    assert calls == ["crosslinks", "category"]
    assert first["same_item_cache"] == "miss" and first["same_item_pending"] is None
    assert set(first["search_timings_seconds"]) == {"same_item_open", "same_item_models", "category_market"}

    # Streamlit runs the page script afresh on every rerun: a new namespace must still hit.
    first["mfds_procurement_crosslinks"][0]["모델"] = "changed on screen"
    second = _search_state()
    build_namespace()["_ensure_same_item_market"](second)
    assert calls == ["crosslinks", "category"]  # nothing rebuilt
    assert second["same_item_cache"] == "hit"
    assert second["mfds_procurement_crosslinks"] == [{"모델": "HeartOn A16-DS", "나라장터 직접거래": 92}]
    assert second["category_market"] == "MARKET"

    index["file"] = "b" * 64  # a new serving index arrived
    third = _search_state()
    build_namespace()["_ensure_same_item_market"](third)
    assert calls == ["crosslinks", "category", "crosslinks", "category"]
    assert third["same_item_cache"] == "miss"


def test_cache_keeps_at_most_the_limit_and_drops_the_oldest() -> None:
    from purchase_price.ui import same_item_cache

    same_item_cache.clear()
    for number in range(same_item_cache.LIMIT + 3):
        same_item_cache.put(("file", f"MODEL-{number}"), [{"n": number}], None)
    assert same_item_cache.size() == same_item_cache.LIMIT
    assert same_item_cache.get(("file", "MODEL-0")) is None
    assert same_item_cache.get(("file", f"MODEL-{same_item_cache.LIMIT + 2}")) == ([{"n": same_item_cache.LIMIT + 2}], None)
    same_item_cache.clear()


def test_the_page_script_keeps_no_cache_of_its_own() -> None:
    # v32 kept the dict in the page script; every rerun emptied it (two production misses).
    assert "_SAME_ITEM_CACHE" not in SOURCE
    assert "same_item_cache.get(cache_key)" in SOURCE and "same_item_cache.put(" in SOURCE
