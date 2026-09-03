import streamlit as st

st.set_page_config(page_title="구매가격 검색·검토 보조시스템", page_icon="🔎", layout="wide")

st.title("구매가격 검색·검토 보조시스템")
st.caption("공개정보 기반 PoC · 구매결정이 아닌 구매검토 보조도구")

st.info(
    "현재 단계는 Phase 0~1 초기 구현입니다. 실제 시장가격 수집기는 아직 연결하지 않았으며, "
    "검색 흐름 검증용 샘플 수집기만 포함됩니다."
)

st.markdown("### 시작하기")
st.page_link("pages/1_통합검색.py", label="제품명 / 제조사 / 모델 / 규격으로 검색")
st.page_link("pages/2_견적서_분석.py", label="견적서 업로드 (초기 골격)")
st.page_link("pages/3_Phase0_검증.py", label="Phase 0 대표품목 데이터 가능성 검증")

st.markdown("---")
st.markdown(
    "**운영 원칙:** 출처·수집일·비교등급을 함께 제시하고, 근거 부족 시 임의의 적정가격을 만들지 않습니다."
)
