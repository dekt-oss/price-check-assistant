from __future__ import annotations

from decimal import Decimal

from purchase_price.ui.track_b_transactions import _quantity_text, _quantity_unit


def test_quantity_text_drops_trailing_zeros_without_exponents() -> None:
    assert _quantity_text(Decimal("1.000")) == "1"
    assert _quantity_text(Decimal("100")) == "100"
    assert _quantity_text(Decimal("2.50")) == "2.5"
    assert _quantity_text(None) == "미확인"
    assert _quantity_unit(Decimal("3.000"), "개") == "3 개"
