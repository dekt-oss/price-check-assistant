# MFDS 의료기기 시장조사 구현 상태

작성일: 2026-09-04

## 기준선

- base: `main`
- 시작 기준 commit: `3bc2c3c8ed93245c500f349f6335cf5e23540c8b`
- branch: `phase2/mfds-market-research-m2`

## M1 완료

- 식약처 형명정보 API adapter (`PRDLST_NM`)
- 식약처 의료기기 제조·수입업 허가정보 adapter (`Entrps`)
- 동일 식약처 품목 등록모델 표시
- 취소·취하/수출전용 후보 분리
- Streamlit `의료기기 시장조사` 페이지
- fixture 기반 CI

## 이번 M2 구현

상세 계약은 `docs/MFDS_MARKET_RESEARCH_M2.md`를 기준으로 한다.

### 완료

- 국내 정상 동일품목 후보가 있으면 해당 후보를 우선 표시
- 국내 정상 동일품목 후보가 **0건일 때만** 사용목적·주요사양 기반 보조 대체탐색을 제안
- 보조탐색은 `대체 가능 판정`이 아니라 추가 조사 후보로 표시
- 취소·취하/수출전용 모델은 정상 후보가 있으면 기본 숨김
- 정상 후보가 0건이면 `참고용 · 제외된 등록제품` expander로만 표시
- 취소·취하/수출전용 의미를 UI에서 설명
- 기존 G2B 가격근거의 `공급업체=` provenance에서 실제 공공조달 공급업체 후보 추출
- 공급사 화면 우선순위: `나라장터` → `식약처` → `웹`
- 일반 웹 공급사 탐색은 `웹`으로 명시하고 공식 총판으로 자동 승격 금지
- 공식 형명정보 API에 모델명 서버 filter가 없다는 계약을 UI/문서에 명시
- Home 화면을 현재 실제 기능에 맞게 갱신
- Streamlit Community Cloud 배포용 `requirements.txt`, `.streamlit/config.toml` 추가
- 웹 배포 runbook 추가

### 테스트

`tests/test_market_research_support.py`

- 나라장터 공급업체 explicit evidence만 추출
- 중복 업체 dedupe
- 0건에서만 대체탐색 gate 활성화
- 웹 링크는 반드시 `웹 ·` 라벨 사용

## 다음 구현

### exact model identity

- 의료기기 표준코드별 제품정보 API의 실제 request filter/live response 검증
- exact 모델 → UDI/품목명/분류번호/허가번호/제조·수입업체 자동 연결
- API가 지원하지 않는 모델 필터는 추정하지 않음

### Safety

- 의료기기 회수·판매중지 API의 실제 endpoint/request contract 검증
- exact 모델/허가번호 hit 시 가격보다 위에 큰 빨간 경고
- 품목 수준 정보는 exact 경고와 구분
- 식약처 안전성서한 공식근거 연결

### 공급시장 확대

- 식약처 제품에 연결된 제조·수입업체 자동 join
- G2B 계약정보까지 공급업체 evidence 확대
- 제조사 공식 파트너/총판 웹근거 adapter

### 견적서 통합

- XLSX에서 추출한 의료기기 행에 시장조사 바로가기/자동 연결
- 가격근거 + 등록장비 + 공급업체 + safety를 단일 구매검토 화면으로 통합

## 웹 배포 상태

코드 저장소는 Streamlit Community Cloud 배포 준비 상태다.

실제 `streamlit.app` URL을 만들려면 최초 1회 Streamlit Community Cloud 계정에서 GitHub OAuth로 public repository 접근 권한을 부여해야 한다. 서비스키는 GitHub에 커밋하지 않고 배포 Secrets로 주입한다.

## 검증 경계

- 사용목적/주요사양을 근거로 AI가 자동 대체품을 생성하지 않는다.
- 웹 검색결과 업체는 공식 공급업체로 확정하지 않는다.
- 회수·판매중지 endpoint는 공식 request contract 확인 전 추정 구현하지 않는다.
- 기존 가격 A/B/C/D/X 및 ComparisonScope 계약은 변경하지 않는다.
