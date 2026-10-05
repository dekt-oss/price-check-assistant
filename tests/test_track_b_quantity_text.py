from __future__ import annotations

from decimal import Decimal

from purchase_price.ui.track_b_transactions import _quantity_text, _quantity_unit


def test_quantity_text_drops_trailing_zeros_without_exponents() -> None:
    assert _quantity_text(Decimal("1.000")) == "1"
    assert _quantity_text(Decimal("100")) == "100"
    assert _quantity_text(Decimal("2.50")) == "2.5"
    assert _quantity_text(None) == "미확인"
    assert _quantity_unit(Decimal("3.000"), "개") == "3 개"


def test_group_total_quantity_is_normalized() -> None:
    from types import SimpleNamespace

    from purchase_price.domain import MatchGrade
    from purchase_price.ui.track_b_transactions import model_price_group_rows

    candidates = tuple(
        SimpleNamespace(
            model_name="NT-SG",
            specification="(부품)스탠드형보관함",
            price=Decimal("396000"),
            quantity=Decimal("2.000"),
            transaction_date="2026-10-01",
            match_grade=MatchGrade.B,
            contract_delivery_type=None,
            contract_type=None,
            delivery_condition=None,
        )
        for _ in range(3)
    )
    rows = model_price_group_rows(SimpleNamespace(candidates=candidates))

    assert rows[0]["총수량"] == "6"
