from decimal import Decimal
from types import SimpleNamespace

from purchase_price.schemas import ProductQuery
from purchase_price.ui import workspace_runtime_compat


def test_legacy_track_b_adapter_uses_pre_v3_lookup_when_snapshot_symbol_is_missing(monkeypatch) -> None:
    module = workspace_runtime_compat.track_b_r2_quote_index
    monkeypatch.delattr(module, "open_track_b_serving_snapshot", raising=False)
    calls = []

    def lookup(query, *, quote_unit_price):
        calls.append((query.model_name, quote_unit_price))
        return SimpleNamespace(status="success_0")

    monkeypatch.setattr(module, "lookup_track_b_quote_from_r2", lookup)

    with workspace_runtime_compat.open_track_b_serving_snapshot_compat() as snapshot:
        one = snapshot.lookup(
            ProductQuery(product_name="채혈기", model_name="C101"),
            quote_unit_price=Decimal("500"),
        )
        many = snapshot.lookup_model_summaries(
            (
                ProductQuery(product_name="채혈기", model_name="C101"),
                ProductQuery(product_name="채혈기", model_name="C102"),
            )
        )

    assert one.status == "success_0"
    assert [item.status for item in many] == ["success_0", "success_0"]
    assert calls == [
        ("C101", Decimal("500")),
        ("C101", None),
        ("C102", None),
    ]


def test_quote_position_compat_does_not_make_adequacy_verdict() -> None:
    stats = SimpleNamespace(
        direct_count=2,
        min_price=Decimal("100"),
        max_price=Decimal("120"),
    )

    message = workspace_runtime_compat.build_quote_position_message_compat(
        quote_unit_price=Decimal("130"),
        stats=stats,
        unit="개",
        vat_status="포함",
        conditions="배송 포함",
    )

    assert "상단 대비 +8.3%" in message
    assert "단위 개" in message
    assert "VAT 포함" in message
    assert "조건 배송 포함" in message
    assert "적정" not in message
    assert "부적정" not in message
    assert "권고" not in message


def test_dashboard_imports_only_pre_v3_symbols_from_cached_runtime_modules() -> None:
    source = open("pages/1_대시보드.py", encoding="utf-8").read()

    assert "open_track_b_serving_snapshot_compat" in source
    assert "build_quote_position_message_compat" in source
    assert "from purchase_price.services.track_b_r2_quote_index import open_track_b_serving_snapshot" not in source
    purchase_import = source.split(
        "from purchase_price.ui.purchase_workspace import (", 1
    )[1].split(")", 1)[0]
    assert "build_quote_position_message" not in purchase_import
