from __future__ import annotations

from decimal import Decimal

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_market_models import MarketResearchBundle
from purchase_price.services.g2b_unmapped_discovery import (
    G2BUnmappedDiscoveryResult,
    discover_unmapped_g2b_candidates,
)
from purchase_price.services.market_price_research import (
    quote_delta_from_market_median,
    should_run_broad_research,
    summarize_g2b_research,
)
from purchase_price.services.market_research import research_g2b_market
from purchase_price.services.market_research_support import build_web_supplier_search_links
from purchase_price.services.search import SearchRun, search_all
from purchase_price.ui.g2b_market_research import render_g2b_market_research


def run_market_research(
    query: ProductQuery,
    *,
    lookback_days: int,
    research_pages_per_term: int = 1,
    research_request_budget: int = 18,
    procurement_detail_limit: int = 4,
) -> tuple[SearchRun, G2BUnmappedDiscoveryResult | None, MarketResearchBundle | None]:
    """Run direct-price, shopping discovery and procurement Research independently.

    Shopping direct-price/discovery can use a credential approved only for ShoppingMall API while
    bid/award/pre-spec/item/contract Research can use a separate service subscription. Research
    records remain outside `search_all` and `assess_prices` regardless of which key is configured.
    """

    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    research_key = (settings.resolved_g2b_research_service_key or "").strip()

    run = search_all(query, build_collectors(g2b_lookback_days=lookback_days))

    market_bundle = None
    if should_run_broad_research(query, g2b_enabled=bool(research_key)):
        market_bundle = research_g2b_market(
            query,
            service_key=research_key,
            lookback_days=min(lookback_days, 90),
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=min(settings.g2b_max_retries, 2),
            max_terms=6,
            max_pages_per_window=research_pages_per_term,
        )
        market_bundle = enrich_market_bundle_with_bid_items(
            market_bundle,
            service_key=research_key,
            max_bid_notices=procurement_detail_limit,
            max_pages_per_bid=1,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=min(settings.g2b_max_retries, 2),
        )
        market_bundle = enrich_market_bundle_with_contracts(
            market_bundle,
            service_key=research_key,
            max_bid_notices=procurement_detail_limit,
            max_pages_per_bid=1,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=min(settings.g2b_max_retries, 2),
        )

    discovery = None
    if should_run_broad_research(query, g2b_enabled=bool(shopping_key)):
        discovery = discover_unmapped_g2b_candidates(
            query,
            service_key=shopping_key,
            lookback_days=lookback_days,
            base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
            pages_per_term_window=research_pages_per_term,
            request_budget=research_request_budget,
        )
    return run, discovery, market_bundle


def render_market_reference_summary(
    discovery: G2BUnmappedDiscoveryResult | None,
    *,
    quote_unit_price: Decimal | None = None,
) -> None:
    summary = summarize_g2b_research(discovery)
    if discovery is None:
        return
    if discovery.status == "failure":
        st.warning("나라장터 쇼핑몰 Research API 조회가 실패했습니다. 이는 시장자료 0건과 다릅니다.")
        return
    if not summary.has_prices:
        st.info("쇼핑몰 Research는 정상 실행됐지만 현재 검색어·기간에서 가격 후보가 0건입니다.")
        return

    st.markdown("**나라장터 쇼핑몰 시장참고 범위**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("관련 가격후보", f"{summary.candidate_count}건")
    c2.metric("하단", f"{summary.low:,.0f}원" if summary.low is not None else "-")
    c3.metric("중앙값", f"{summary.median:,.0f}원" if summary.median is not None else "-")
    c4.metric("상단", f"{summary.high:,.0f}원" if summary.high is not None else "-")
    st.caption(
        "이 범위는 검증 전 관련 세부품명·제조사·분류 후보를 포함할 수 있는 시장조사 참고값입니다. "
        "동일제품 직접가격 범위와는 분리됩니다."
    )

    delta = quote_delta_from_market_median(quote_unit_price, summary)
    if delta is not None:
        direction = "높음" if delta > 0 else "낮음" if delta < 0 else "동일"
        st.info(
            f"현재 견적은 Research 중앙값 대비 **{abs(delta):.1f}% {direction}**입니다. "
            "이는 시장참고 비교이며 최종 적정성 판정은 아닙니다."
        )


def render_procurement_research(bundle: MarketResearchBundle | None) -> None:
    if bundle is None:
        return
    render_g2b_market_research(bundle)


def render_external_research_links(query: ProductQuery) -> None:
    links = build_web_supplier_search_links(query.product_name, query.model_name)
    if not links:
        return
    with st.expander("추가 웹 조사", expanded=False):
        st.caption("나라장터 밖의 공개 웹 자료를 추가로 확인할 때 사용하는 보조 검색입니다.")
        for label, url in links:
            st.link_button(label, url)
