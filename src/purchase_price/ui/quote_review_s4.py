from __future__ import annotations

import streamlit as st

from purchase_price.config import get_settings
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.quote_extraction import quote_item_query
from purchase_price.ui.market_research import (
    render_market_reference_summary,
    run_market_research,
)
from purchase_price.ui.quote_review_state import QuoteReviewState, can_enter
from purchase_price.ui.widgets import (
    render_discovery_candidates,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)


def render_s4(state: QuoteReviewState, index: int) -> None:
    st.subheader("4. 근거 수집")
    item = state.items[index]
    settings = get_settings()
    g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())
    state.lookback_days = int(
        st.selectbox(
            "나라장터 검색기간",
            options=G2B_LOOKBACK_OPTIONS,
            index=(
                G2B_LOOKBACK_OPTIONS.index(state.lookback_days)
                if state.lookback_days in G2B_LOOKBACK_OPTIONS
                else G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS)
            ),
            format_func=g2b_lookback_label,
            disabled=not g2b_enabled,
            key=f"quote_g2b_lookback_{index}",
            help="1~5년 모두 API 허용범위 안의 기간창으로 나눠 조사합니다.",
        )
    )

    if st.button("이 품목 시장가격 검색", type="primary", key=f"search_evidence_{index}"):
        state.reset_downstream(after_step=4)
        query = quote_item_query(item)
        with st.status("시장가격과 공개근거를 검색하고 있습니다...", expanded=True) as status_box:
            status_box.write("검증된 직접가격 source를 확인합니다.")
            status_box.write(
                "제품명이 있으면 verified mapping 유무와 관계없이 나라장터 Research 후보도 함께 조사합니다."
            )
            run, discovery = run_market_research(
                query,
                lookback_days=state.lookback_days,
                research_pages_per_term=1,
                research_request_budget=24,
            )
            state.search_runs[index] = run
            state.discoveries[index] = discovery
            status_box.update(
                label=f"검색 완료 · 검증근거 {len(run.results)}건",
                state="complete",
                expanded=False,
            )

    run = state.search_runs.get(index)
    if run is None:
        st.info("검색을 실행하면 시장참고 범위와 검증 직접근거가 이곳에 표시됩니다.")
        return

    discovery = state.discoveries.get(index)
    st.markdown("**시장가격 요약**")
    render_market_reference_summary(discovery, quote_unit_price=item.unit_price)

    if discovery is not None:
        st.markdown("**나라장터 Research 후보 — 판정 미포함**")
        render_discovery_candidates(discovery)

    if run.results:
        st.markdown("**검증 직접가격 범위 — 출처·VAT별 분리**")
        render_observation_cards(run.results)
        st.markdown("**검증 가격근거**")
        render_evidence_table(run.results)
    else:
        st.caption("검증된 동일제품 직접 가격근거가 없어도 Research 시장참고 결과는 사용할 수 있습니다.")

    with st.expander("출처별 검색상태", expanded=False):
        render_source_status(run)
        failed = [
            source for source in run.source_statuses if not source.succeeded and not source.skipped
        ]
        if failed:
            st.error(
                "수집 미완료: "
                + ", ".join(source.source_name for source in failed)
                + ". API 실패는 정상 0건과 구분됩니다."
            )
        if run.errors:
            st.warning(" / ".join(run.errors))

    allowed, reasons = can_enter(5, state)
    for reason in reasons:
        st.info(reason)
    if st.button("5. 조건 대조로", type="primary", disabled=not allowed):
        state.step = 5
        st.rerun()
