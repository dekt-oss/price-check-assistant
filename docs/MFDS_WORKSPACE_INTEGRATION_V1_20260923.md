# MFDS Workspace Integration V1 — 2026-09-23

## 목표

통합 구매조사 워크스페이스에서 의료기기 검색 시 가격과 별도로 식약처 공식 등록 identity와 동일품목 등록모델을 자동 확인한다.

## 공식 Source 계약

### 의료기기 형명정보

- Source: https://www.data.go.kr/data/15073899/openapi.do
- operation: `getMdeqModlInq01`
- 공식 서버 검색필드: `PRDLST_NM` 품목명
- `INDT_NM` 의미: **업종**
- 주요 결과: 허가번호, 품목명, 허가일, 취소/취하, 상품명, 형명, 수출전용 여부

중요:
`INDT_NM`은 업체명이 아니다.

### 업체명이 포함된 공식 Source

- 의료기기 표준코드별 제품정보
  - https://www.data.go.kr/data/15073875/openapi.do
- 의료기기 UDI/EDI 정보 조회 서비스
  - https://www.data.go.kr/data/15138675/openapi.do

공개 설명상 제조·수입 업체명, 모델, 허가번호 등을 포함한다.

현재 접근 가능한 공개 명세에서 모델명 기반 역검색 request contract를 확정하지 못했으므로
임의 파라미터를 만들지 않는다.

---

## V1 자동조회 gate

식약처 조회는 다음 경우에만 자동 실행한다.

1. Track B 거래/참고 근거의 세부품명번호가 `42...`
2. 또는 verified G2B mapping의 세부품명번호가 `42...`

이 gate는 '의료기기일 가능성이 높아 MFDS를 조회할지'만 결정한다.

공식 MFDS identity는 별도로:

- 공식 품목명 조회
- 결과 내 exact-normalized 모델 일치

를 통과해야 한다.

---

## V1 화면

### 식약처·업체

표시:

- 조회된 등록모델 수
- 국내 정상 후보 수
- exact 모델 확인 상태
- 허가번호
- 허가일
- 업종
- 취소/취하
- 수출전용

업체/제조사 힌트가 사용자 또는 견적에 있으면 별도 업허가 API로 교차확인한다.

단:

`업허가 존재 = 해당 모델의 공식 제조사/수입사/총판`

으로 해석하지 않는다.

### 경쟁장비

동일 공식 품목 조회 결과 중:

- 취소·취하 아님
- 수출전용 아님
- 입력 exact 모델 제외

인 등록모델만 표시한다.

라벨은:

`동일 식약처 품목 등록장비`

로 한다.

임상적 대체 가능성, 성능 동등성, 급여/수가 동등성은 자동 판단하지 않는다.

---

## 등록업체 기능 상태

현재 상태:

`company_source_not_connected`

이유:

형명정보 API에는 업체명 필드가 없고,
업체명이 포함된 UDI/제품정보 Source의 모델 역검색 request contract를 아직 공식적으로 고정하지 못했다.

따라서 0개 업체라고 표시하지 않는다.

후속 완료조건:

1. 공식 operation/base URL 확인
2. 모델 또는 허가번호 기반 request filter 공식 검증
3. live response field 고정
4. exact 모델/허가 identity와 company record 연결
5. 업체별 활성 등록모델 수/허가건수/최근허가일 집계

---

## 장애 처리

- 서비스키 없음: `not_configured`
- 의료기기 자동조회 대상 아님: `not_applicable`
- 정상 API 0건: `success_0`
- API 오류/timeout: `failure`

`failure`를 등록 0건으로 바꾸지 않는다.

MFDS 실패는 나라장터 가격검색 전체를 실패시키지 않는다.

---

## Safety

V1의 허가 identity 결과에서 permit number를 Safety 공식 확인키로 노출한다.

회수·판매중지 자동 adapter가 연결되기 전까지:

- 경고 없음 = 안전함

으로 표현하지 않는다.
