# ruff: noqa: E402  (imports follow the stale-module refresh below)
import importlib
import sys

import streamlit as st

# A Streamlit process that started before a deploy keeps the old copies of imported modules (the
# page file updates, its imports do not). Reload the ones whose wording or table changed, in
# dependency order, before this page imports names from them.
_UI_RUNTIME_MARKERS = (
    ("purchase_price.services.quote_upload_security", "QUOTE_UPLOAD_IMAGES_V1"),
    ("purchase_price.ui.track_b_transactions", "ENTRY_ERRORS_EXCLUDED_V1"),
    ("purchase_price.ui.quote_review_layout", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_item_intelligence", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_review_summary", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_review_steps", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_review_s4", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_review_s5_s6", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_market_research", "QUOTE_REVIEW_ACCEPTANCE_V3"),
    ("purchase_price.ui.quote_market_research", "HANDOFF_SOURCE_V1"),
    ("purchase_price.ui.quote_review_layout", "QUOTE_REVIEW_IDENTITY_V1"),
    ("purchase_price.ui.quote_market_research", "QUOTE_REVIEW_IDENTITY_V1"),
    # 입력 오류 의심 trades are left out of the median: reload in dependency order.
    ("purchase_price.ui.quote_review_layout", "QUOTE_REVIEW_ENTRY_ERRORS_V1"),
    ("purchase_price.ui.quote_item_intelligence", "QUOTE_REVIEW_ENTRY_ERRORS_V1"),
    ("purchase_price.ui.quote_review_summary", "QUOTE_REVIEW_ENTRY_ERRORS_V1"),
    ("purchase_price.ui.quote_market_research", "QUOTE_REVIEW_ENTRY_ERRORS_V1"),
    # The per-item status row became wrapping cards (no "…" cut-off).
    ("purchase_price.ui.track_b_transactions", "QUANTITY_COMMAS_V1"),
    ("purchase_price.ui.product_identity", "PRODUCT_IDENTITY_V2"),
    ("purchase_price.ui.quote_review_layout", "QUOTE_REVIEW_CARD_WRAP_V1"),
    ("purchase_price.ui.quote_review_steps", "QUOTE_REVIEW_MFDS_INDEX_V1"),
    ("purchase_price.ui.quote_item_intelligence", "QUOTE_REVIEW_ITEM_STATUS_V1"),
    ("purchase_price.ui.quote_market_research", "QUOTE_REVIEW_ITEM_STATUS_V1"),
)


def _refresh_ui_modules() -> None:
    """Reload retained pre-deploy copies once; never raises."""

    for name, marker in _UI_RUNTIME_MARKERS:
        module = sys.modules.get(name)
        if module is None or hasattr(module, marker):
            continue
        try:
            importlib.invalidate_caches()
            importlib.reload(module)
        except Exception:
            pass


_refresh_ui_modules()

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
DETAIL_EXPANDER_LABEL = "상세 검증 (선택) · 원문 확인 · 조건 대조 · 승인"
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
            "꼭 거칠 필요는 없습니다. 위 비교표의 판정은 이 단계 없이도 볼 수 있습니다. 결재 문서에 근거를 "
            "남겨야 할 때처럼 더 꼼꼼히 확인하고 싶을 때, 견적서 원문과 품목을 맞춰 보고 부가세·설치·보증 같은 "
            "거래 조건이 같은지 따져 담당자가 비교할 거래를 하나씩 승인합니다."
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
                    "거래 조건을 확인하지 못했거나 서로 맞지 않는 가격 자료는 승인에서 빠지고 참고용으로만 남습니다. "
                    "담당자가 같은 조건임을 직접 확인해 승인한 가격 자료만 이 단계의 견적 위치 계산에 씁니다."
                )
                render_s6(state, selected_index)
        with right:
            render_path_card(state)
