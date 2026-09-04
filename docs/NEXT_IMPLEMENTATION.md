# 다음 구현 순서

Phase 0는 2026-09-04 종료했다. 최종 검증은 `docs/PHASE0_FINAL_REPORT.md`를 기준으로 한다.

최종 판정은 **Adjust → Phase 1 진행**이다.

## 우선 결정 — 실사용 화면 1개로 통합

사용자 화면을 기능별로 더 늘리지 않는다.

현재 `통합검색`, `견적서 분석`, `의료기기 시장조사`, `Phase0 검증`으로 분리된 UI는 개발 과정에서 생긴 중간 구조로 본다.

최종 실사용 UI 목표는 **`구매검토` 1화면**이다.

- 입력 방식: `직접 검색` / `견적서 업로드`
- 공통 결과: identity → 가격근거 → 견적비교 → 의료기기 공식정보 → 경쟁/공급사 → Safety → 상세근거
- 견적서 다품목은 별도 상세페이지 대신 같은 화면의 master-detail 패턴
- Phase0 검증은 사용자 navigation에서 제거하고 CI/pytest/benchmark/docs로 유지

상세 계약은 `docs/SINGLE_SCREEN_PURCHASE_REVIEW.md`를 기준으로 한다.

---

## Phase 1-UI — Single-screen foundation

가격 source를 더 늘리기 전에 기존 기능을 한 화면에서 안전하게 재사용할 수 있도록 UI/domain 경계를 먼저 정리한다.

1. `PurchaseReviewInput` 공통 입력 계약 정의
2. 직접검색 입력과 견적서 row를 동일 계약으로 변환
3. 가격검색/가격판정 renderer를 재사용 가능한 단위로 분리
4. MFDS identity/경쟁장비/공급사 renderer 분리
5. 결과 화면을 `핵심판정 → identity/Safety → 가격근거 → 경쟁/공급사 → 상세근거` 순으로 통합
6. `st.navigation`으로 사용자 navigation을 1개로 축소
7. 통합 화면 AppTest 및 legacy page parity 검증
8. 검증 완료 후 기존 분리 페이지 제거

이 단계에서 A/B/C/D/X, Evidence Type, ComparisonScope, direct monetary range 계약은 변경하지 않는다.

---

## Phase 1-A — 공개가격 수집 coverage 확대

1. G2B Shopping verified 세부품명 mapping 확대
2. exact model 검색·pagination·retry·실패근거 저장 강화
3. `totalCount`가 안전 페이지 한도를 넘으면 날짜구간을 자동 이분할하는 adaptive date partitioning 추가
4. incomplete window 재시도 큐 및 재개 가능한 수집상태 저장
5. Manufacturer official price snapshot의 freshness/재검증 정책 추가
6. 공식가격 변경 감지
7. raw evidence와 normalized observation provenance 강화

YTD 복원력 검증에서 31일 구간의 레이저프린터가 2,000건을 넘어 safety limit에 도달했다. 페이지 한도를 무작정 키우기보다 날짜구간 자동분할을 우선한다. 상세는 `docs/PHASE0_YTD_RESILIENCE_CHECK.md`를 본다.

## Phase 1-B — G2B 계약정보 collector

다음 신규 production-like collector는 `나라장터 계약정보서비스`로 한다.

목표:
- 물품 실제 계약 목록/상세 수집
- 계약총액·수량·단가 관계 검증
- 공고/계약번호 provenance 연결
- Shopping/납품요구 근거와 독립 source로 비교

## Phase 1-C — 가격조건 구조화

Phase 0 Condition Completeness가 0%였으므로 우선순위가 높다.

구조화 대상:
- VAT 포함/별도/미상
- 수량·단위
- 배송비
- 설치비
- 옵션/부속품
- 보증
- 유지보수/서비스 계약
- 거래/기준일

조건이 다른 가격은 숫자가 같아도 동일 조건 가격으로 취급하지 않는다.

## Phase 1-D — 결과 UX 완성

Single-screen 결과에서 다음을 명시적으로 보여준다.

- 제품 동일성 A/B/C/D/X
- Evidence Type
- 직접비교 가능/참고만 가능/제외
- source와 기준일
- 가격조건 미상 항목
- `비교근거 부족` 상태
- 다중출처 관측범위
- 견적 비교가 보류된 이유

자동 vendor 선정이나 구매결정은 하지 않는다.

---

## Phase 2 — 의료기기 Safety RED layer

식약처 회수·판매중지정보의 **공식 operation/request contract를 확보한 뒤에만** adapter를 구현한다.

목표:
- exact 모델/허가번호 중심 safety matching
- 회수·판매중지 hit 시 가격결과보다 우선하는 RED 경고
- API 실패와 0건을 구분
- `검색결과 없음=안전` 표현 금지
- 시스템이 자동 구매중단을 결정하지 않음

공식 request parameter를 추정해서 구현하지 않는다.

---

## Phase 3 — 견적서 확장

현재 Excel `.xlsx/.xls` 구조적 파싱을 유지하면서 단계적으로 확장한다.

1. 다품목 master-detail UX 완성
2. PDF text extraction
3. OCR은 최후 수단
4. AI는 필드 추출/표준화 보조에 제한

실제 견적파일은 Public PoC에서 영구저장하지 않는다.

---

## 이후 — 내부 이식

Public PoC 승인 후 별도 진행한다.

- 내부 단가 Excel import부터 검토
- PostgreSQL에 검증된 observation/evidence 축적
- ERP 직접연계는 후순위
- 병원 내부 견적/단가/거래처 데이터는 public repo 또는 공개 Streamlit에 저장하지 않음
