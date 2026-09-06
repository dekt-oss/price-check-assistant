import streamlit as st

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
st.caption(
    "업로드 → 품목 확인 → 제품 식별 → 근거 수집 → 조건 대조 → 승인·판정을 한 화면에서 진행합니다."
)
render_stepper(state)

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
        render_s5(state, selected_index)
    else:
        render_s6(state, selected_index)
with right:
    render_path_card(state)
