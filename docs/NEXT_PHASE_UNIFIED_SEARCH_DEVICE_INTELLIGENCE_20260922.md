# 파일럿 다음 단계 — Unified Search V4 + 의료기기 Intelligence 통합

작성일: 2026-09-22

## 1. 목적

초기 기획의 최종 사용자 질문은 다음 다섯 가지다.

1. 이 물건이 무엇인지
2. 비교 가능한 가격자료가 어디에 있는지
3. 현재 견적이 비교자료에서 어느 수준인지
4. 가격 차이가 모델·규격·옵션 차이인지
5. 의료기기라면 등록업체·경쟁장비·안전정보가 무엇인지

현재 가격/R2 파이프라인은 파일럿 사용 단계에 도달했다. 다음 단계는 기능을 더 늘리는 것보다
**한 줄 검색 → 구조화된 제품 identity → 가격·조달·식약처 근거를 한 화면에 연결**하는 데 초점을 둔다.

---

## 2. 현재 운영상태

### Track B / R2

- Historical target: 5,208 codes
- Historical backfill: **5,208/5,208 완료**
- Historical fixed window: 2025-09-12 ~ 2026-09-11
- Rolling refresh first cycle: **900/5,208 codes 진행**
- 첫 rolling batch 관측: 165 rows
- serving 반영 후 pending: 0
- base schedule: 월/수/금 03:10 KST
- request budget: 900/run
- 정상 진행 시 첫 rolling cycle은 남은 4,308 codes를 5회에 나누어 처리한다.
- supplemental lane은 CX30N/4511181101 등 targeted gap 보완용으로 base state와 분리한다.

### 검색 품질

- curated UAT: 30
- observed-model regression: 24
- combined search UAT: 54
- curated unexpected delivery-index ZERO: 0
- exact sampled source-row recovery: 24/24

### 실제 Production 브라우저 감사에서 확인된 UX gap

- `ApeosPrint C5570 GK`: 한 줄 검색만으로 DIRECT A/B 정상
- `DFM100`: 한 줄 검색은 참고 2건이나 구조화 검색은 DIRECT 2건
- `ROTAPRO`: 한 줄 검색에서는 external Research basis가 약하지만 구조화 검색에서는 verified mapping + Research 정상
- `CX30N`: direct 0 / reference 25가 의도대로 fail-closed
- `MinION Mk1D`: unverified qualifier 때문에 reference-only 유지

따라서 현재 병목은 R2 데이터보다 **한 줄 검색의 identity 해석/UX orchestration**이다.

---

## 3. Unified Search V4

### 목표

사용자가 다음처럼 입력해도:

- `DFM100`
- `ROTAPRO`
- `필립스 Efficia DFM100 심장 충격기`

내부 query를 가능한 범위에서 다음처럼 구조화한다.

- 품명
- 제조사
- 모델
- 규격

### 안전 규칙

1. 사용자 상세입력은 자동해석보다 항상 우선한다.
2. 자동해석은 기존 model mapping / verified alias / manufacturer alias에 근거할 때만 사용한다.
3. unverified G2B mapping은 **검색 힌트**로만 쓰고 공식분류로 승격하지 않는다.
4. verified G2B mapping만 Research 세부품명번호 basis로 사용할 수 있다.
5. 자동해석 자체는 A/B 판정이 아니다.
6. 실제 A/B는 기존 product matching 규칙을 그대로 통과해야 한다.

### UI

검색결과 상단에 다음을 명시한다.

- 검색어 해석: 품명 / 제조사 / 모델
- 해석 근거: 검증된 모델 매핑 또는 등록된 모델 검색 힌트
- 동일성 확인 A/B 건수
- 검색 참고 건수
- 공개조달 Research 건수

결과의 시각적 우선순위:

1. Safety RED/AMBER — 연결 완료 후 최상단
2. 제품 identity
3. 동일성 확인 A/B 가격
4. Research-only 참고
5. 등록업체·공급업체
6. 대체/경쟁장비 후보
7. 원문 provenance

---

## 4. 의료기기: 장비 → 식약처 등록업체 조회

### 사용자 요구

예를 들어 `심장충격기` 또는 특정 장비/모델을 검색했을 때,

> 이 품목으로 식약처에 등록된 업체가 어디인지

를 바로 확인할 수 있어야 한다.

### 현재 이미 확보된 데이터

식약처 형명정보 API 결과에 다음이 존재한다.

- 품목명
- 모델명
- 허가번호
- 허가일
- 업체명
- 취소/취하 상태
- 수출전용 여부

현재 `의료기기 조회` 화면은 각 등록모델 행에 업체를 표시하지만 **업체 중심 요약이 없다.**

### V1 구현

품목 조회 결과의 국내 정상 후보를 업체별로 그룹화해 별도 카드/표를 제공한다.

표시 필드:

- 등록업체
- 활성 등록모델 수
- 허가건수
- 최근 허가일
- 대표 모델
- 취소/취하 제외 여부

라벨:

**식약처 품목 등록업체**

주의:

이 표시는 특정 모델의 판매점·총판을 의미하지 않는다.

### V2 업허가 교차확인

업체를 선택하면 식약처 제조·수입업 허가정보와 연결한다.

- 업체명
- 업종: 제조 / 수입 / 판매 / 임대 / 수리
- 업허가번호
- 영업상태
- 주소

라벨:

**식약처 업허가 확인**

### 공급사와의 구분

업체 근거는 다음 네 종류를 혼합하지 않는다.

1. `식약처 품목 등록업체` — 제품/품목 허가 근거
2. `식약처 업허가 업체` — 의료기기 영업 자격 근거
3. `나라장터 공급실적 업체` — 실제 공공조달 납품 근거
4. `웹` — 공식 관계 미확정

공급사 우선순위는 기존 원칙을 유지한다.

**나라장터 실제 공급실적 → 식약처 제품/업허가 근거 → 제조사 공식 채널 → 웹**

---

## 5. 동일 품목 경쟁장비

### 현재

식약처 동일 품목의 등록모델 조회와 국내 정상 후보 필터는 이미 구현돼 있다.

### 다음 UI

현재 모델을 기준으로:

- 같은 식약처 품목
- 국내 정상 등록
- 취소/취하 아님
- 수출전용 아님

인 다른 모델을 **동일 품목 등록장비 후보**로 표시한다.

표시:

- 업체
- 모델
- 허가번호
- 허가일
- 공개 조달가격 근거 유무
- 나라장터 공급업체 유무

절대 문구:

- `경쟁장비 후보`
- `동일 식약처 품목 등록모델`

금지 문구:

- `동등장비`
- `대체 가능`
- `구매 추천`

임상적 대체성은 자동 판정하지 않는다.

---

## 6. Safety / 회수·판매중지

초기 기획의 핵심 기능이지만 현재는 공식 링크 기반 수동확인 단계다.

### 다음 구현 gate

공식 회수·판매중지 API request contract가 확인된 경우에만 adapter를 연결한다.

RED:

- exact 모델
- 또는 동일 품목허가번호

의 회수/판매중지 hit.

AMBER:

- 동일 품목/업체 수준 hit
- 관련 안전성서한

NONE:

`연결된 공식 source에서 현재 일치 항목을 확인하지 못함`

`안전함`이라는 표현은 사용하지 않는다.

Safety 경고는 가격보다 위에 둔다.

---

## 7. UDI

현재 기능은 알고 있는 UDI-DI의 exact forward lookup이다.

다음 단계는 공식 request filter가 검증될 때만:

`모델 → UDI-DI / 품목 / 허가번호 / 제조·수입업체`

를 연결한다.

모델명으로 UDI를 추정하지 않는다.

---

## 8. 계약 Research source

Production 실검색에서 계약 API가 일부 요청에 대해:

`SERVICE_KEY_IS_NOT_REGISTERED_ERROR / code=30`

을 반환한다.

현재 UI는 이를 0건과 구분하므로 가격 오판 위험은 제한적이다.

다음 조치:

1. data.go.kr 활용승인/서비스키 scope 확인
2. 해당 operation이 현재 키에 미승인이라면 `미연결`로 명시
3. 승인 전 반복 호출을 줄여 UX 노이즈와 latency를 줄임
4. 계약총액은 수량/단위 검증 전 직접단가로 사용하지 않음

---

## 9. 통합 구매검토 화면 목표

최종적으로 별도 기능 페이지를 늘리는 대신 한 제품 검색결과에서 다음 순서로 보여준다.

### 1. Safety

회수·판매중지 / 안전성 정보

### 2. 제품 확인

품명 / 제조사 / 모델 / 규격 / 식약처 허가 / G2B 분류

### 3. 가격

- 동일성 확인 A/B
- 검색 참고
- 공개조달 Research
- 현재 견적 위치

### 4. 업체

- 식약처 품목 등록업체
- 식약처 업허가
- 나라장터 실제 공급사
- 웹 보조후보

### 5. 경쟁장비

동일 식약처 품목의 다른 국내 정상 등록모델

### 6. 근거

원문 URL / 거래일 / 기관 / 수량 / 조건 / API 상태

---

## 10. 구현 순서

### P0 — 현재 PR

- 한 줄 search intent hydration
- DFM100 / ROTAPRO regression
- 자동해석 UI
- 직접 / 참고 / Research 결과요약 UI

### P1 — 의료기기 업체 중심 UI

- 품목 등록업체 집계
- 업체 → 등록모델 drill-down
- 업허가 교차확인
- G2B 실제 공급업체와 근거등급별 병합
- 홈/견적검토에서 의료기기 조사로 identity handoff

### P1 — 계약 Research 권한정리

- API 승인 scope 확인
- 미승인 endpoint 상태 표시/호출정책 정리

### P2 — Safety 자동연결

- 회수·판매중지 adapter
- RED/AMBER gate
- 가격보다 상단 표시

### P2 — UDI identity

- 공식 filter contract 검증
- 모델/허가/UDI 연결

### P3 — 견적 화면 통합

품목별로 가격 + MFDS + 업체 + Safety를 한 구매검토 카드로 표시한다.

---

## 11. 파일럿 성공 판단

다음 지표를 실사용 이슈 #198에서 누적한다.

- 한 줄 검색이 상세검색과 동일한 A/B 결과를 만드는 비율
- 동일모델 누락/오탐 건수
- Research-only 근거가 직접가격으로 잘못 승격된 건수: 목표 0
- 식약처 exact model 확인 성공률
- 장비별 등록업체/실제 공급사 확보율
- 실제 견적 5종 release gate
- 담당자 시장조사 소요시간
