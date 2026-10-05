from __future__ import annotations

import importlib

from purchase_price.services import track_b_r2_quote_index


def test_track_b_snapshot_adapter_imports_when_loaded_legacy_module_lacks_new_opener(
    monkeypatch,
) -> None:
    monkeypatch.delattr(
        track_b_r2_quote_index,
        "open_track_b_serving_snapshot",
        raising=False,
    )

    module = importlib.import_module(
        "purchase_price.services.track_b_serving_snapshot"
    )

    assert callable(module.open_track_b_serving_snapshot)
    assert module._native_snapshot_opener() is None


def test_dashboard_uses_hot_reload_safe_track_b_snapshot_adapter() -> None:
    from pathlib import Path

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert (
        "from purchase_price.services import track_b_serving_snapshot as track_b_snapshot_service"
    ) in source
    assert (
        "from purchase_price.services.track_b_r2_quote_index "
        "import open_track_b_serving_snapshot"
    ) not in source


def test_snapshot_falls_back_when_loaded_db_module_lacks_batch_lookup(monkeypatch) -> None:
    from types import SimpleNamespace

    from purchase_price.schemas import ProductQuery
    from purchase_price.services import track_b_db_quote_comparison
    from purchase_price.services.track_b_serving_snapshot import TrackBServingSnapshot

    monkeypatch.delattr(
        track_b_db_quote_comparison,
        "compare_track_b_models_batch",
        raising=False,
    )
    calls: list[tuple[str, object, int]] = []

    def fake_compare(_session, query, *, quote_unit_price, limit):
        calls.append((query.model_name, quote_unit_price, limit))
        return SimpleNamespace(status="success_0", candidates=())

    monkeypatch.setattr(
        track_b_db_quote_comparison,
        "compare_track_b_quote",
        fake_compare,
    )
    snapshot = TrackBServingSnapshot(status="available", session=object())
    queries = (
        ProductQuery(product_name="품목", model_name="MODEL-A"),
        ProductQuery(product_name="품목", model_name="MODEL-B"),
    )

    results = snapshot.lookup_model_summaries(
        queries,
        quote_unit_prices=(None, None),
        limit_per_model=50,
    )

    assert len(results) == 2
    assert calls == [
        ("MODEL-A", None, 50),
        ("MODEL-B", None, 50),
    ]


def test_dashboard_reloads_retained_pre_fix_track_b_modules() -> None:
    from pathlib import Path

    from purchase_price.services import track_b_db_quote_comparison, track_b_live_gap_fill
    from purchase_price.services import track_b_serving_snapshot as snapshot

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "snapshot_runtime, live_runtime = _track_b_runtime()" in source
    assert "with snapshot_runtime.open_track_b_serving_snapshot() as track_b_snapshot:" in source
    assert "merge_live_gap = live_runtime.merge_live_gap" in source
    # The markers the guard checks must exist in the current modules.
    assert hasattr(track_b_db_quote_comparison, "_not_cancelled_clause")
    assert hasattr(snapshot, "WORKSPACE_LOOKUP_LIMIT")
    assert track_b_live_gap_fill.DROPS_CANCELLED_LINES is True
