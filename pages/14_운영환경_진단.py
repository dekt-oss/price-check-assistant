from __future__ import annotations

import streamlit as st

from purchase_price.services.runtime_readiness import runtime_readiness

st.set_page_config(page_title="운영환경 진단", page_icon="🩺", layout="wide")
st.title("운영환경 진단")
st.caption(
    "Secret 값이나 견적 원문을 표시하지 않고 현재 실행환경의 live API/OCR 준비상태만 확인합니다. "
    "이 화면은 외부 API를 호출하지 않습니다."
)

checks = runtime_readiness()
columns = st.columns(len(checks))
for column, check in zip(columns, checks, strict=True):
    with column:
        st.subheader(check.label)
        if check.ready:
            st.success("READY")
        else:
            st.warning("UNAVAILABLE")
        st.caption(check.detail)

st.divider()
st.markdown("### 해석")
st.write(
    "- **G2B/MFDS READY**: 해당 source가 사용할 수 있는 service key가 설정돼 있다는 뜻입니다. "
    "key 값은 표시하지 않습니다.\n"
    "- **PDF 로컬 OCR READY**: Python OCR 모듈, Tesseract 실행파일, `kor`/`eng` language pack이 "
    "현재 런타임에서 확인됐다는 뜻입니다.\n"
    "- 이 페이지는 실제 G2B/MFDS 요청을 보내거나 견적 PDF를 OCR하지 않습니다."
)

st.info(
    "READY는 '실행 준비됨'을 뜻하며 실제 API 성공·검색결과 존재·실제 스캔 견적 OCR 정확도를 "
    "증명하지 않습니다. 실제 live smoke와 원문대조 UAT는 별도로 수행해야 합니다."
)

with st.expander("Secret/개인정보 비노출 원칙", expanded=False):
    st.write(
        "- service key 값은 화면에 출력하지 않습니다.\n"
        "- 어떤 실제 견적 파일도 이 진단에서 읽지 않습니다.\n"
        "- 외부 API 호출을 자동 실행하지 않습니다.\n"
        "- API 실패와 정상 0건은 실제 live smoke에서 별도로 구분합니다."
    )
