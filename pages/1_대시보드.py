from __future__ import annotations

from decimal import Decimal, InvalidOperation

import streamlit as st

from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.track_b_r2_quote_index import lookup_track_b_quote_from_r2
from purchase_price.ui.market_research import (
    render_market_reference_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STATE_SESSION_KEY,
    QuoteReviewState,
)
from purchase_price.ui.quote_review_steps import _store_extraction
from purchase_price.ui.track_b_transactions import (
    candidate_counts,
    has_transaction_candidates,
    transaction_rows,
)
from purchase_price.ui.widgets import (
    evidence_rows,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

st.set_page_config(page_title="구매가격 검색", page_icon="🔎", layout="wide")

st.markdown(
    """
<style>
.block-container {max-width: 1180px; padding-top: 2.2rem;}
[data-testid="stForm"] {border: 0; padding: 0;}
[data-testid="stFileUploader"] {margin-top: 0.2rem;}
.home-kicker {text-align:center; color:#6b7280; font-size:0.95rem; margin-bottom:0.15rem;}
.home-title {text-align:center; font-size:2.35rem; font-weight:750; margin:0.2rem 0 0.35rem 0;}
.home-subtitle {text-align:center; color:#6b7280; margin-bottom:1.6rem;}
.home-section {margin-top:1.15rem;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="home-kicker">공개 조달·시장근거 기반 구매검토</div>', unsafe_allow_html=True)
st.markdown('<div class="home-title">무엇을 조사할까요?</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="home-subtitle">품목이나 모델명을 입력하면 가격·판매처·구매처·거래이력을 바로 찾습니다.</div>',
    unsafe_allow_html=True,
)

with st.form("home_unified_search"):
    search_col, button_col = st.columns([8, 1.35], gap="small")
    with search_col:
        search_text = st.text_input(
            "통합 검색",
            placeholder="품목 또는 모델명  예) FLOW-C, Veriti Pro Dx, 가스마취기",
            label_visibility="collapsed",
        )
    with button_col:
        submitted = st.form_submit_button("검색", type="primary", use_container_width=True)

    with st.expander("상세 검색조건", expanded=False):
        a1, a2 = st.columns(2)
        product_name = a1.text_input("품명", placeholder="예: 가스마취기")
        manufacturer = a2.text_input("제조사", placeholder="예: Getinge / Maquet")
        model_name = a1.text_input("모델명", placeholder="예: FLOW-C")
        specification = a2.text_input("규격", placeholder="선택")
        quote_text = a1.text_input("현재 견적 단가", placeholder="선택 · 예: 66000000")
        lookback_days = a2.selectbox(
            "나라장터 검색기간",
            options=G2B_LOOKBACK_OPTIONS,
            index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
            format_func=g2b_lookback_label,
        )

st.markdown('<div class="home-section"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown("**견적서로 바로 시작**")
    st.caption("PDF · Excel · 이미지 견적서를 올리면 품목을 추출하고 같은 형식으로 거래가격을 찾습니다.")
    uploaded = st.file_uploader(
        "견적서 업로드",
        type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
        label_visibility="collapsed",
        key="home_quote_upload",
    )

if uploaded is not None:
    if QUOTE_REVIEW_STATE_SESSION_KEY not in st.session_state:
        st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY] = QuoteReviewState()
    quote_state: QuoteReviewState = st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY]
    if quote_state.file_name != uploaded.name or quote_state.extraction is None:
        with st.spinner("견적서에서 품목을 추출하고 있습니다..."):
            _store_extraction(uploaded, quote_state)
    st.switch_page("pages/2_견적_검토.py")

if submitted:
    raw_search = search_text.strip()
    resolved_model = model_name.strip()
    resolved_product = product_name.strip() or raw_search
    if not resolved_product and not resolved_model and not manufacturer.strip() and not specification.strip():
        st.warning("품목 또는 모델명을 입력하세요.")
        st.stop()

    quote = None
    if quote_text.strip():
        try:
            quote = Decimal(quote_text.replace(",", "").strip())
        except InvalidOperation:
            st.error("견적 단가는 숫자로 입력하세요.")
            st.stop()

    review_input = build_purchase_review_input(
        product_name=resolved_product,
        manufacturer=manufacturer,
        model_name=resolved_model,
        specification=specification,
        quote_unit_price=quote,
    )
    if review_input is None:
        st.warning("검색조건을 확인하세요.")
        st.stop()
    query = review_input.to_product_query()

    st.divider()
    heading = resolved_model or resolved_product or raw_search
    st.subheader(f"{heading} 거래가격")

    track_b = lookup_track_b_quote_from_r2(query, quote_unit_price=review_input.quote_unit_price)
    model_probe_used = False
    if (
        raw_search
        and not model_name.strip()
        and not product_name.strip()
        and track_b.status == "success_0"
    ):
        model_probe_input = build_purchase_review_input(
            product_name=raw_search,
            manufacturer=manufacturer,
            model_name=raw_search,
            specification=specification,
            quote_unit_price=quote,
        )
        if model_probe_input is not None:
            model_probe_query = model_probe_input.to_product_query()
            model_probe = lookup_track_b_quote_from_r2(
                model_probe_query,
                quote_unit_price=model_probe_input.quote_unit_price,
            )
            if has_transaction_candidates(model_probe):
                track_b = model_probe
                query = model_probe_query
                model_probe_used = True

    rows = transaction_rows(track_b)
    strict_count, reference_count = candidate_counts(track_b)
    with st.container(border=True):
        st.markdown("**나라장터 거래가격**")
        if model_probe_used:
            st.caption("입력어가 모델명과 일치해 모델 기준 결과를 우선 표시합니다.")
        if rows:
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={"가격": st.column_config.NumberColumn("가격", format="%d원")},
            )
            st.caption(f"동일성 확인 {strict_count}건 · 검색 참고 {reference_count}건")
        elif track_b.status == "unavailable":
            st.info("가격 검색 인덱스를 준비 중입니다. 공개 시장자료도 함께 조사합니다.")
        elif track_b.status == "not_ingested":
            st.info("수집 자료의 빠른 가격 인덱스를 만드는 중입니다.")
        elif track_b.status == "insufficient_identity":
            st.info("품목 또는 모델명을 입력하세요.")
        else:
            st.info("현재 수집 범위에서 거래가격을 찾지 못했습니다. 공개 시장자료를 추가 조사합니다.")

    with st.status("공개 시장자료를 추가 확인하고 있습니다...", expanded=False) as status:
        run, discovery, market_bundle = run_market_research(
            query,
            lookback_days=int(lookback_days),
            research_pages_per_term=1,
            research_request_budget=18,
            procurement_detail_limit=4,
        )
        status.update(label="추가 자료 확인 완료", state="complete")

    if not rows and run.results:
        public_rows = evidence_rows(run.results)
        st.markdown("**공개 시장가격**")
        st.dataframe(
            [
                {
                    "가격": row["단가"],
                    "출처": row["출처"],
                    "거래일": row["거래일"] or "미확인",
                    "자료성격": row["자료성격"],
                    "URL": row["URL"],
                }
                for row in public_rows
            ],
            use_container_width=True,
            hide_index=True,
            column_config={"가격": st.column_config.NumberColumn("가격", format="%d원")},
        )

    show_details = st.toggle("상세 조사·근거 보기", value=False, key="home_search_details")
    if show_details:
        render_market_reference_summary(
            discovery,
            query=query,
            quote_unit_price=review_input.quote_unit_price,
        )
        render_procurement_research(market_bundle)
        render_source_status(run)
        if run.results:
            assessment = assess_prices(run.results, review_input.quote_unit_price)
            m1, m2, m3 = st.columns(3)
            m1.metric("직접가격 근거", f"{assessment.observed_count}건")
            m2.metric("독립 출처", f"{assessment.source_count}개")
            m3.metric("근거 신뢰도", assessment.confidence)
            render_observation_cards(run.results)
            render_evidence_table(run.results)
        else:
            st.caption("엄격한 동일제품 직접가격은 현재 조사 범위에서 확인되지 않았습니다.")

st.caption(
    "검색 참고 가격은 실제 관측값이지만 동일제품으로 확정된 가격은 아닙니다. "
    "모델·규격·VAT·설치·옵션 조건이 확인된 경우에만 직접 비교합니다."
)
