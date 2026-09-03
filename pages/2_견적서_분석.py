import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="견적서 분석", page_icon="📄", layout="wide")
st.title("견적서 분석")
st.caption("Phase 4 기능의 초기 안전 골격입니다. 업로드 파일은 영구 저장하지 않습니다.")

uploaded = st.file_uploader("PDF 또는 Excel 견적서", type=["pdf", "xlsx", "xls"])
if uploaded is not None:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        tmp.flush()
        st.success(f"{uploaded.name} 파일을 임시 영역에서 수신했습니다.")
        st.info(
            "아직 문서추출 엔진은 연결하지 않았습니다. 다음 구현에서 PDF/Excel 구조 추출 → 품목 표준화 → "
            "외부 가격검색 순으로 연결합니다."
        )
