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
        "from purchase_price.services.track_b_serving_snapshot "
        "import open_track_b_serving_snapshot"
    ) in source
    assert (
        "from purchase_price.services.track_b_r2_quote_index "
        "import open_track_b_serving_snapshot"
    ) not in source
