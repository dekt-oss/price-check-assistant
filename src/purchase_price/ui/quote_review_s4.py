from __future__ import annotations

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, SOURCE_NAME
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates
from purchase_price.services.quote_extraction import quote_item_query
from purchase_price.services.search import search_all
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

    if st.button("이 품목 공개근거 검색", type="primary", key=f"search_evidence_{index}"):
        state.reset_downstream(after_step=4)
        query = quote_item_query(item)
        with st.status("공개 가격근거를 검색하고 있습니다...", expanded=True) as status_box:
            status_box.write("검증된 직접가격 source를 검색합니다.")
            run = search_all(query, build_collectors(g2b_lookback_days=state.lookback_days))
            state.search_runs[index] = run
            g2b_status = next(
                (
                    source_status
                    for source_status in run.source_statuses
                    if source_status.source_name == SOURCE_NAME
                ),
                None,
            )
            research_needed = bool(
                g2b_status is not None
                and (
                    g2b_status.skipped
                    or (g2b_status.succeeded and g2b_status.result_count == 0)
                )
            )
            discovery = None
            if research_needed and g2b_enabled and query.product_name.strip():
                status_box.write(
                    "직접가격이 없거나 mapping이 없어 Research Layer에서 관련 후보를 확장 탐색합니다."
                )
                discovery = discover_unmapped_g2b_candidates(
                    query,
                    service_key=(settings.resolved_g2b_service_key or "").strip(),
                    lookback_days=state.lookback_days,
                    base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                    timeout_seconds=settings.g2b_request_timeout_seconds,
                    max_retries=settings.g2b_max_retries,
                    pages_per_term_window=2,
                )
            state.discoveries[index] = discovery
            status_box.update(
                label=f"검색 완료 · 검증근거 {len(run.results)}건",
                state="complete",
                expanded=False,
            )

    run = state.search_runs.get(index)
    if run is None:
        st.info("검색을 실행하면 출처별 완료상태와 근거가 이곳에 표시됩니다.")
        return

    st.markdown("**출처별 검색상태**")
    render_source_status(run)
    failed = [source for source in run.source_statuses if not source.succeeded and not source.skipped]
    if failed:
        st.error(
            "수집 미완료: "
            + ", ".join(source.source_name for source in failed)
            + ". 현재 근거는 성공한 출처만의 부분 결과입니다."
        )
    if run.errors:
        st.warning(" / ".join(run.errors))

    if run.results:
        st.markdown("**관측가격 범위 — 출처·VAT별 분리**")
        render_observation_cards(run.results)
        st.markdown("**검증 가격근거**")
        render_evidence_table(run.results)
    else:
        st.warning("검증된 직접 가격근거를 확보하지 못했습니다.")

    discovery = state.discoveries.get(index)
    if discovery is not None:
        st.markdown("**나라장터 Research 후보 — 판정 미포함**")
        render_discovery_candidates(discovery)

    allowed, reasons = can_enter(5, state)
    for reason in reasons:
        st.info(reason)
    if st.button("5. 조건 대조로", type="primary", disabled=not allowed):
        state.step = 5
        st.rerun()
