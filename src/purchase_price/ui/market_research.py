from __future__ import annotations

from decimal import Decimal

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_market_models import G2BResearchSource, MarketResearchBundle
from purchase_price.services.g2b_research_terms import research_terms_for_query
from purchase_price.services.g2b_unmapped_discovery import (
    G2BUnmappedDiscoveryResult,
    discover_unmapped_g2b_candidates,
)
from purchase_price.services.market_price_research import (
    quote_delta_from_market_median,
    should_run_broad_research,
    summarize_g2b_research,
    summarize_g2b_research_bands,
)
from purchase_price.services.market_research import research_g2b_market
from purchase_price.services.market_research_support import build_web_supplier_search_links
from purchase_price.services.matching import normalize_text
from purchase_price.services.search import SearchRun, search_all
from purchase_price.ui.g2b_market_research import render_g2b_market_research


def _procurement_item_research_terms(
    bundle: MarketResearchBundle | None,
    query: ProductQuery,
    *,
    max_terms: int = 4,
) -> tuple[str, ...]:
    """Lift official purchase-object names into a second Research pass, never identity.

    If an exact/model/generic bid search finds a notice, the official purchase-object rows can name
    the category more usefully than the quote itself. Feeding those names into shopping Research is
    what allows an exact product to fan out to same-class competitors (e.g. a model-labelled phone
    bid -> an official smartphone item name -> other smartphone procurements). The terms stay
    Research-only and never establish MatchGrade.
    """

    if bundle is None or max_terms < 1:
        return ()

    existing = {
        normalize_text(value)
        for value in (
            query.product_name,
            query.model_name,
            query.manufacturer,
            *query.research_hints,
            *bundle.query_terms,
        )
        if value and normalize_text(value)
    }
    output: list[str] = []
    seen: set[str] = set()
    for record in bundle.records:
        if record.source_type != G2BResearchSource.BID_ITEM:
            continue
        term = (record.product_name or record.title or "").strip()
        key = normalize_text(term)
        if not key or key in existing or key in seen:
            continue
        # Avoid tiny/noisy item fragments while allowing ordinary category names such as 스마트폰.
        if len(key) < 3:
            continue
        seen.add(key)
        output.append(term)
        if len(output) >= max_terms:
            break
    return tuple(output)


def _shopping_expansion_terms(
    bundle: MarketResearchBundle | None,
    query: ProductQuery,
) -> tuple[str, ...]:
    """Combine curated aliases with official procurement item names, preserving order."""

    raw = (*research_terms_for_query(query), *_procurement_item_research_terms(bundle, query))
    output: list[str] = []
    seen: set[str] = set()
    for term in raw:
        key = normalize_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(term)
    return tuple(output)


def run_market_research(
    query: ProductQuery,
    *,
    lookback_days: int,
    research_pages_per_term: int = 1,
    research_request_budget: int = 18,
    procurement_detail_limit: int = 4,
) -> tuple[SearchRun, G2BUnmappedDiscoveryResult | None, MarketResearchBundle | None]:
    """Run strict direct-price collection and broad procurement research independently.

    G2B shopping/direct-price calls and bid/award/pre-spec research calls may use different
    data.go.kr subscription keys. Procurement Research and alternatives remain outside `search_all`
    and `assess_prices` until the existing strict identity/comparability gates approve evidence.
    None of those records are passed to `search_all` or `assess_prices`.
    """

    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    research_key = (settings.resolved_g2b_research_service_key or "").strip()
    run = search_all(query, build_collectors(g2b_lookback_days=lookback_days))

    discovery = None
    market_bundle = None
    if should_run_broad_research(query, g2b_enabled=bool(research_key)):
        market_bundle = research_g2b_market(
            query,
            service_key=research_key,
            lookback_days=min(lookback_days, 90),
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=min(settings.g2b_max_retries, 2),
            max_terms=10,
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
            curated_terms=_shopping_expansion_terms(market_bundle, query),
        )
    return run, discovery, market_bundle


def _render_band_metrics(label: str, band) -> None:
    st.markdown(f"**{label}**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("후보", f"{band.candidate_count}건")
    c2.metric("하단", f"{band.low:,.0f}원" if band.low is not None else "-")
    c3.metric("중앙값", f"{band.median:,.0f}원" if band.median is not None else "-")
    c4.metric("상단", f"{band.high:,.0f}원" if band.high is not None else "-")


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

    model_band, manufacturer_band, alternative_band = summarize_g2b_research_bands(discovery)
    st.markdown("**나라장터 쇼핑몰 Research 가격 후보**")
    st.caption(
        "동일모델 표기 후보, 동일 제조사·모델 미확인 후보, 동일분류·대체제품 후보를 분리합니다. "
        "특히 대체제품 가격은 동일제품 시장가격 범위나 최종 적정성 판정에 섞지 않습니다."
    )

    if model_band.has_prices:
        _render_band_metrics("동일모델 표기 후보 · 미검증", model_band)
        delta = quote_delta_from_market_median(quote_unit_price, model_band)
        if delta is not None:
            direction = "높음" if delta > 0 else "낮음" if delta < 0 else "동일"
            st.info(
                f"현재 견적은 동일모델 **표기 후보** 중앙값 대비 {abs(delta):.1f}% {direction}입니다. "
                "모델 표기가 같아도 옵션·VAT·설치·보증 확인 전에는 최종 판정이 아닙니다."
            )

    if manufacturer_band.has_prices:
        _render_band_metrics("동일 제조사 · 모델 미확인 후보", manufacturer_band)

    if alternative_band.has_prices:
        _render_band_metrics("동일분류·대체제품 후보", alternative_band)
        st.warning(
            "이 가격대는 같은 세부품명/품목군의 경쟁제품을 포함할 수 있는 대체품 Research입니다. "
            "동일제품 가격으로 사용하지 않으며 성능·옵션·임상적 대체 가능성을 별도로 확인해야 합니다."
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
