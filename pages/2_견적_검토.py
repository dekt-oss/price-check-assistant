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
    "견적서를 한 번 업로드하면 품목 추출과 시장조사를 바로 실행하고 결과를 한 화면에서 보여줍니다. "
    "동일제품 직접비교나 최종 승인·판정이 필요할 때만 아래 상세 검증을 진행합니다."
)

render_quote_market_research(state)

if state.extraction is not None:
    st.divider()
    st.subheader("상세 검증·최종 판정")
    st.caption(
        "위 시장조사는 검증 완료를 기다리지 않고 넓게 수행합니다. 여기서는 원문 확인, 제품 식별, "
        "거래조건 대조와 담당자 pair 승인 등 기존 안전 게이트만 필요할 때 이어서 진행합니다."
    )

    if not state.items:
        st.info(
            "자동 추출 품목이 없으면 위의 같은 화면에서 품목을 직접 입력하세요. "
            "품목이 생기면 시장조사가 즉시 실행되고 상세 검증도 이어서 사용할 수 있습니다."
        )
    else:
        if state.step < 2:
            state.step = 2

        with st.expander("원문 확인 · 제품 식별 · 조건 대조 · 승인", expanded=False):
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
