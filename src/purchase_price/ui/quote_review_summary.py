from __future__ import annotations

import html
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import streamlit as st

from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_comparable_approval import quote_evidence_pair_key
from purchase_price.ui.quote_review_layout import comparable_trade_stats
from purchase_price.ui.quote_review_state import QuoteReviewState

# Runtime marker: re-imports comparable_trade_stats, which now leaves 입력 오류 의심 trades out.
QUOTE_REVIEW_ENTRY_ERRORS_V1 = True
# Runtime marker: 구매 검토 요약 is a wrapping card per item (no sideways-scrolling table).
QUOTE_REVIEW_SUMMARY_CARDS_V1 = True


@dataclass(frozen=True)
class PurchaseReviewSummaryRow:
    item_index: int
    item_name: str
    quote_unit_price: Decimal | None
    strict_count: int
    reference_count: int
    public_direct_count: int | None
    observed_low: Decimal | None
    observed_median: Decimal | None
    observed_high: Decimal | None
    approved_count: int
    review_status: str
    market_status: str
    other_unit_count: int = 0


def _approved_count(state: QuoteReviewState, index: int) -> int:
    context = state.comparability_context.get(index)
    run = state.search_runs.get(index)
    if context is None or run is None:
        return 0
    count = 0
    for evidence in run.results:
        key = quote_evidence_pair_key(context, evidence)
        if key in state.approvals:
            count += 1
    return count


def _market_status(track_b: Any, strict_count: int, reference_count: int) -> str:
    if track_b is None:
        return "거래를 아직 찾지 않음"
    status = str(getattr(track_b, "status", "") or "")
    if status == "unavailable":
        return "나라장터 가격 자료를 지금은 쓸 수 없음"
    if status == "not_ingested":
        return "가격 자료 준비 중"
    if status == "insufficient_identity":
        return "품명이나 모델명이 필요함"
    if strict_count:
        return "같은 모델 거래 있음"
    if reference_count:
        return "이름이 비슷한 거래만 있음"
    return "찾은 범위에 거래 없음"


def _review_status(
    *,
    item_confirmed: bool,
    strict_count: int,
    reference_count: int,
    approved_count: int,
) -> str:
    """상세 검증(선택)의 진행 상태. 위 비교표의 '판정'과는 별개입니다."""

    if approved_count:
        return "검증 완료"
    if not item_confirmed:
        return "검증 전 · 견적서 원문과 맞춰 보지 않음"
    if strict_count:
        return "검증 전 · 거래 조건을 맞춰 보지 않음"
    if reference_count:
        return "이름이 비슷한 거래만 있어 같은 제품인지 따져 봐야 함"
    return "거래를 더 찾아봐야 함"


def build_purchase_review_summary_rows(
    state: QuoteReviewState,
) -> list[PurchaseReviewSummaryRow]:
    rows: list[PurchaseReviewSummaryRow] = []
    for index, item in enumerate(state.items):
        track_b = state.track_b_db.get(index)
        # Same trades as the comparison table: default period, same unit as most trades.
        stats = comparable_trade_stats(track_b)
        run = state.search_runs.get(index)
        public_direct_count = None
        if run is not None:
            public_direct_count = assess_prices(run.results, item.unit_price).observed_count
        approved_count = _approved_count(state, index)
        item_name = item.product_name or item.model_name or f"품목 {index + 1}"
        rows.append(
            PurchaseReviewSummaryRow(
                item_index=index,
                item_name=item_name,
                quote_unit_price=item.unit_price,
                strict_count=stats.count,
                reference_count=stats.reference_count,
                public_direct_count=public_direct_count,
                observed_low=stats.low,
                observed_median=stats.median,
                observed_high=stats.high,
                approved_count=approved_count,
                review_status=_review_status(
                    item_confirmed=bool(state.item_confirmed.get(index, False)),
                    strict_count=stats.count,
                    reference_count=stats.reference_count,
                    approved_count=approved_count,
                ),
                market_status=_market_status(track_b, stats.count, stats.reference_count),
                other_unit_count=stats.other_count,
            )
        )
    return rows


def _money(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _range_text(row: PurchaseReviewSummaryRow) -> str:
    if row.observed_low is None or row.observed_high is None:
        return "계산할 수 없음"
    return f"{row.observed_low:,.0f} ~ {row.observed_high:,.0f}원"


QUOTE_REVIEW_ACCEPTANCE_V3 = True

DETAIL_VERIFY_NOTE = (
    "상세 검증은 선택 사항입니다. 위 비교표의 판정은 상세 검증과 상관없이 같은 모델 거래의 가운데 값으로 "
    "계산합니다. 상세 검증은 부가세·수량·설치·옵션·보증 같은 거래 조건까지 같은지 담당자가 거래를 하나씩 "
    "확인해 승인하는, 더 꼼꼼한 확인 단계입니다."
)


def purchase_summary_fields(row: PurchaseReviewSummaryRow) -> list[tuple[str, str, int]]:
    """(label, value, columns spanned) for one item; the same facts the old 11-column table held."""

    return [
        ("견적 단가", _money(row.quote_unit_price), 1),
        ("같은 모델 거래", f"{row.strict_count}건", 1),
        ("단위가 다른 거래", f"{row.other_unit_count}건" if row.other_unit_count else "없음", 1),
        ("이름이 비슷한 거래", f"{row.reference_count}건", 1),
        (
            "그 밖의 공개 가격 자료",
            f"{row.public_direct_count}건" if row.public_direct_count is not None else "아직 찾지 않음",
            1,
        ),
        ("거래 가격대", _range_text(row), 2),
        ("거래 가운데 값", _money(row.observed_median), 1),
        ("승인한 거래", f"{row.approved_count}건", 1),
        ("상세 검증", row.review_status, 2),
        ("거래 자료 상태", row.market_status, 1),
    ]


PURCHASE_SUMMARY_CSS = """
<style>
.qs-list {display:flex; flex-direction:column; gap:10px; margin:6px 0 10px 0;}
.qs-item {border:1px solid var(--pc-border, #DCE5EF); border-radius:12px; background:#fff; padding:12px 16px 14px 16px;}
.qs-name {font-size:14px; font-weight:700; color:var(--pc-navy, #14304F); margin-bottom:10px; overflow-wrap:anywhere; word-break:keep-all;}
.qs-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px 18px; margin:0;}
.qs-grid > div {min-width:0;}
.qs-grid .qs-span2 {grid-column:span 2;}
.qs-grid dt {font-size:11px; font-weight:700; color:var(--pc-muted, #6B7C93); margin:0 0 2px 0;}
.qs-grid dd {font-size:13px; line-height:1.45; margin:0; overflow-wrap:anywhere; word-break:keep-all;}
@media (max-width: 1200px) { .qs-grid {grid-template-columns:repeat(2,minmax(0,1fr));} }
@media (max-width: 560px) { .qs-grid {grid-template-columns:minmax(0,1fr);} .qs-grid .qs-span2 {grid-column:auto;} }
</style>
"""


def purchase_summary_html(rows: list[PurchaseReviewSummaryRow]) -> str:
    """One wrapping card per item instead of an 11-column table that was cut off on the right."""

    cards = []
    for row in rows:
        fields = "".join(
            f'<div class="{"qs-span2" if span > 1 else ""}"><dt>{html.escape(label)}</dt>'
            f"<dd>{html.escape(value)}</dd></div>"
            for label, value, span in purchase_summary_fields(row)
        )
        cards.append(
            f'<div class="qs-item"><div class="qs-name">{row.item_index + 1}. {html.escape(row.item_name)}</div>'
            f'<dl class="qs-grid">{fields}</dl></div>'
        )
    return PURCHASE_SUMMARY_CSS + f'<div class="qs-list" id="purchase-review-summary-cards-v1">{"".join(cards)}</div>'


def render_purchase_review_summary(state: QuoteReviewState) -> None:
    rows = build_purchase_review_summary_rows(state)
    if not rows:
        return

    with st.container(border=True):
        st.markdown("### 구매 검토 요약")
        st.caption(
            "찾은 거래와 상세 검증 진행 상황을 한눈에 봅니다. 거래 가격대와 가운데 값은 실제 거래 기록일 뿐 "
            "적정 가격을 뜻하지 않습니다."
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("품목", f"{len(rows)}건")
        c2.metric("거래가 있는 품목", f"{sum(row.strict_count > 0 for row in rows)}건")
        c3.metric("상세 검증을 마친 품목", f"{sum(row.approved_count > 0 for row in rows)}건")
        c4.metric("상세 검증 전 품목", f"{sum(row.approved_count == 0 for row in rows)}건")

        st.markdown(purchase_summary_html(rows), unsafe_allow_html=True)
        st.caption(DETAIL_VERIFY_NOTE)
