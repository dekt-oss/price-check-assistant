import streamlit as st

st.set_page_config(page_title="구매가격 검색·검토 보조시스템", page_icon="🔎", layout="wide")

st.title("구매가격 검색·검토 보조시스템")
st.caption("공개정보 기반 PoC · 구매결정이 아닌 구매검토 보조도구")

st.markdown(
    """
현재 PoC는 **견적서 품목 추출 → 공개가격 조사 → 나라장터 계약근거 → 의료기기 등록/경쟁장비/공급사 → Safety·UDI 확인** 흐름을
Streamlit 화면에서 확인할 수 있습니다. 공개근거가 부족하면 임의로 적정가격이나 대체장비를 만들지 않습니다.
    """
)

st.markdown("### 업무별 시작")
c1, c2 = st.columns(2)
with c1:
    st.page_link("pages/2_견적서_분석.py", label="📄 견적서 업로드 → 품목/단가 추출 → 가격 비교")
    st.page_link("pages/1_통합검색.py", label="🔎 제품명 / 제조사 / 모델 / 규격 직접 검색")
    st.page_link("pages/7_나라장터_계약근거.py", label="📑 나라장터 물품 계약근거 조회")
    st.page_link("pages/5_의료기기_안전_공급사.py", label="🛡️ 의료기기 Safety · 공급사 근거 확인")
with c2:
    st.page_link("pages/4_의료기기_시장조사.py", label="🏥 의료기기 등록·경쟁장비·공급사 시장조사")
    st.page_link("pages/6_의료기기_UDI.py", label="🏷️ 의료기기 UDI-DI 공식조회")
    st.page_link("pages/3_Phase0_검증.py", label="🧪 Phase 0 대표품목 데이터 가능성 검증")

st.markdown("### 현재 조사 Source")
st.markdown(
    """
- **나라장터 쇼핑/납품:** verified exact-model mapping이 있는 경우 실제 공개 구매/납품실적과 공급업체 근거 조회
- **나라장터 계약정보:** 품명·기간 기준 계약번호·계약기관·계약방법·상세원문 조회. 계약총액은 제품 단가로 자동 환산하지 않음
- **식약처 등록/업허가:** 동일 품목 등록모델과 의료기기 제조·수입·판매 등 업허가 상태 조회
- **식약처 UDI:** 알고 있는 UDI-DI를 공식 `UDIDI_CD` 필터로 exact 조회해 코드체계·업체정보 확인
- **식약처 Safety:** 회수·판매중지·행정처분·안전성서한 공식 확인 경로 제공. 자동 API 미연결 상태를 `안전`으로 해석하지 않음
- **제조사 공개가격:** 사람이 검증한 공식 공개가격 snapshot
- **웹:** 공급사/대체장비 보조 탐색. 반드시 `웹` 출처로 표시하며 공식근거보다 낮은 우선순위
    """
)

st.markdown("---")
st.markdown(
    "**운영 원칙:** 출처·수집일·제품동일성·비교범위를 함께 제시하고, 근거 부족 시 임의의 적정가격·대체장비·공식 공급사를 생성하지 않습니다."
)
