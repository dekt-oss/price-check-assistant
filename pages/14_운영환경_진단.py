from __future__ import annotations

import streamlit as st

from purchase_price.services.g2b_market_models import G2BResearchSource
from purchase_price.services.live_smoke import (
    LIVE_FAILURE,
    LIVE_INVALID,
    LIVE_NOT_AUTHORIZED,
    LIVE_NOT_READY,
    LIVE_SUCCESS,
    LIVE_SUCCESS_0,
    result_from_public_dict,
    run_g2b_live_smoke,
    run_g2b_research_live_smoke,
    run_mfds_business_live_smoke,
    run_mfds_model_live_smoke,
)
from purchase_price.services.runtime_readiness import runtime_readiness

st.set_page_config(page_title="운영환경 진단", page_icon="🩺", layout="wide")
st.title("운영환경 진단")
st.caption(
    "Secret 값이나 견적 원문을 표시하지 않고 실제 배포환경의 API/OCR 준비상태를 확인합니다. "
    "페이지를 여는 것만으로 외부 API를 호출하지 않습니다."
)
checks = runtime_readiness()
check_by_key = {check.key: check for check in checks}
for start in range(0, len(checks), 4):
    row = checks[start : start + 4]
    columns = st.columns(len(row))
    for column, check in zip(columns, row, strict=True):
        with column:
            st.subheader(check.label)
            if check.ready:
                st.success("READY")
            else:
                st.warning("UNAVAILABLE")
            st.caption(check.detail)
st.info(
    "READY는 Secret 설정 여부일 뿐 해당 서비스 활용신청 승인이나 실제 API 성공을 뜻하지 않습니다. "
    "아래 live smoke는 제출 버튼을 누를 때만 공식 API를 호출합니다. "
    "Research smoke는 입찰·낙찰·사전규격 각각 논리 요청 1회로 제한합니다."
)


def _render_live_result(session_key: str) -> None:
    payload = st.session_state.get(session_key)
    if not isinstance(payload, dict):
        return
    result = result_from_public_dict(payload)
    if result.status == LIVE_SUCCESS:
        st.success("성공 — 조회 결과 있음")
    elif result.status == LIVE_SUCCESS_0:
        st.info("성공 — 정상 응답, 조회 결과 0건")
    elif result.status == LIVE_NOT_AUTHORIZED:
        st.error("인증/활용신청 미승인 — 검색 결과 0건이 아닙니다")
    elif result.status == LIVE_FAILURE:
        st.error("실패 — 외부 API 요청 오류")
    elif result.status in {LIVE_NOT_READY, LIVE_INVALID}:
        st.warning("미실행")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("응답 품목", "-" if result.record_count is None else result.record_count)
    m2.metric("전체 건수", "-" if result.total_count is None else result.total_count)
    m3.metric("응답시간", f"{result.elapsed_ms:.0f} ms")
    request_budget = (
        "-"
        if result.logical_requests == 0
        else f"{result.logical_requests} / 최대 {result.max_http_attempts} HTTP"
    )
    m4.metric("요청 예산", request_budget)
    st.caption(result.detail)
    if result.credential_source:
        st.caption(f"선택된 Secret 변수: `{result.credential_source}` (값은 표시하지 않음)")


st.divider()
st.markdown("## 수동 live smoke")
g2b_shopping_ready = check_by_key["g2b_credential"].ready
g2b_research_ready = check_by_key["g2b_research_credential"].ready
mfds_ready = check_by_key["mfds_credential"].ready

with st.container(border=True):
    st.markdown("### 1. G2B Shopping")
    with st.form("g2b_live_smoke_form"):
        g2b_name = st.text_input("나라장터 세부품명", value="제습기")
        lookback_days = st.selectbox(
            "조회기간",
            options=[30, 90, 180, 365],
            format_func=lambda value: f"최근 {value}일",
        )
        g2b_submit = st.form_submit_button(
            "G2B Shopping live smoke 실행",
            disabled=not g2b_shopping_ready,
            type="primary",
        )
    if g2b_submit:
        st.session_state["g2b_live_smoke_result"] = run_g2b_live_smoke(
            g2b_name, lookback_days=lookback_days
        ).to_public_dict()
    _render_live_result("g2b_live_smoke_result")

with st.container(border=True):
    st.markdown("### 2. G2B Research — 입찰·낙찰·사전규격")
    st.caption(
        "Production에서 보였던 HTTP 403/code=30과 정상 0건을 분리하기 위한 진단입니다. "
        "세 API는 같은 Research credential family를 사용하되 서비스별 승인상태를 각각 확인합니다."
    )
    with st.form("g2b_research_live_smoke_form"):
        research_keyword = st.text_input("Research 검색어", value="마취")
        research_submit = st.form_submit_button(
            "G2B Research 3종 live smoke 실행",
            disabled=not g2b_research_ready,
            type="primary",
        )
    if research_submit:
        for source, session_key in (
            (G2BResearchSource.BID_NOTICE, "g2b_research_bid_smoke"),
            (G2BResearchSource.AWARD, "g2b_research_award_smoke"),
            (G2BResearchSource.PRESPEC, "g2b_research_prespec_smoke"),
        ):
            st.session_state[session_key] = run_g2b_research_live_smoke(
                source, research_keyword
            ).to_public_dict()

    cols = st.columns(3)
    for column, title, session_key in zip(
        cols,
        ("입찰공고", "낙찰", "사전규격"),
        (
            "g2b_research_bid_smoke",
            "g2b_research_award_smoke",
            "g2b_research_prespec_smoke",
        ),
        strict=True,
    ):
        with column:
            st.markdown(f"**{title}**")
            _render_live_result(session_key)

with st.container(border=True):
    st.markdown("### 3. MFDS 품목/모델")
    with st.form("mfds_model_live_smoke_form"):
        mfds_product_name = st.text_input("식약처 공식 품목명", value="인공호흡기")
        mfds_model_submit = st.form_submit_button(
            "MFDS 품목/모델 live smoke 실행", disabled=not mfds_ready
        )
    if mfds_model_submit:
        st.session_state["mfds_model_live_smoke_result"] = run_mfds_model_live_smoke(
            mfds_product_name
        ).to_public_dict()
    _render_live_result("mfds_model_live_smoke_result")

with st.container(border=True):
    st.markdown("### 4. MFDS 업체")
    with st.form("mfds_business_live_smoke_form"):
        mfds_company_name = st.text_input(
            "업체명", placeholder="검증할 의료기기 업체명을 입력하세요"
        )
        mfds_business_submit = st.form_submit_button(
            "MFDS 업체 live smoke 실행", disabled=not mfds_ready
        )
    if mfds_business_submit:
        st.session_state["mfds_business_live_smoke_result"] = run_mfds_business_live_smoke(
            mfds_company_name
        ).to_public_dict()
    _render_live_result("mfds_business_live_smoke_result")

st.caption(
    "live smoke는 연결성/권한 진단입니다. 결과를 가격판정, exact identity, 공식 총판 여부 또는 안전성으로 자동 승격하지 않습니다. "
    "service key 값과 raw API payload는 표시하지 않습니다."
)
