from __future__ import annotations

from dataclasses import replace

import streamlit as st

from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_extraction import parse_quote_decimal, quote_item_query
from purchase_price.ui.market_research import (
    render_external_research_links,
    render_market_reference_summary,
    run_market_research,
)
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
    state.comparability_context.clear()
    state.approvals.clear()


def _render_compact_item_editor(state: QuoteReviewState) -> None:
    if not state.items:
        return
    with st.expander("추출 품목 수정", expanded=False):
        st.caption(
            "자동 추출이 틀린 경우 핵심 식별정보와 견적 단가만 수정하세요. VAT·설치·보증 등 세부조건은 시장검색의 필수조건이 아닙니다."
        )
        index = st.selectbox(
            "수정할 품목",
            options=list(range(len(state.items))),
            format_func=lambda i: f"{i + 1}. {state.items[i].product_name or state.items[i].model_name or '미확인 품목'}",
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
            _clear_research(state)
            st.success("품목을 수정했습니다. 시장가격을 다시 조사합니다.")
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
        query = quote_item_query(item)
        progress.progress(
            (done - 1) / total,
            text=f"{index + 1}/{len(state.items)} · {item.product_name or item.model_name or '미확인 품목'} 조사 중",
        )
        run, discovery = run_market_research(
            query,
            lookback_days=state.lookback_days,
            research_pages_per_term=1,
            research_request_budget=18,
        )
        state.search_runs[index] = run
        state.discoveries[index] = discovery
    progress.progress(1.0, text="시장가격 자동 조사를 완료했습니다.")


def _render_item_result(state: QuoteReviewState, index: int) -> None:
    item = state.items[index]
    query = quote_item_query(item)
    run = state.search_runs.get(index)
    discovery = state.discoveries.get(index)

    with st.container(border=True):
        title = item.product_name or item.model_name or f"품목 {index + 1}"
        st.subheader(f"{index + 1}. {title}")
        st.caption(
            " · ".join(
                part
                for part in (
                    item.manufacturer,
                    item.model_name,
                    item.specification,
                )
                if part
            )
            or "추가 식별정보 없음"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("견적 단가", _money(item.unit_price))
        c2.metric("수량", str(item.quantity) if item.quantity is not None else "미확인")
        c3.metric("단위", item.unit or "미확인")

        render_market_reference_summary(discovery, quote_unit_price=item.unit_price)

        if run is not None and run.results:
            assessment = assess_prices(run.results, item.unit_price)
            st.markdown("**동일제품/직접가격 근거**")
            d1, d2, d3 = st.columns(3)
            d1.metric("직접근거", f"{assessment.observed_count}건")
            d2.metric("독립 출처", f"{assessment.source_count}개")
            d3.metric("신뢰도", assessment.confidence)
            render_observation_cards(run.results)
        else:
            st.caption("검증된 동일제품 직접가격이 없어도 위 시장참고 조사는 계속 제공합니다.")

        if discovery is not None and discovery.candidates:
            with st.expander("나라장터 관련 거래 후보", expanded=True):
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
        "견적서를 업로드하면 품목을 추출한 뒤 **제품 식별 확인을 기다리지 않고 바로 시장가격 조사를 시작**합니다. "
        "세부조건은 검색 제한이 아니라 결과 해석을 위한 보조정보입니다."
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
        st.caption("PDF · xlsx · xls 견적서를 업로드하면 자동 시장가격 조사가 시작됩니다.")
        return

    top1, top2, top3 = st.columns([1.3, 1, 1])
    top1.metric("추출 품목", f"{len(state.items)}건")
    top2.metric("파일", state.file_name or "-")
    if top3.button("새 견적서로 초기화"):
        st.session_state.pop("quote_review_state", None)
        st.rerun()

    if state.extraction.warnings:
        with st.expander(f"추출 경고 {len(state.extraction.warnings)}건", expanded=False):
            for warning in state.extraction.warnings:
                st.warning(warning)

    if not state.items:
        st.warning("자동 추출 품목이 없습니다. 정밀 비교검토에서 수동 품목을 입력할 수 있습니다.")
        return

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

    st.subheader("품목별 시장가격")
    for index in range(len(state.items)):
        _render_item_result(state, index)
