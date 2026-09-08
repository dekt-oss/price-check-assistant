from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_bid_item_enrichment import enrich_market_bundle_with_bid_items
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.services.g2b_catalog_enrichment import enrich_discovery_with_catalog
from purchase_price.services.g2b_classification_research import resolve_classification_research
from purchase_price.services.g2b_contract_enrichment import enrich_market_bundle_with_contracts
from purchase_price.services.g2b_lifecycle import G2B_LIFECYCLE_BASE_URL
from purchase_price.services.g2b_lifecycle_enrichment import enrich_market_bundle_with_lifecycle
from purchase_price.services.g2b_market_models import MarketResearchBundle
from purchase_price.services.g2b_unmapped_discovery import (
    G2BDiscoveryCandidate,
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
from purchase_price.services.research_basis import (
    ResearchBasis,
    research_terms_with_basis,
    resolve_research_basis,
)
from purchase_price.services.search import SearchRun, search_all
from purchase_price.ui.g2b_market_research import render_g2b_market_research


def _classification_session_key(query: ProductQuery) -> str:
    raw = "|".join((query.manufacturer, query.model_name, query.product_name)).casefold()
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"g2b_classification_candidate_{digest}"


def _targeted_detail_codes(
    query: ProductQuery,
    *,
    basis: ResearchBasis,
    classification_resolution,
) -> tuple[str, ...]:
    """Choose a bounded Shopping Research code without promoting resolver candidates."""

    code = (basis.code or "").strip()
    if basis.is_verified_official and code.isdigit() and len(code) == 10:
        return (code,)

    if classification_resolution is None or not classification_resolution.candidates:
        return ()
    selected = str(st.session_state.get(_classification_session_key(query), "") or "").strip()
    allowed = {
        candidate.detail_product_code
        for candidate in classification_resolution.candidates
        if candidate.detail_product_code.isdigit() and len(candidate.detail_product_code) == 10
    }
    return (selected,) if selected in allowed else ()


def run_market_research(
    query: ProductQuery,
    *,
    lookback_days: int,
    research_pages_per_term: int = 1,
    research_request_budget: int = 18,
    procurement_detail_limit: int = 4,
) -> tuple[SearchRun, G2BUnmappedDiscoveryResult | None, MarketResearchBundle | None]:
    """Run direct-price, Shopping discovery and procurement Research independently.

    Resolver candidates can expand Research recall or, after explicit session selection, drive a
    targeted detail-code query. None of those records or candidates are passed to `search_all` or
    `assess_prices`.
    """

    # Static safety contract kept verbatim for regression tests: None of those records
    # or candidates are passed to `search_all` or `assess_prices`.
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    research_key = (settings.resolved_g2b_research_service_key or "").strip()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    lifecycle_key = (settings.resolved_g2b_lifecycle_service_key or "").strip()

    run = search_all(query, build_collectors(g2b_lookback_days=lookback_days))

    basis = resolve_research_basis(query)
    broad_research_requested = should_run_broad_research(
        query,
        g2b_enabled=bool(research_key or shopping_key),
    )
    classification_resolution = None
    if broad_research_requested and not basis.is_verified_official:
        classification_resolution = resolve_classification_research(
            query,
            service_key=catalog_key,
            base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
            timeout_seconds=min(settings.g2b_request_timeout_seconds, 10.0),
            max_retries=1,
        )
    resolver_terms = (
        classification_resolution.research_terms if classification_resolution is not None else ()
    )
    targeted_codes = _targeted_detail_codes(
        query,
        basis=basis,
        classification_resolution=classification_resolution,
    )
    research_terms = research_terms_with_basis(query) + resolver_terms

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
            additional_terms=resolver_terms,
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
            independent_terms=research_terms,
            requested_lookback_days=lookback_days,
            max_independent_terms=1,
            max_pages_per_window=1,
        )
        market_bundle = enrich_market_bundle_with_lifecycle(
            market_bundle,
            service_key=lifecycle_key,
            max_bid_notices=min(procurement_detail_limit, 2),
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=min(settings.g2b_max_retries, 2),
            base_url=settings.g2b_lifecycle_base_url or G2B_LIFECYCLE_BASE_URL,
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
            curated_terms=research_terms,
            target_detail_product_codes=targeted_codes,
        )
        if classification_resolution is not None:
            discovery = replace(
                discovery,
                classification_resolution_status=classification_resolution.status.value,
                classification_lookup_terms=tuple(
                    request.term for request in classification_resolution.lookup_requests
                ),
                classification_candidates=classification_resolution.candidates,
                classification_specification_clues=classification_resolution.specification_clues,
                classification_error_types=classification_resolution.error_types,
                classification_error_messages=classification_resolution.error_messages,
            )
        if catalog_key and discovery.candidates:
            discovery = enrich_discovery_with_catalog(
                discovery,
                service_key=catalog_key,
                max_candidates=3,
                timeout_seconds=min(settings.g2b_request_timeout_seconds, 10.0),
                max_retries=1,
                base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
            )
    return run, discovery, market_bundle


def _basis_status_label(basis: ResearchBasis) -> str:
    if basis.is_verified_official:
        return "공식 조달분류 확인"
    return "Research 기준명 후보 · 미검증"


def _render_classification_candidates(
    query: ProductQuery,
    discovery: G2BUnmappedDiscoveryResult,
) -> None:
    status = discovery.classification_resolution_status
    if not status:
        return

    if status == "failure":
        details = " · ".join(discovery.classification_error_messages[:2])
        st.warning(
            "공식 세부품명 resolver 조회가 실패했습니다. 이는 공식분류 후보 0건과 다릅니다."
            + (f" ({details})" if details else "")
        )
        return
    if status == "not_configured":
        st.caption("공식 세부품명 resolver는 API 키가 없어 이번 실행에서 조회하지 않았습니다.")
        return
    if status == "success_0":
        st.info("공식 세부품명 resolver는 정상 실행됐지만 현재 품명으로 확인된 후보가 0건입니다.")
        return
    if status == "partial":
        st.warning("공식 세부품명 resolver 일부 요청이 실패했습니다. 아래 후보는 부분 결과입니다.")

    if not discovery.classification_candidates:
        return

    candidates = list(discovery.classification_candidates)
    with st.expander("공식 세부품명 후보 · Research 미검증", expanded=True):
        st.dataframe(
            [
                {
                    "세부품명번호": candidate.detail_product_code,
                    "한글명": candidate.korean_name,
                    "영문명": candidate.english_name or "-",
                    "사용상태": candidate.use_status or "-",
                    "탐색근거": f"{candidate.search_field.value}={candidate.search_term}",
                }
                for candidate in candidates
            ],
            use_container_width=True,
            hide_index=True,
        )
        if discovery.classification_specification_clues:
            st.caption(
                "견적에서 분리 보존한 규격 단서: "
                + " · ".join(
                    f"`{clue}`" for clue in discovery.classification_specification_clues
                )
            )

        labels = {
            candidate.detail_product_code: (
                f"{candidate.korean_name} · {candidate.detail_product_code}"
            )
            for candidate in candidates
        }
        st.selectbox(
            "이번 세션에서 우선 확인할 공식 세부품명 후보",
            options=[""] + list(labels),
            format_func=lambda code: "미확정" if not code else labels[code],
            key=_classification_session_key(query),
        )
        # Safety wording contract: verified mapping 파일을 수정하지
        st.caption(
            "선택값은 현재 세션의 세부품명번호 표적 Research 조회에만 사용합니다. "
            "verified mapping 파일을 수정하지 않으며, 후보 선택만으로 견적 제품과 동일제품·규격동등으로 "
            "확정하거나 가격을 `assess_prices()`에 승격하지 않습니다."
        )


def _render_research_basis(
    query: ProductQuery,
    discovery: G2BUnmappedDiscoveryResult | None,
) -> None:
    basis = resolve_research_basis(query)
    st.markdown("**가격조사 기준**")
    c1, c2 = st.columns([2, 1])
    c1.metric("기준 품목명", basis.name or "미확인")
    c2.metric("분류 상태", _basis_status_label(basis))
    if basis.code:
        st.caption(f"공식 세부품명번호: `{basis.code}` · {basis.rationale}")
    else:
        st.caption(basis.rationale)

    if discovery is not None:
        _render_classification_candidates(query, discovery)
        if discovery.targeted_detail_codes:
            target_source = (
                "검증 공식분류"
                if basis.is_verified_official
                else "세션에서 명시적으로 선택한 Research 후보"
            )
            st.caption(
                "세부품명번호 표적 Shopping Research 실행: "
                + " · ".join(f"`{code}`" for code in discovery.targeted_detail_codes)
                + f" · 근거: {target_source}. 표적조회 자체는 동일제품 판정이 아닙니다."
            )

    if discovery is not None and discovery.terms:
        with st.expander("실제 검색 확장어", expanded=False):
            st.write(" · ".join(f"`{term}`" for term in discovery.terms[:8]))
            st.caption(
                "검색 확장어는 넓은 Research용입니다. 검색어 자체로 동일제품·공식분류·대체가능성을 "
                "확정하지 않습니다."
            )


def _quantity_unit(candidate: G2BDiscoveryCandidate) -> str:
    if candidate.quantity is None:
        return candidate.unit or "-"
    quantity = f"{candidate.quantity:,.4f}".rstrip("0").rstrip(".")
    return f"{quantity} {candidate.unit}".strip()


def _candidate_rows(candidates: list[G2BDiscoveryCandidate]) -> list[dict[str, str]]:
    return [
        {
            "후보": candidate.title,
            "품목식별번호": candidate.product_id or "-",
            "분류": candidate.classification_name or "-",
            "분류번호": candidate.classification_code or "-",
            "기관": candidate.institution or "-",
            "공급업체": candidate.supplier or "-",
            "수량·단위": _quantity_unit(candidate),
            "라인": candidate.item_sequence or "-",
            "납품조건": candidate.delivery_condition or "-",
            "변경차수": candidate.record_change_order or "-",
            "원문규격": candidate.original_specification or "-",
            "가격": f"{candidate.price:,.0f}원",
            "관계": candidate.relevance,
            "공식 품목속성": candidate.catalog_summary or "-",
            "근거": candidate.match_reason or "Research 후보",
        }
        for candidate in candidates[:10]
    ]


def _render_model_price_summary(
    discovery: G2BUnmappedDiscoveryResult,
    *,
    quote_unit_price: Decimal | None = None,
) -> None:
    summary = summarize_g2b_research(discovery)
    model_candidates = [
        candidate
        for candidate in discovery.candidates
        if candidate.relevance == "모델 표기 후보" and candidate.price > 0
    ]

    if summary.has_prices:
        st.markdown("**동일모델 표기 가격 후보 · 미검증 Research**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("동일모델 가격후보", f"{summary.model_candidate_count}건")
        c2.metric("하단", f"{summary.low:,.0f}원" if summary.low is not None else "-")
        c3.metric("중앙값", f"{summary.median:,.0f}원" if summary.median is not None else "-")
        c4.metric("상단", f"{summary.high:,.0f}원" if summary.high is not None else "-")
        if model_candidates:
            st.dataframe(
                _candidate_rows(model_candidates),
                use_container_width=True,
                hide_index=True,
            )
        st.caption(
            "모델 문자열이 표기된 Research 후보만 집계합니다. 공식 품목속성은 해당 나라장터 "
            "품목식별번호의 규격 검증 보조근거이며, 견적 제품과 동일제품임을 자동 확정하지 않습니다. "
            "기관·공급업체·라인·규격·납품조건·변경차수는 원자료 추적용 provenance이며 가격 승격 근거가 아닙니다. "
            "최종 동일제품 직접가격 범위는 엄격한 제품 식별·비교조건 검증을 통과한 Evidence로 별도 산정합니다."
        )

        delta = quote_delta_from_market_median(quote_unit_price, summary)
        if delta is not None:
            direction = "높음" if delta > 0 else "낮음" if delta < 0 else "동일"
            st.info(
                f"현재 견적은 동일모델 표기 Research 중앙값 대비 **{abs(delta):.1f}% {direction}**입니다. "
                "이는 미검증 Research 비교이며 최종 적정성 판정은 아닙니다."
            )
    elif discovery.candidates:
        st.info(
            "동일모델로 집계할 수 있는 가격 후보는 0건입니다. 대체품·관련품목 가격은 아래에서 개별 "
            "참고로만 표시합니다."
        )
    else:
        st.info("쇼핑몰 Research는 정상 실행됐지만 현재 조사 기준·기간에서 유의미한 가격 후보가 0건입니다.")


def _render_related_price_candidates(
    query: ProductQuery,
    discovery: G2BUnmappedDiscoveryResult,
) -> None:
    basis = resolve_research_basis(query)
    related = [
        candidate
        for candidate in discovery.candidates
        if candidate.relevance != "모델 표기 후보" and candidate.price > 0
    ]
    if not related:
        return

    same_official_class: list[G2BDiscoveryCandidate] = []
    if basis.is_verified_official and basis.code:
        same_official_class = [
            candidate for candidate in related if candidate.classification_code == basis.code
        ]
    same_official_ids = {id(candidate) for candidate in same_official_class}
    unverified_related = [
        candidate for candidate in related if id(candidate) not in same_official_ids
    ]

    if same_official_class:
        st.markdown("**동일 공식분류의 다른 제품 · 실제 납품가격 참고**")
        st.dataframe(
            _candidate_rows(same_official_class),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "견적 품목과 동일한 검증 세부품명번호에 속한 타 제품의 실제 납품가격 후보입니다. "
            "나라장터 품목식별번호의 공식 속성이 조회된 후보는 규격 비교 보조근거를 함께 표시합니다. "
            "동일 분류가 곧 규격·성능 동등을 의미하지 않으므로 개별 대체품 후보로만 확인하며, "
            "동일모델 가격 범위에는 합산하지 않습니다."
        )

    if unverified_related:
        st.markdown("**공식분류 미확정 규격·관련품목 대체후보 · 개별 참고**")
        st.dataframe(
            _candidate_rows(unverified_related),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "공식 분류 또는 규격 동등성이 확인되지 않은 후보입니다. 후보 자체와 개별 가격은 조사 "
            "참고로 보여주되 가격 band와 견적 대비 증감률 계산에는 포함하지 않습니다."
        )


def render_model_price_research_summary(
    discovery: G2BUnmappedDiscoveryResult | None,
    *,
    quote_unit_price: Decimal | None = None,
) -> None:
    if discovery is None or discovery.status == "failure":
        return
    _render_model_price_summary(discovery, quote_unit_price=quote_unit_price)


def render_market_alternative_candidates(
    discovery: G2BUnmappedDiscoveryResult | None,
    *,
    query: ProductQuery,
) -> None:
    if discovery is None or discovery.status == "failure":
        return
    _render_related_price_candidates(query, discovery)


def render_market_reference_summary(
    discovery: G2BUnmappedDiscoveryResult | None,
    *,
    query: ProductQuery,
    quote_unit_price: Decimal | None = None,
    include_model_price_summary: bool = True,
    include_related_candidates: bool = True,
) -> None:
    _render_research_basis(query, discovery)
    if discovery is None:
        return
    if discovery.status == "failure":
        st.warning("나라장터 쇼핑몰 Research API 조회가 실패했습니다. 이는 시장자료 0건과 다릅니다.")
        return

    if include_model_price_summary:
        _render_model_price_summary(discovery, quote_unit_price=quote_unit_price)
    if include_related_candidates:
        _render_related_price_candidates(query, discovery)


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
