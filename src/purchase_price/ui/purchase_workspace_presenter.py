from __future__ import annotations

from decimal import Decimal
from typing import Any

from purchase_price.ui import purchase_workspace as legacy_purchase_workspace

build_purchase_workspace_stats = legacy_purchase_workspace.build_purchase_workspace_stats
supplier_rows = legacy_purchase_workspace.supplier_rows


def build_quote_position_message(
    *,
    quote_unit_price: Decimal | None,
    stats: Any,
    unit: str = "",
    vat_status: str = "",
    conditions: str = "",
) -> str:
    """Hot-reload-safe quote-position presenter.

    Streamlit Cloud can retain the pre-Workspace-V3 purchase_workspace module.
    Use its native presenter when available; otherwise preserve the current
    descriptive, non-recommendation wording locally.
    """

    native = getattr(legacy_purchase_workspace, "build_quote_position_message", None)
    if callable(native):
        return native(
            quote_unit_price=quote_unit_price,
            stats=stats,
            unit=unit,
            vat_status=vat_status,
            conditions=conditions,
        )

    if quote_unit_price is None or quote_unit_price <= 0:
        return "내 견적가를 입력하면 A/B 직접비교 자료에서 관측된 위치를 확인할 수 있습니다."

    qualifiers = [
        f"단위 {unit.strip()}" if unit.strip() else "단위 미확인",
        f"VAT {vat_status.strip()}" if vat_status.strip() else "VAT 미확인",
        f"조건 {conditions.strip()}" if conditions.strip() else "설치·운송 조건 미확인",
    ]
    qualifier_text = " · ".join(qualifiers)

    direct_count = int(getattr(stats, "direct_count", 0) or 0)
    min_price = getattr(stats, "min_price", None)
    max_price = getattr(stats, "max_price", None)
    if direct_count == 0 or min_price is None or max_price is None:
        return f"직접 비교자료가 없어 가격 위치를 계산하지 않습니다. {qualifier_text}."

    if direct_count == 1:
        delta = ((quote_unit_price - min_price) / min_price * 100).quantize(Decimal("0.1"))
        return (
            f"직접 비교자료 1건 대비 {delta:+.1f}%입니다. "
            f"1건뿐으로 가격대 판단근거가 부족합니다. {qualifier_text}."
        )

    if quote_unit_price > max_price:
        delta = ((quote_unit_price - max_price) / max_price * 100).quantize(Decimal("0.1"))
        position = f"직접 비교자료 상단 대비 {delta:+.1f}%"
    elif quote_unit_price < min_price:
        delta = ((quote_unit_price - min_price) / min_price * 100).quantize(Decimal("0.1"))
        position = f"직접 비교자료 하단 대비 {delta:+.1f}%"
    else:
        position = "직접 비교자료 관측 범위 안"

    return (
        f"내 견적가는 {position}에 위치합니다. {qualifier_text}. "
        "조건 동일성을 별도로 확인하세요."
    )
