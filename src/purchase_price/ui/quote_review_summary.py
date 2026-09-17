from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any

import streamlit as st

from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_comparable_approval import quote_evidence_pair_key
from purchase_price.ui.quote_review_state import QuoteReviewState
from purchase_price.ui.track_b_transactions import (
    category_reference_candidates,
    reference_candidates,
    strict_comparison_candidates,
)


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


def _positive_prices(candidates: tuple[Any, ...]) -> list[Decimal]:
    prices: list[Decimal] = []
    for candidate in candidates:
        value = getattr(candidate, "price", None)
        if value is None:
            continue
        try:
            price = Decimal(str(value))
        except Exception:
            continue
        if price.is_finite() and price > 0:
            prices.append(price)
    return prices


def _observed_range(
    candidates: tuple[Any, ...],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    prices = sorted(_positive_prices(candidates))
    if not prices:
        return None, None, None
    return prices[0], Decimal(str(median(prices))), prices[-1]


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
        return "거래가격 조회 전"
    status = str(getattr(track_b, "status", "") or "")
    if status == "unavailable":
        return "거래가격 DB 연결 확인"
    if status == "not_ingested":
        return "가격 인덱스 준비 중"
    if status == "insufficient_identity":
        return "제품 식별 필요"
    if strict_count:
        return "동일성 거래 확인"
    if reference_count:
        return "참고거래만 확인"
    return "현재 수집범위 0건"


def _review_status(
    *,
    item_confirmed: bool,
    strict_count: int,
    reference_count: int,
    approved_count: int,
) -> str:
    if approved_count:
        return "담당자 승인 근거 있음"
    if not item_confirmed:
        return "품목 원문 확인 필요"
    if strict_count:
        return "조건대조·승인 전"
    if reference_count:
        return "동일성 확인 필요"
    return "추가 조사 필요"


def build_purchase_review_summary_rows(
    state: QuoteReviewState,
) -> list[PurchaseReviewSummaryRow]:
    rows: list[PurchaseReviewSummaryRow] = []
    for index, item in enumerate(state.items):
        track_b = state.track_b_db.get(index)
        strict = strict_comparison_candidates(track_b) if track_b is not None else ()
        references = (
            (
                *category_reference_candidates(track_b),
                *reference_candidates(track_b),
            )
            if track_b is not None
            else ()
        )
        low, med, high = _observed_range(strict)
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
                strict_count=len(strict),
                reference_count=len(references),
                public_direct_count=public_direct_count,
                observed_low=low,
                observed_median=med,
                observed_high=high,
                approved_count=approved_count,
                review_status=_review_status(
                    item_confirmed=bool(state.item_confirmed.get(index, False)),
                    strict_count=len(strict),
                    reference_count=len(references),
                    approved_count=approved_count,
                ),
                market_status=_market_status(track_b, len(strict), len(references)),
            )
        )
    return rows


def _money(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _range_text(row: PurchaseReviewSummaryRow) -> str:
    if row.observed_low is None or row.observed_high is None:
        return "산정불가"
    return f"{row.observed_low:,.0f} ~ {row.observed_high:,.0f}원"


def render_purchase_review_summary(state: QuoteReviewState) -> None:
    rows = build_purchase_review_summary_rows(state)
    if not rows:
        return

    with st.container(border=True):
        st.markdown("### 구매검토 요약")
        st.caption(
            "현재 확보된 거래·공개근거와 검토 진행상태를 요약합니다. "
            "관측가격과 중앙값은 시장 관측치이며 자동 적정가격 판정이 아닙니다."
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("품목", f"{len(rows)}건")
        c2.metric("동일성 거래 확인 품목", f"{sum(row.strict_count > 0 for row in rows)}건")
        c3.metric("승인 근거 보유 품목", f"{sum(row.approved_count > 0 for row in rows)}건")
        c4.metric(
            "추가 확인 품목",
            f"{sum(row.review_status != '담당자 승인 근거 있음' for row in rows)}건",
        )

        st.dataframe(
            [
                {
                    "품목": row.item_name,
                    "견적 단가": _money(row.quote_unit_price),
                    "나라장터 동일성 거래": row.strict_count,
                    "나라장터 참고": row.reference_count,
                    "추가 공개 직접근거": (
                        f"{row.public_direct_count}건"
                        if row.public_direct_count is not None
                        else "미조사"
                    ),
                    "거래 관측범위": _range_text(row),
                    "거래 중앙값(Median)": _money(row.observed_median),
                    "담당자 승인": f"{row.approved_count}건",
                    "검토상태": row.review_status,
                    "데이터상태": row.market_status,
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "나라장터 동일성 거래도 VAT·수량·설치·옵션·보증 등 비교조건과 담당자 pair 승인을 "
            "통과하기 전에는 견적의 높고 낮음 판정에 사용하지 않습니다."
        )
