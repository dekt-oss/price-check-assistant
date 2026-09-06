from decimal import Decimal

import pytest

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.ui.quote_review_contract import (
    build_extracted_item_snippet,
    build_manual_quote_item,
    changed_item_field_labels,
)


def _item() -> QuoteItem:
    return QuoteItem(
        source_sheet="Sheet1",
        source_row=7,
        product_name="프린터",
        manufacturer="Maker",
        model_name="M-1",
        specification="A3",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("1000"),
        total_amount=Decimal("1000"),
        vat_status="포함",
    )


def test_changed_fields_and_snippet_are_grounded_in_extracted_item() -> None:
    original = _item()
    edited = QuoteItem(
        **{
            **original.__dict__,
            "manufacturer": "Maker Korea",
            "unit_price": Decimal("1100"),
        }
    )
    assert changed_item_field_labels(original, edited) == ("제조사", "단가")
    snippet = build_extracted_item_snippet(original)
    assert "프린터" in snippet
    assert "Maker" in snippet
    assert "M-1" in snippet
    assert "단가 1000" in snippet


def test_manual_item_requires_identity_and_marks_manual_provenance() -> None:
    with pytest.raises(ValueError, match="하나 이상"):
        build_manual_quote_item(
            product_name="",
            manufacturer="",
            model_name="",
            specification="",
            quantity=None,
            unit="",
            unit_price=None,
            total_amount=None,
            vat_status="",
            delivery_condition="",
            installation_condition="",
            option_condition="",
            warranty_condition="",
            maintenance_condition="",
            other_conditions="",
        )

    item = build_manual_quote_item(
        product_name="프린터",
        manufacturer="Maker",
        model_name="M-1",
        specification="A3",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("1000"),
        total_amount=Decimal("1000"),
        vat_status="포함",
        delivery_condition="",
        installation_condition="",
        option_condition="",
        warranty_condition="",
        maintenance_condition="",
        other_conditions="",
    )
    assert item.source_sheet == "수동 입력"
    assert item.source_row == 1
    assert item.product_name == "프린터"
