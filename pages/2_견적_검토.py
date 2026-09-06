import streamlit as st

from purchase_price.ui.quote_market_research import render_quote_market_research
from purchase_price.ui.quote_review_s4 import render_s4
from purchase_price.ui.quote_review_s5_s6 import render_s5, render_s6
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STATE_SESSION_KEY,
    QuoteReviewState,
)
from purchase_price.ui.quote_review_steps import (
    render_item_list,
    render_path_card,
    render_s1,
    render_s2,
    render_s3,
    render_stepper,
)

st.set_page_config(page_title="견적 검토", page_icon="📋", layout="wide")

if QUOTE_REVIEW_STATE_SESSION_KEY not in st.session_state:
    st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY] = QuoteReviewState()
state: QuoteReviewState = st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY]

st.title("견적 검토")
st.caption("기본은 견적서 업로드만으로 품목별 시장가격을 자동 조사합니다. 정밀 조건대조·승인판정은 필요할 때만 선택합니다.")

mode = st.radio(
    "검토 방식",
    options=("자동 시장가격 조사", "정밀 비교검토"),
    horizontal=True,
    label_visibility="collapsed",
    key="quote_review_mode",
)

if mode == "자동 시장가격 조사":
    render_quote_market_research(state)
else:
    st.caption(
        "정밀 비교검토는 동일제품 직접비교와 최종 승인판정이 필요한 경우에 사용합니다. "
        "언제든 이전 단계로 돌아갈 수 있습니다."
    )
    render_stepper(state)

    nav_left, nav_right = st.columns([1, 5])
    with nav_left:
        if state.step > 1 and st.button("← 이전 단계", key="quote_review_back"):
            state.step -= 1
            st.rerun()
    with nav_right:
        st.caption(f"현재 단계 {state.step}/6")

    left, center, right = st.columns([0.9, 2.4, 1.1], gap="small")
    with left:
        selected_index = render_item_list(state)
    with center:
        if state.step == 1:
            render_s1(state)
        elif state.step == 2:
            render_s2(state, selected_index)
        elif state.step == 3:
            render_s3(state, selected_index)
        elif state.step == 4:
            render_s4(state, selected_index)
        elif state.step == 5:
            if st.button("품목·견적 조건 수정으로 돌아가기"):
                state.step = 2
                st.rerun()
            render_s5(state, selected_index)
        else:
            st.info(
                "조건이 미확인이거나 충돌인 근거는 최종 승인·판정에서는 제외되지만, "
                "시장조사 참고자료 자체는 자동 조사 화면에서 계속 확인할 수 있습니다."
            )
            render_s6(state, selected_index)
    with right:
        render_path_card(state)
