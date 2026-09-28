from __future__ import annotations

import importlib
from decimal import Decimal
from types import SimpleNamespace

from purchase_price.ui import purchase_workspace


def test_workspace_presenter_survives_legacy_module_without_quote_position(
    monkeypatch,
) -> None:
    monkeypatch.delattr(
        purchase_workspace,
        "build_quote_position_message",
        raising=False,
    )
    module = importlib.reload(
        importlib.import_module("purchase_price.ui.purchase_workspace_presenter")
    )
    stats = SimpleNamespace(
        direct_count=2,
        min_price=Decimal("100"),
        max_price=Decimal("120"),
    )

    message = module.build_quote_position_message(
        quote_unit_price=Decimal("130"),
        stats=stats,
        unit="개",
        vat_status="포함",
        conditions="배송 포함",
    )

    assert "상단 대비 +8.3%" in message
    assert "적정" not in message
    assert "권고" not in message


def test_dashboard_uses_hot_reload_safe_workspace_presenter() -> None:
    from pathlib import Path

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "from purchase_price.ui.purchase_workspace_presenter import (" in source
    assert "from purchase_price.ui.purchase_workspace import (" not in source
