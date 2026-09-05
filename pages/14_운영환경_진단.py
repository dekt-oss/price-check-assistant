from __future__ import annotations

import streamlit as st

from purchase_price.services.live_smoke import (
    LIVE_FAILURE,
    LIVE_INVALID,
    LIVE_NOT_READY,
    LIVE_SUCCESS,
    LIVE_SUCCESS_0,
    result_from_public_dict,
    run_g2b_live_smoke,
    run_mfds_business_live_smoke,
    run_mfds_model_live_smoke,
)
from purchase_price.services.runtime_readiness import runtime_readiness

st.set_page_config(page_title="운영환경 진단", page_icon="🩺", layout="wide")
st.title("운영환경 진단")
st.caption("Secret 값이나 견적 원문을 표시하지 않고 실제 배포환경의 API/OCR 준비상태를 확인합니다. 페이지를 여는 것만으로 외부 API를 호출하지 않습니다.")
checks = runtime_readiness()
check_by_key = {check.key: check for check in checks}
columns = st.columns(len(checks))
for column, check in zip(columns, checks, strict=True):
    with column:
        st.subheader(check.label)
        st.success("READY") if check.ready else st.warning("UNAVAILABLE")
        st.caption(check.detail)
st.info("READY는 설치/인증 준비상태일 뿐 실제 API 성공이나 OCR 정확도를 뜻하지 않습니다. 아래 live smoke는 버튼을 누를 때만 공식 API에 bounded 1회 요청합니다.")


def _render_live_result(session_key: str) -> None:
    payload = st.session_state.get(session_key)
    if not isinstance(payload, dict):
        return
    result = result_from_public_dict(payload)
    if result.status == LIVE_SUCCESS:
        st.success("성공 — 조회 결과 있음")
    elif result.status == LIVE_SUCCESS_0:
        st.info("성공 — 정상 응답, 조회 결과 0건")
    elif result.status == LIVE_FAILURE:
        st.error("실패 — 외부 API 요청 오류")
    elif result.status in {LIVE_NOT_READY, LIVE_INVALID}:
        st.warning("미실행")
    m1, m2, m3 = st.columns(3)
    m1.metric("응답 품목", "-" if result.record_count is None else result.record_count)
    m2.metric("전체 건수", "-" if result.total_count is None else result.total_count)
    m3.metric("응답시간", f"{result.elapsed_ms:.0f} ms")
    st.caption(result.detail)


st.divider()
st.markdown("## 수동 live smoke")
g2b_ready = check_by_key["g2b_credential"].ready
mfds_ready = check_by_key["mfds_credential"].ready
with st.container(border=True):
    st.markdown("### 1. G2B Shopping")
    g2b_name = st.text_input("나라장터 세부품명", value="제습기", key="live_smoke_g2b_detail_product_name")
    lookback_days = st.selectbox("조회기간", options=[30, 90, 180, 365], format_func=lambda value: f"최근 {value}일", key="live_smoke_g2b_lookback_days")
    if st.button("G2B live smoke 실행", disabled=not g2b_ready, type="primary"):
        st.session_state["g2b_live_smoke_result"] = run_g2b_live_smoke(g2b_name, lookback_days=lookback_days).to_public_dict()
    _render_live_result("g2b_live_smoke_result")
with st.container(border=True):
    st.markdown("### 2. MFDS 품목/모델")
    mfds_product_name = st.text_input("식약처 공식 품목명", value="인공호흡기", key="live_smoke_mfds_product_name")
    if st.button("MFDS 품목/모델 live smoke 실행", disabled=not mfds_ready):
        st.session_state["mfds_model_live_smoke_result"] = run_mfds_model_live_smoke(mfds_product_name).to_public_dict()
    _render_live_result("mfds_model_live_smoke_result")
with st.container(border=True):
    st.markdown("### 3. MFDS 업체")
    mfds_company_name = st.text_input("업체명", placeholder="검증할 의료기기 업체명을 입력하세요", key="live_smoke_mfds_company_name")
    if st.button("MFDS 업체 live smoke 실행", disabled=not mfds_ready):
        st.session_state["mfds_business_live_smoke_result"] = run_mfds_business_live_smoke(mfds_company_name).to_public_dict()
    _render_live_result("mfds_business_live_smoke_result")
st.caption("live smoke는 연결성 진단입니다. 결과를 가격판정, exact identity, 공식 총판 여부 또는 안전성으로 자동 승격하지 않습니다. service key와 raw API payload는 표시하지 않습니다.")
