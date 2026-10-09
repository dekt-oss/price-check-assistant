import streamlit as st

from purchase_price.ui.quote_market_research import (
    SELECTED_ITEM_SESSION_KEY,
    render_quote_market_research,
)
from purchase_price.ui.quote_review_s4 import render_s4
from purchase_price.ui.quote_review_s5_s6 import render_s5, render_s6
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STATE_SESSION_KEY,
    QuoteReviewState,
)
from purchase_price.ui.quote_review_steps import (
    render_item_list,
    render_path_card,
    render_s2,
    render_s3,
    render_stepper,
)
from purchase_price.ui.theme import page_header_html

PAGE_TITLE = "견적서 검토"
DETAIL_EXPANDER_LABEL = "상세 검증 · 원문 확인 · 제품 식별 · 조건 대조 · 승인"
DETAIL_SYNCED_ITEM_KEY = "quote_review_detail_synced_item_v1"

st.set_page_config(page_title=PAGE_TITLE, page_icon="📋", layout="wide")

if QUOTE_REVIEW_STATE_SESSION_KEY not in st.session_state:
    st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY] = QuoteReviewState()
state: QuoteReviewState = st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY]

st.markdown(
    page_header_html(
        PAGE_TITLE,
        subtitle="견적서를 올리면 품목마다 나라장터에서 같은 제품이 거래된 가격과 견적 단가를 나란히 비교합니다.",
    ),
    unsafe_allow_html=True,
)

render_quote_market_research(state)

# 상세 검증·최종 판정: the older step-by-step review stays available, folded at the bottom.
if state.extraction is not None and state.items:
    if state.step < 2:
        state.step = 2

    # Open the step-by-step review on the item chosen in the table above.
    main_selected = st.session_state.get(SELECTED_ITEM_SESSION_KEY, 0)
    if st.session_state.get(DETAIL_SYNCED_ITEM_KEY) != main_selected and 0 <= main_selected < len(state.items):
        st.session_state["quote_review_item_selector"] = main_selected
        st.session_state[DETAIL_SYNCED_ITEM_KEY] = main_selected

    with st.expander(DETAIL_EXPANDER_LABEL, expanded=False):
        st.caption(
            "결재 문서에 붙일 때만 필요합니다. 품목을 원문과 맞춰 보고, 제품을 확인하고, VAT·설치·보증 같은 "
            "거래 조건을 대조한 뒤 담당자가 비교 거래를 하나씩 승인합니다."
        )
        render_stepper(state)

        nav_left, nav_right = st.columns([1, 5])
        with nav_left:
            if state.step > 2 and st.button("← 이전 검증 단계", key="quote_review_back"):
                state.step -= 1
                st.rerun()
        with nav_right:
            st.caption(f"상세 검증 단계 {state.step}/6")

        left, center, right = st.columns([0.9, 2.4, 1.1], gap="small")
        with left:
            selected_index = render_item_list(state)
        with center:
            if state.step <= 2:
                render_s2(state, selected_index)
            elif state.step == 3:
                render_s3(state, selected_index)
            elif state.step == 4:
                render_s4(state, selected_index)
            elif state.step == 5:
                render_s5(state, selected_index)
            else:
                st.info(
                    "조건이 미확인이거나 충돌인 근거는 승인·판정에서 제외되며 참고용으로만 남습니다. "
                    "담당자가 동일 비교조건을 명시적으로 확인한 pair만 견적 위치 계산에 사용합니다."
                )
                render_s6(state, selected_index)
        with right:
            render_path_card(state)
