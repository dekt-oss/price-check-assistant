import streamlit as st

st.set_page_config(page_title="대시보드", page_icon="🏠", layout="wide")
st.title("구매가격 검색·검토 보조시스템")
st.caption("공개정보 기반 PoC · 구매결정이 아닌 구매검토 보조도구")

st.markdown("## 업무 시작")
c1, c2, c3 = st.columns(3)
with c1:
    with st.container(border=True):
        st.markdown("### 📋 견적 검토")
        st.write("견적 업로드부터 제품 식별, 근거 수집, 조건 대조, 승인·판정까지 한 화면에서 진행합니다.")
        st.page_link("pages/2_견적_검토.py", label="견적 검토 시작", use_container_width=True)
with c2:
    with st.container(border=True):
        st.markdown("### 🔎 빠른 검색")
        st.write("제품명·제조사·모델·규격으로 공개 가격근거와 나라장터 계약근거를 직접 조회합니다.")
        st.page_link("pages/3_빠른_검색.py", label="빠른 검색 열기", use_container_width=True)
with c3:
    with st.container(border=True):
        st.markdown("### 🏥 의료기기 조회")
        st.write("식약처 등록모델, 업허가·Safety 확인, UDI-DI 공식조회를 한 영역에서 확인합니다.")
        st.page_link("pages/4_의료기기_조회.py", label="의료기기 조회 열기", use_container_width=True)

st.markdown("## 검토 흐름")
st.markdown(
    """
1. **견적 업로드·품목 확인** — 자동 추출값은 반드시 원문과 대조합니다.
2. **제품 식별** — verified mapping 또는 명시적 조사요청, 의료기기는 MFDS exact identity를 확인합니다.
3. **공개 근거 수집** — 출처 실패·0건·미검증 후보를 직접가격과 분리합니다.
4. **조건 대조·승인** — 수량·단위·VAT·배송·설치·옵션·보증·유지보수·기준일을 대조합니다.
5. **견적 위치 확인** — 담당자가 승인한 동일조건 pair만 사용하며 구매 권고나 적정/부적정 판정은 하지 않습니다.
"""
)

st.markdown("## 현재 조사 Source")
st.markdown(
    """
- **나라장터 쇼핑/납품:** verified exact-model mapping이 있는 경우 공개 구매·납품실적 조회
- **나라장터 계약정보:** 계약번호·기관·계약방법·상세원문 확인. 계약총액은 제품 단가로 자동 환산하지 않음
- **식약처:** 등록모델·업허가·UDI 및 공식 Safety 확인 경로
- **제조사 공개가격:** 사람이 검증한 공식 공개가격 snapshot
- **웹:** 보조 탐색만 수행하며 공식근거보다 낮은 우선순위
"""
)

st.info(
    "근거가 부족하거나 조건이 다르면 판정을 보류합니다. 검색 실패와 검색 0건도 서로 다른 상태로 표시합니다."
)
