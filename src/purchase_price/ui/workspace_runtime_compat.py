from __future__ import annotations

from decimal import Decimal
from typing import Any

from purchase_price.services import track_b_r2_quote_index


class LegacyTrackBServingSnapshot:
    """Compatibility adapter for a cached pre-V3 Track B R2 module.

    Streamlit Community Cloud may reload the page before reloading an already imported
    service module. The pre-V3 module has lookup_track_b_quote_from_r2 but not the reusable
    snapshot API. This adapter keeps the page available until the process naturally reloads.
    """

    status = "legacy_compat"
    data_as_of: str | None = None

    def __enter__(self) -> "LegacyTrackBServingSnapshot":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def lookup(self, query, *, quote_unit_price):
        return track_b_r2_quote_index.lookup_track_b_quote_from_r2(
            query,
            quote_unit_price=quote_unit_price,
        )

    def lookup_model_summaries(
        self,
        queries,
        *,
        quote_unit_prices=None,
        limit_per_model: int = 50,
    ):
        del limit_per_model
        queries = tuple(queries)
        prices = (
            tuple(quote_unit_prices)
            if quote_unit_prices is not None
            else tuple(None for _ in queries)
        )
        return tuple(
            track_b_r2_quote_index.lookup_track_b_quote_from_r2(
                query,
                quote_unit_price=price,
            )
            for query, price in zip(queries, prices, strict=True)
        )


def open_track_b_serving_snapshot_compat():
    opener = getattr(track_b_r2_quote_index, "open_track_b_serving_snapshot", None)
    if callable(opener):
        return opener()
    return LegacyTrackBServingSnapshot()


def build_quote_position_message_compat(
    *,
    quote_unit_price: Decimal | None,
    stats: Any,
    unit: str = "",
    vat_status: str = "",
    conditions: str = "",
) -> str:
    """V3 quote-position copy kept outside the potentially cached legacy UI module."""

    if quote_unit_price is None or quote_unit_price <= 0:
        return "내 견적가를 입력하면 A/B 직접비교 자료에서 관측된 위치를 확인할 수 있습니다."

    qualifiers = [
        f"단위 {unit.strip()}" if unit.strip() else "단위 미확인",
        f"VAT {vat_status.strip()}" if vat_status.strip() else "VAT 미확인",
        f"조건 {conditions.strip()}" if conditions.strip() else "설치·운송 조건 미확인",
    ]
    qualifier_text = " · ".join(qualifiers)

    if stats.direct_count == 0 or stats.min_price is None or stats.max_price is None:
        return f"직접 비교자료가 없어 가격 위치를 계산하지 않습니다. {qualifier_text}."

    if stats.direct_count == 1:
        only = stats.min_price
        delta = ((quote_unit_price - only) / only * 100).quantize(Decimal("0.1"))
        return (
            f"직접 비교자료 1건 대비 {delta:+.1f}%입니다. "
            f"1건뿐으로 가격대 판단근거가 부족합니다. {qualifier_text}."
        )

    if quote_unit_price > stats.max_price:
        delta = ((quote_unit_price - stats.max_price) / stats.max_price * 100).quantize(
            Decimal("0.1")
        )
        position = f"직접 비교자료 상단 대비 {delta:+.1f}%"
    elif quote_unit_price < stats.min_price:
        delta = ((quote_unit_price - stats.min_price) / stats.min_price * 100).quantize(
            Decimal("0.1")
        )
        position = f"직접 비교자료 하단 대비 {delta:+.1f}%"
    else:
        position = "직접 비교자료 관측 범위 안"

    return f"내 견적가는 {position}에 위치합니다. {qualifier_text}. 조건 동일성을 별도로 확인하세요."
