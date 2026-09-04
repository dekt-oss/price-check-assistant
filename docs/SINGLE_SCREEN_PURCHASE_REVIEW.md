# Single-screen 구매검토 UI 정비안

## 1. 결정

사용자에게 보이는 실사용 화면은 **1개**를 목표로 한다.

현재 `Home + 통합검색 + 견적서 분석 + 의료기기 시장조사 + Phase0 검증`으로 분리된 구조를 그대로 확장하지 않는다.

최종 사용자 흐름은 아래 하나로 통합한다.

```text
구매검토
├─ 직접 검색
└─ 견적서 업로드
      ↓
선택된 1개 품목의 공통 조사 파이프라인
      ↓
제품 identity → 가격근거 → 견적비교 → 의료기기 공식정보 → 경쟁/공급사 → Safety → 상세근거
```

`직접 검색`과 `견적서 업로드`는 서로 다른 페이지가 아니라 **입력 방식만 다른 동일 화면의 탭/세그먼트**로 취급한다.

---

## 2. 화면 계약

### 상단: 입력

한 화면 상단에서 입력 방식을 선택한다.

- `직접 검색`
  - 제품명
  - 제조사
  - 모델명
  - 규격
  - 현재 견적단가(선택)
- `견적서 업로드`
  - `.xlsx/.xls` 업로드
  - 추출 행 확인/수정
  - 조사할 행 1개 선택

두 입력 방식은 최종적으로 동일한 `PurchaseReviewInput` 계약으로 정규화한다.

```text
product_name
manufacturer
model_name
specification
quote_unit_price (optional)
```

견적서 원본 파일, 파일명, 시트명, 원본 행번호, 총액 등은 외부 source 교차조회 identity payload로 사용하지 않는다.

---

## 3. 같은 화면의 결과 순서

### A. 핵심 판정

가장 먼저 담당자가 결론을 읽을 수 있어야 한다.

- 제품/모델 확인 상태
- 현재 견적
- 관측 가격범위
- 견적 위치 또는 판정보류
- 근거 신뢰도
- 주요 확인 필요사항

### B. 제품 identity / 공식정보

- A/B/C/D/X 제품 동일성
- 식약처 exact identity가 확인된 경우 품목명·모델명·허가번호
- ambiguous/inactive/export-only 상태는 fail-closed
- 견적서나 사용자 입력 문자열 자체를 공식 identity로 승격하지 않음

### C. Safety

- exact 모델/허가번호 기준 공식 회수·판매중지 hit가 있으면 가격영역보다 우선하는 RED 경고
- `조회 실패`, `미연결`, `0건`을 `안전`으로 표현하지 않음
- 자동 구매중단 판단은 하지 않음

### D. 가격 근거

- 직접근거 관측범위
- source 수
- Evidence Type
- ComparisonScope
- 기준일
- 가격조건(VAT/설치/옵션/보증 등)

### E. 경쟁장비 / 공급사

의료기기일 때만 필요한 정보를 노출한다.

- 동일 공식 식약처 품목의 국내 정상 등록모델
- broad alternative는 공식 조회 성공 + 국내 동일품목 후보 0건일 때만 `추가 조사 후보`
- 공급사 우선순위
  1. G2B 실제 공개 납품업체
  2. MFDS 제조/수입업허가 업체
  3. 웹 후보(`웹` 명시)

### F. 상세 근거

긴 표·원문 provenance는 기본 접힘(expander)으로 둔다.

사용자는 한 화면을 유지하되 필요한 경우에만 상세를 펼친다.

---

## 4. 견적서 다품목 UX

견적서 전체 결과도 별도 페이지를 만들지 않는다.

1. 견적서 업로드
2. 품목별 요약표 표시
3. 행 선택
4. 같은 화면 아래 `선택 품목 상세` 갱신
5. 다른 행을 선택하면 상세만 교체

즉 `견적서 요약 → 품목 상세`는 페이지 이동이 아니라 **master-detail** 패턴으로 구현한다.

---

## 5. 사용자 화면에서 제거할 것

### Phase0 검증 페이지

사용자 메뉴에서 제거한다.

- 검증 자체는 삭제하지 않음
- CI, pytest, benchmark artifact, docs로 유지
- 운영 UI에 개발용 검증 페이지를 노출하지 않음

### 기존 분리 페이지

통합 화면 parity 검증 전까지 코드는 임시 유지할 수 있으나 사용자 navigation에서는 숨긴다.

- `1_통합검색.py`
- `2_견적서_분석.py`
- `4_의료기기_시장조사.py`

통합 화면의 AppTest와 회귀테스트가 확보되면 legacy page를 제거한다.

---

## 6. Navigation 구현

현재 최소 Streamlit 계약은 `streamlit>=1.40`이다.

`st.navigation` / `st.Page`는 이 최소버전에서 사용할 수 있다.

구현 목표:

```python
page = st.Page("app_pages/purchase_review.py", title="구매검토", default=True)
pg = st.navigation([page], position="hidden")
pg.run()
```

`st.navigation`을 사용하면 기존 `pages/` 자동 navigation은 무시되므로 사용자에게는 단일 화면만 보이게 할 수 있다.

주의:
- 첫 refactor PR에서는 legacy page 파일을 즉시 삭제하지 않는다.
- 새 단일화 페이지가 기능 parity를 확보한 뒤 삭제한다.

---

## 7. 구현 순서

### PR-A — UI foundation

- `PurchaseReviewInput` 공통 입력 계약
- 가격검색 결과 renderer 분리
- MFDS identity/경쟁/공급사 renderer 분리
- 견적서 row → 공통 입력 변환
- 기존 기능 결과값은 변경하지 않음

### PR-B — Single-screen page

- 직접검색 / 견적서 업로드 입력 탭
- master-detail 견적서 UX
- 가격 + MFDS + G2B를 동일 결과영역에서 렌더
- `st.navigation`으로 사용자 navigation 1개로 축소
- 기존 legacy page는 navigation에서 숨김

### PR-C — Safety RED layer

공식 operation/request contract가 확보된 뒤 진행한다.

- MFDS 회수·판매중지 adapter
- exact 모델/허가번호 matching
- hit 시 결과 최상단 RED 경고
- no hit 문구는 `현재 연결된 공식 안전정보에서 일치 항목을 확인하지 못함`
- API 실패는 별도 오류 상태

### PR-D — Legacy removal / production smoke

- 단일화 AppTest
- 직접검색 회귀
- 견적서 `.xls/.xlsx` 회귀
- MFDS identity fail-closed 회귀
- G2B supplier gate 회귀
- production smoke 후 기존 3개 페이지 제거

---

## 8. 비목표

이번 UI 정비에서 아래는 하지 않는다.

- LLM을 핵심 검색 dependency로 추가
- 유사문자열만으로 식약처 공식 identity 확정
- broad alternative를 자동 대체장비로 승격
- lowest price를 적정가격으로 간주
- `observed_only` 가격으로 견적 높음/낮음 강제판정
- API 조회 실패를 0건으로 처리
- Safety 미조회/0건을 안전으로 표현
- 실제 병원 견적파일을 public repo/DB에 저장

---

## 9. 완료 기준

사용자가 첫 화면에서 아래 업무를 페이지 이동 없이 수행할 수 있으면 완료로 본다.

1. 제품 직접 검색 또는 견적서 업로드
2. 품목 선택
3. 무엇인지(identity) 확인
4. 가격근거 확인
5. 견적 위치 확인 또는 판정보류 이유 확인
6. 의료기기라면 경쟁장비/공급사 확인
7. Safety 확인
8. 상세 근거 펼쳐보기

**사용자 화면 수 목표: 1개.**
