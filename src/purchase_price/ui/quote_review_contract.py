from __future__ import annotations

from decimal import Decimal

from purchase_price.services.quote_extraction import QuoteItem

_ITEM_FIELD_LABELS = (
    ("product_name", "품명"),
    ("manufacturer", "제조사"),
    ("model_name", "모델명"),
    ("specification", "규격"),
    ("quantity", "수량"),
    ("unit", "단위"),
    ("unit_price", "단가"),
    ("total_amount", "금액"),
    ("vat_status", "VAT"),
    ("delivery_condition", "배송"),
    ("installation_condition", "설치"),
    ("option_condition", "옵션/구성"),
    ("warranty_condition", "보증"),
    ("maintenance_condition", "유지보수"),
    ("other_conditions", "기타 조건"),
)


def changed_item_field_labels(original: QuoteItem, current: QuoteItem) -> tuple[str, ...]:
    """Return human-readable labels for fields changed from the extracted item."""
    return tuple(
        label
        for field_name, label in _ITEM_FIELD_LABELS
        if getattr(original, field_name) != getattr(current, field_name)
    )


def build_extracted_item_snippet(item: QuoteItem) -> str:
    """Build a compact, non-invented representation of the extracted row for source review."""
    values = [
        item.product_name,
        item.manufacturer,
        item.model_name,
        item.specification,
        f"수량 {item.quantity}" if item.quantity is not None else "",
        item.unit,
        f"단가 {item.unit_price}" if item.unit_price is not None else "",
        f"금액 {item.total_amount}" if item.total_amount is not None else "",
        f"VAT {item.vat_status}" if item.vat_status else "",
    ]
    return " · ".join(str(value).strip() for value in values if str(value).strip())


def build_manual_quote_item(
    *,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
    quantity: Decimal | None,
    unit: str,
    unit_price: Decimal | None,
    total_amount: Decimal | None,
    vat_status: str,
    delivery_condition: str,
    installation_condition: str,
    option_condition: str,
    warranty_condition: str,
    maintenance_condition: str,
    other_conditions: str,
) -> QuoteItem:
    """Build the explicit S2 manual-entry row used only when automatic extraction returned zero."""
    if not any(
        value.strip()
        for value in (product_name, manufacturer, model_name, specification)
    ):
        raise ValueError("수동 품목 입력에는 품명·제조사·모델명·규격 중 하나 이상이 필요합니다.")
    return QuoteItem(
        source_sheet="수동 입력",
        source_row=1,
        product_name=product_name.strip(),
        manufacturer=manufacturer.strip(),
        model_name=model_name.strip(),
        specification=specification.strip(),
        quantity=quantity,
        unit=unit.strip(),
        unit_price=unit_price,
        total_amount=total_amount,
        vat_status=vat_status.strip(),
        delivery_condition=delivery_condition.strip(),
        installation_condition=installation_condition.strip(),
        option_condition=option_condition.strip(),
        warranty_condition=warranty_condition.strip(),
        maintenance_condition=maintenance_condition.strip(),
        other_conditions=other_conditions.strip(),
    )
