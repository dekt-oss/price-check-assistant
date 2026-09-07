from __future__ import annotations

from dataclasses import replace

import streamlit as st

from purchase_price.config import get_settings
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_extraction import parse_quote_decimal, quote_item_query
from purchase_price.services.quote_research_hints import build_quote_filename_research_hints
from purchase_price.ui.market_research import (
    render_external_research_links,
    render_market_reference_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.quote_review_contract import build_manual_quote_item
from purchase_price.ui.quote_review_state import QuoteReviewState
from purchase_price.ui.quote_review_steps import _store_extraction
from purchase_price.ui.widgets import (
    render_condition_table,
    render_discovery_candidates,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)


def _money(value) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _clear_research(state: QuoteReviewState) -> None:
    state.search_runs.clear()
    state.discoveries.clear()
    state.market_bundles.clear()
    state.comparability_context.clear()
    state.approvals.clear()


def _invalidate_item_review(state: QuoteReviewState, index: int) -> None:
    state.item_confirmed[index] = False
    state.item_notes.pop(index, None)
    state.condition_notes.pop(index, None)
    state.identity.pop(index, None)
    _clear_research(state)
    state.step = 2


def _query_for_item(state: QuoteReviewState, index: int):
    """Build a strict identity query plus research-only aliases from quote context."""

    query = quote_item_query(state.items[index])
    hints = build_quote_filename_research_hints(state.file_name or "")
    if not hints:
        return query
    return replace(query, research_hints=hints)


def _render_inline_manual_item_form(state: QuoteReviewState) -> None:
    st.warning(
        "자동 추출 결과가 없습니다. 다른 검토 모드로 이동할 필요 없이 이 화면에서 핵심 품목정보를 입력하면 "
        "저장 직후 시장조사를 시작합니다."
    )
    with st.form("quote_auto_manual_item"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input("품명", placeholder="예: 극초단파치료시스템")
        manufacturer = c2.text_input("제조사", placeholder="선택")
        model_name = c1.text_input("모델명", placeholder="선택")
        specification = c2.text_input("규격", placeholder="선택")
        quantity = c1.text_input("수량", placeholder="예: 1")
        unit = c2.text_input("단위", placeholder="예: SET")
        unit_price = c1.text_input("견적 단가", placeholder="예: 66000000")
        total_amount = c2.text_input("총액", placeholder="선택")
        vat = c1.text_input("VAT", placeholder="포함/별도/면세 등 선택")
        installation = c2.text_input("설치", placeholder="선택")
        options = c1.text_input("옵션/구성", placeholder="선택")
        warranty = c2.text_input("보증", placeholder="선택")
        submitted = st.form_submit_button("품목 저장 후 시장조사", type="primary")

    if not submitted:
        return

    try:
        item = build_manual_quote_item(
            product_name=product_name,
            manufacturer=manufacturer,
            model_name=model_name,
            specification=specification,
            quantity=parse_quote_decimal(quantity),
            unit=unit,
            unit_price=parse_quote_decimal(unit_price),
            total_amount=parse_quote_decimal(total_amount),
            vat_status=vat,
            delivery_condition="",
            installation_condition=installation,
            option_condition=options,
            warranty_condition=warranty,
            maintenance_condition="",
            other_conditions="",
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    state.items = [item]
    state.item_confirmed = {0: False}
    state.item_notes = {0: "자동 추출 0건 — 통합 견적검토 화면에서 담당자 수동 입력"}
    state.condition_notes = {0: {}}
    state.identity.clear()
    _clear_research(state)
    state.step = 2
    st.success("품목을 저장했습니다. 시장가격 조사를 시작합니다.")
    st.rerun()


def _render_compact_item_editor(state: QuoteReviewState) -> None:
    if not state.items:
        return
    with st.expander("추출 품목 수정", expanded=False):
        st.caption(
            "자동 추출이 틀린 경우 핵심 식별정보와 견적 단가만 수정하세요. "
            "VAT·설치·보증 등 세부조건은 시장검색의 필수조건이 아닙니다."
        )
        index = st.selectbox(
            "수정할 품목",
            options=list(range(len(state.items))),
            format_func=lambda i: (
                f"{i + 1}. {state.items[i].product_name or state.items[i].model_name or '미확인 품목'}"
            ),
            key="quote_auto_edit_index",
        )
        item = state.items[int(index)]
        with st.form(f"quote_auto_edit_{index}"):
            c1, c2 = st.columns(2)
            product_name = c1.text_input("품명", value=item.product_name)
            manufacturer = c2.text_input("제조사", value=item.manufacturer)
            model_name = c1.text_input("모델명", value=item.model_name)
            specification = c2.text_input("규격", value=item.specification)
            unit_price = c1.text_input(
                "견적 단가",
                value="" if item.unit_price is None else format(item.unit_price, "f"),
            )
            quantity = c2.text_input(
                "수량",
                value="" if item.quantity is None else format(item.quantity, "f"),
            )
            saved = st.form_submit_button("수정 저장")
        if saved:
            state.items[int(index)] = replace(
                item,
                product_name=product_name.strip(),
                manufacturer=manufacturer.strip(),
                model_name=model_name.strip(),
                specification=specification.strip(),
                unit_price=parse_quote_decimal(unit_price),
                quantity=parse_quote_decimal(quantity),
            )
            _invalidate_item_review(state, int(index))
            st.success("품목을 수정했습니다. 기존 식별·비교상태를 초기화하고 시장가격을 다시 조사합니다.")
            st.rerun()


def _ensure_market_research(state: QuoteReviewState) -> None:
    if not state.items:
        return
    missing = [index for index in range(len(state.items)) if index not in state.search_runs]
    if not missing:
        return

    progress = st.progress(0, text="견적 품목의 시장가격을 자동 조사하고 있습니다...")
    total = len(missing)
    for done, index in enumerate(missing, start=1):
        item = state.items[index]
        query = _query_for_item(state, index)
        progress.progress(
            (done - 1) / total,
            text=(
                f"{index + 1}/{len(state.items)} · "
                f"{item.product_name or item.model_name or '미확인 품목'} 조사 중"
            ),
        )
        run, discovery, market_bundle = run_market_research(
            query,
            lookback_days=state.lookback_days,
            research_pages_per_term=1,
            research_request_budget=24,
            procurement_detail_limit=4,
        )
        state.search_runs[index] = run
        state.discoveries[index] = discovery
        state.market_bundles[index] = market_bundle
    progress.progress(1.0, text="시장가격 자동 조사를 완료했습니다.")


def _render_overview(state: QuoteReviewState) -> None:
    direct_evidence_count = sum(len(run.results) for run in state.search_runs.values())
    procurement_record_count = sum(
        len(bundle.records) for bundle in state.market_bundles.values() if bundle is not None
    )
    discovery_candidate_count = sum(
        len(discovery.candidates)
        for discovery in state.discoveries.values()
        if discovery is not None
    )
    unconfirmed_count = sum(
        not state.item_confirmed.get(index, False) for index in range(len(state.items))
    )

    st.subheader("검토 요약")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("견적 품목", f"{len(state.items)}건")
    c2.metric("검증 직접근거", f"{direct_evidence_count}건")
    c3.metric("조달 Research", f"{procurement_record_count + discovery_candidate_count}건")
    c4.metric("원문 확인 필요", f"{unconfirmed_count}건")
    st.caption(
        "Research는 동일제품 자료가 부족해도 넓게 계속 수행합니다. 조달 Research·쇼핑몰 후보는 "
        "검증된 동일제품 직접가격과 분리되며 최종 판정에는 자동 투입되지 않습니다."
    )


def _render_item_result(state: QuoteReviewState, index: int) -> None:
    item = state.items[index]
    query = _query_for_item(state, index)
    run = state.search_runs.get(index)
    discovery = state.discoveries.get(index)
    market_bundle = state.market_bundles.get(index)

    with st.container(border=True):
        title = item.product_name or item.model_name or f"품목 {index + 1}"
        st.subheader(f"{index + 1}. {title}")
        st.caption(
            " · ".join(
                part for part in (item.manufacturer, item.model_name, item.specification) if part
            )
            or "추가 식별정보 없음"
        )
        if query.research_hints:
            st.caption(
                "자동 확장 Research: "
                + " · ".join(query.research_hints)
                + " — 견적 파일명에서 얻은 조사 힌트이며 동일제품 identity 근거는 아닙니다."
            )
        c1, c2, c3 = st.columns(3)
        c1.metric("견적 단가", _money(item.unit_price))
        c2.metric("수량", str(item.quantity) if item.quantity is not None else "미확인")
        c3.metric("단위", item.unit or "미확인")

        render_procurement_research(market_bundle)
        render_market_reference_summary(discovery, quote_unit_price=item.unit_price)

        if run is not None and run.results:
            assessment = assess_prices(run.results, item.unit_price)
            st.markdown("**검증된 동일제품 직접가격 근거**")
            d1, d2, d3 = st.columns(3)
            d1.metric("직접근거", f"{assessment.observed_count}건")
            d2.metric("독립 출처", f"{assessment.source_count}개")
            d3.metric("신뢰도", assessment.confidence)
            render_observation_cards(run.results)
        else:
            st.caption(
                "검증된 동일제품 직접가격이 없어도 입찰·품목상세·낙찰·사전규격·계약 Research는 "
                "시장조사 참고자료로 계속 제공합니다."
            )

        if discovery is not None and discovery.candidates:
            with st.expander("나라장터 쇼핑몰 동일·동급·대체 후보", expanded=False):
                render_discovery_candidates(discovery)

        render_external_research_links(query)

        with st.expander("상세 근거·비교조건", expanded=False):
            st.caption(
                "VAT·배송·설치·옵션·보증 등은 여기서 확인합니다. 이 정보가 비어 있어도 시장검색 자체는 중단하지 않습니다."
            )
            if run is not None:
                render_source_status(run)
                if run.results:
                    render_evidence_table(run.results)
                    render_condition_table(run.results)
                    profiles = [build_price_condition_profile(evidence) for evidence in run.results]
                    if profiles:
                        average = round(
                            sum(profile.completeness_percent for profile in profiles) / len(profiles)
                        )
                        st.caption(f"직접근거 평균 조건명시율: {average}%")
            st.write(
                {
                    "견적 VAT": item.vat_status or "미확인",
                    "배송": item.delivery_condition or "미확인",
                    "설치": item.installation_condition or "미확인",
                    "옵션/구성": item.option_condition or "미확인",
                    "보증": item.warranty_condition or "미확인",
                    "유지보수": item.maintenance_condition or "미확인",
                }
            )


def render_quote_market_research(state: QuoteReviewState) -> None:
    st.info(
        "견적서를 업로드하면 정확 모델명뿐 아니라 견적의 일반 품명·나라장터 세부품명 후보·동급 품목군까지 "
        "Research를 넓혀 동시에 조사합니다. 대체품 가격은 동일제품 가격과 분리합니다."
    )

    uploaded = st.file_uploader(
        "견적서 파일",
        type=["pdf", "xlsx", "xls"],
        key="quote_auto_market_upload",
    )
    if uploaded is not None and (state.file_name != uploaded.name or state.extraction is None):
        _store_extraction(uploaded, state)
        state.lookback_days = G2B_DEFAULT_LOOKBACK_DAYS

    if state.extraction is None:
        st.caption("PDF · xlsx · xls 견적서를 업로드하면 품목 추출과 시장조사가 한 번에 시작됩니다.")
        return

    top1, top2, top3 = st.columns([1.3, 2.2, 1])
    top1.metric("추출 품목", f"{len(state.items)}건")
    top2.metric("파일", state.file_name or "-")
    if top3.button("새 견적서로 초기화"):
        st.session_state.pop("quote_review_state", None)
        st.rerun()

    if state.diagnostics is not None:
        st.caption(f"추출 경로: {state.diagnostics.strategy_label}")

    settings = get_settings()
    st.caption(
        "나라장터 API 인증 라우팅: "
        f"입찰·낙찰·사전규격={settings.g2b_research_key_source} · "
        f"쇼핑몰·납품={settings.g2b_shopping_key_source}"
    )

    if state.extraction.warnings:
        with st.expander(f"추출 경고 {len(state.extraction.warnings)}건", expanded=False):
            for warning in state.extraction.warnings:
                st.warning(warning)

    if not state.items:
        _render_inline_manual_item_form(state)
        return

    st.markdown("**인식된 견적 품목**")
    rows = [
        {
            "품목": index + 1,
            "품명": item.product_name,
            "제조사": item.manufacturer,
            "모델": item.model_name,
            "규격": item.specification,
            "견적단가": float(item.unit_price) if item.unit_price is not None else None,
        }
        for index, item in enumerate(state.items)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    _render_compact_item_editor(state)

    with st.expander("검색 설정", expanded=False):
        selected_lookback = int(
            st.selectbox(
                "나라장터 검색기간",
                options=G2B_LOOKBACK_OPTIONS,
                index=(
                    G2B_LOOKBACK_OPTIONS.index(state.lookback_days)
                    if state.lookback_days in G2B_LOOKBACK_OPTIONS
                    else G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS)
                ),
                format_func=g2b_lookback_label,
                key="quote_auto_lookback",
            )
        )
        if selected_lookback != state.lookback_days:
            state.lookback_days = selected_lookback
            _clear_research(state)
            st.rerun()
        if st.button("시장가격 다시 조사", key="quote_auto_research_again"):
            _clear_research(state)
            st.rerun()

    _ensure_market_research(state)
    _render_overview(state)

    st.subheader("품목별 시장조사")
    for index in range(len(state.items)):
        _render_item_result(state, index)
