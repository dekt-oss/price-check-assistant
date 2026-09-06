from __future__ import annotations

from decimal import Decimal

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_unmapped_discovery import (
    G2BUnmappedDiscoveryResult,
    discover_unmapped_g2b_candidates,
)
from purchase_price.services.market_price_research import (
    quote_delta_from_market_median,
    should_run_broad_research,
    summarize_g2b_research,
)
from purchase_price.services.market_research_support import build_web_supplier_search_links
from purchase_price.services.search import SearchRun, search_all


def run_market_research(
    query: ProductQuery,
    *,
    lookback_days: int,
    research_pages_per_term: int = 1,
    research_request_budget: int = 24,
) -> tuple[SearchRun, G2BUnmappedDiscoveryResult | None]:
    """Run exact/direct sources and broad G2B research independently.

    Broad research is intentionally not gated by verified mapping or quote-condition completeness.
    It returns research candidates only; direct-price evidence continues to come from `search_all`.
    """

    settings = get_settings()
    g2b_key = (settings.resolved_g2b_service_key or "").strip()
    run = search_all(query, build_collectors(g2b_lookback_days=lookback_days))

    discovery = None
    if should_run_broad_research(query, g2b_enabled=bool(g2b_key)):
        discovery = discover_unmapped_g2b_candidates(
            query,
            service_key=g2b_key,
            lookback_days=lookback_days,
            base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
            pages_per_term_window=research_pages_per_term,
            request_budget=research_request_budget,
        )
    return run, discovery


def render_market_reference_summary(
    discovery: G2BUnmappedDiscoveryResult | None,
    *,
    quote_unit_price: Decimal | None = None,
) -> None:
    summary = summarize_g2b_research(discovery)
    if discovery is None:
        st.info("나라장터 Research를 실행할 제품명이 없습니다.")
        return
    if discovery.status == "failure":
        st.warning("나라장터 Research API 조회가 실패했습니다. 이는 시장자료 0건과 다릅니다.")
        return
    if not summary.has_prices:
        st.info("나라장터 Research는 정상 실행됐지만 현재 검색어·기간에서 가격 후보가 0건입니다.")
        return

    st.markdown("**나라장터 시장참고 범위**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("관련 가격후보", f"{summary.candidate_count}건")
    c2.metric("하단", f"{summary.low:,.0f}원" if summary.low is not None else "-")
    c3.metric("중앙값", f"{summary.median:,.0f}원" if summary.median is not None else "-")
    c4.metric("상단", f"{summary.high:,.0f}원" if summary.high is not None else "-")
    st.caption(
        "이 범위는 동일모델 확정가격뿐 아니라 관련 세부품명·제조사·분류 후보를 포함할 수 있는 "
        "시장조사 참고값입니다. 조건 미확인 때문에 검색 자체를 막지 않습니다."
    )

    detail = (
        f"모델 표기 {summary.model_candidate_count}건 · "
        f"제조사 표기 {summary.manufacturer_candidate_count}건 · "
        f"분류 후보 {summary.classification_candidate_count}건"
    )
    st.caption(detail)

    delta = quote_delta_from_market_median(quote_unit_price, summary)
    if delta is not None:
        direction = "높음" if delta > 0 else "낮음" if delta < 0 else "동일"
        st.info(
            f"현재 견적은 Research 중앙값 대비 **{abs(delta):.1f}% {direction}**입니다. "
            "이는 시장참고 비교이며 최종 적정성 판정은 아닙니다."
        )


def render_external_research_links(query: ProductQuery) -> None:
    links = build_web_supplier_search_links(query.product_name, query.model_name)
    if not links:
        return
    with st.expander("추가 웹 조사", expanded=False):
        st.caption("나라장터 밖의 공개 웹 자료를 추가로 확인할 때 사용하는 보조 검색입니다.")
        for label, url in links:
            st.link_button(label, url)
