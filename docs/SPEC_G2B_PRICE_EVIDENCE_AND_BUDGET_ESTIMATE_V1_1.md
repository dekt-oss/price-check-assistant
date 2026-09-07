# SPEC — G2B 가격근거 계층화 + 규격/예산 기반 추정 v1.1

- 상태: **Claude adversarial review 반영 완료 / P0-a 구현만 허용**
- 작성일: 2026-09-07
- 기준 `main`: `f9999ae6ddc3f6e85261ac9892494bbafa772647`
- 원안: `docs/SPEC_G2B_PRICE_EVIDENCE_AND_BUDGET_ESTIMATE_V1.md`
- 외부 리뷰: `docs/REVIEW_CLAUDE_G2B_PRICE_EVIDENCE_V1.md` (PR #110)
- 관련 미완료 PR: #108 `Fix G2B key routing and widen quote research to categories and alternatives`
- 대상 저장소: `dekt-oss/price-check-assistant`

---

## 0. 리뷰 반영 결론

Claude 리뷰의 결론 `REDESIGN REQUIRED`를 수용한다. 다만 기존 명세의 핵심 골격은 유지한다.

유지하는 원칙:

1. Actual Exact / Alternative Actual / Budget Estimate / Procurement Context의 4분리
2. Budget Estimate는 `CollectedPrice`가 아닌 Research-only projection
3. Research record는 `assess_prices()`에 자동 유입되지 않음
4. `MatchGrade A/B/C/D/X`, `EvidenceType`, `ComparisonScope` 기존 계약 유지
5. 넓은 Research와 엄격한 Verdict를 분리

재설계하는 전제와 경계:

1. Research API 인증/활용신청이 실제로 정상인지 먼저 증명한다.
2. 품목/견적 단위 요청예산을 명시적으로 제한한다.
3. 문자열 포함/토큰 교집합만으로 동일분류·대체품을 만들지 않는다.
4. bid item 예정단가 필드 semantics는 실응답 fixture 확보 전까지 미검증으로 차단한다.
5. single-item budget derivation 게이트를 더 좁힌다.
6. VAT basis가 확정되지 않은 경우 quote delta를 표시하지 않는다.

---

## 1. 제품 목표

병원 구매담당자가 견적서를 업로드하면 시스템은 가능한 한 자동으로 다음을 조사한다.

```text
견적서 업로드
  → 제품/모델/규격 추출
  → exact identity 검색
  → 일반 품명/검증 alias 검색
  → 나라장터 공식 세부품명·세부품명번호 확보 시 공식분류 검색
  → 동일제품 실제 단가
  → 동일 공식분류 다른 제조사/모델 실제 단가
  → 조건이 충분할 때 입찰 예산/예정단가 기반 참고 추정
  → 단가화 불가능한 조달 금액은 Context로 분리
  → 사용자에게 4개 영역으로 한 화면에 표시
```

핵심은 다음 식이다.

```text
Research recall ↑
Verdict precision 유지
가격 의미 혼합 = 금지
```

---

## 2. 절대 유지 계약

### 2.1 F1 쇼핑몰 실제단가 계약

`docs/F1_G2B_SHOPPING.md`를 유지한다.

- `prdctUprc`처럼 semantics가 실응답으로 확인된 단가만 직접가격 Evidence 후보가 될 수 있다.
- `prdctAmt` 총액만으로 단가를 임의 생성하지 않는다.
- 실제 단가라도 identity가 불충분하면 직접가격 범위에 들어가지 않는다.
- raw evidence / source record / source URL을 보존한다.

### 2.2 F3 MatchGrade 계약

`docs/F3_PRODUCT_MATCHING.md`를 유지한다.

- A/B만 직접가격 후보
- C는 동일 제품군 참고
- D는 사람이 확인한 기능적 대체관계
- X는 제외
- substring/편집거리만으로 A/B/C/D를 만들지 않는다.

### 2.3 Research isolation

다음은 자동으로 `CollectedPrice`가 될 수 없다.

- 입찰공고 총 추정가격
- 사전규격 배정예산
- 낙찰총액
- 계약총액
- 파생 Budget Estimate
- 문자열 관련 후보

`assess_prices()`는 기존 직접가격 Evidence와 comparability gate를 통과한 데이터만 사용한다.

---

## 3. 리뷰 Finding 처리표

| Finding | 등급 | 결정 | v1.1 반영 |
| --- | --- | --- | --- |
| F1 Research API 403 / 진단 부재 | BLOCKER | 수용 | P0-a로 최우선 |
| F2 요청 예산 없음 | HIGH | 수용 | P0-b |
| F3 문자열 대체품 판정 | HIGH | 수용 | P1에서 삭제/3분리 |
| F4 예정단가 필드 미검증 | HIGH | 수용 | fixture 전 BLOCKED |
| F5 single-item 누락 케이스 | HIGH | 수용 | P2 게이트 강화 |
| F6 낙찰총액/수량 파생 | MEDIUM | v1 보류 | P4 후속 |
| F7 VAT 미확인 delta | MEDIUM | 수용 | P1/P3에서 금지 |
| F8 파일명 generic hint | MEDIUM | 수용 | 입찰검색에만 제한 |
| F9 mapping substring | MEDIUM | 수용 | exact/explicit alias만 |
| F10 EvidenceType budget 값 | MEDIUM | 수용 | deprecated + 생성금지 테스트 |
| F11 #108 테스트 assertion만 변경 금지 | MEDIUM | 수용 | 라벨 정책 먼저 수정 |
| F12 research_hints identity 혼입 | LOW | 후속 개선 | 캐시/identity 분리 고려 |
| F13 30일 창 근거 약함 | LOW | P0-b에서 live 확인 | 미확인 전 30일 유지 |

---

## 4. 제품 소유자 결정 — v1.1 기본값

외부 리뷰가 요구한 6개 결정을 다음과 같이 정한다. 사용자가 명시적으로 변경하기 전까지 이 값이 v1 기준이다.

### D1. Research API 활용신청/키

현재 승인상태는 **미검증**으로 둔다.

P0-a 완료조건:

- `BidPublicInfoService`
- `ScsbidInfoService`
- `HrcspSsstndrdInfoService`

세 서비스가 실제 배포환경 key로 각각 정상 응답해야 한다.

`success_0`도 인증/통신 정상으로 인정하지만 `403/code=30`은 실패다.

### D2. VAT basis

v1에서는 amount type별 법적 VAT basis registry가 공개 근거와 함께 확정되기 전에는 `unknown`을 유지한다.

따라서 VAT basis가 양쪽 모두 확정되고 동일하지 않으면 quote delta를 표시하지 않는다.

### D3. 낙찰총액 ÷ 수량

v1에서는 **사용하지 않는다**.

single-item award derivation은 P4 후속으로 보류한다.

### D4. Alternative band

대체품 band는 **공식 세부품명번호(code) 일치 후보만** 계산한다.

code-exact 후보가 부족하면:

- 후보 표는 보여줄 수 있음
- 중앙값/range는 숨김
- 동일제품 price range에는 절대 혼입하지 않음

### D5. 요청 예산

초기 상한:

```text
품목당 논리 요청 <= 40
견적서 전체 논리 요청 <= 200
```

일일 개발 quota 1,000건을 전제로 한 보수적 시작값이다. 실제 API 제약/성공률을 측정한 후 조정한다.

### D6. PR #108 처리

**분할한다.**

- P0-a: key routing + readiness + live smoke + auth circuit breaker
- P1: narrowed query expansion / classification safety
- #108 전체를 그대로 merge하지 않는다.

---

## 5. 구현 순서와 강제 Gate

### P0-a — Research credential routing / readiness / auth circuit breaker

목표:

- Shopping API key family와 Research API key family를 분리
- 실제 어떤 secret variable이 선택됐는지 key **이름만** 진단에 표시
- Research live smoke를 운영환경에서 직접 실행 가능
- 403/code=30이면 해당 source의 첫 실패 요청 뒤 나머지 term을 중단

필수 구현:

1. `G2B_SHOPPING_SERVICE_KEY`
2. `G2B_RESEARCH_SERVICE_KEY`
3. shopping resolver / research resolver 분리
4. `g2b_shopping_key_source`, `g2b_research_key_source`
5. runtime readiness에 별도 항목
   - `g2b_shopping_credential`
   - `g2b_research_credential`
6. 운영환경 진단에 G2B Research smoke
7. Research status에 `NOT_AUTHORIZED` 또는 동등한 명시상태
8. code=30 / HTTP 403 auth error circuit breaker
9. secret 값/raw URL 노출 금지

완료조건:

```text
CI green
AND
Production/승인 live 환경에서 bid smoke 정상
AND
award smoke 정상
AND
prespec smoke 정상
AND
각 결과에 key_source가 secret 이름으로만 표시
```

**P0-a live 3/3가 확인되기 전 P0-b/P1/P2를 main에 merge하지 않는다.**

### P0-b — Research request budget

P0-a live gate 통과 후 시작한다.

목표:

```text
품목당 <= 40 logical requests
견적당 <= 200 logical requests
```

설계:

```python
@dataclass
class MarketResearchBudget:
    total_limit: int
    per_source_limit: dict[G2BResearchSource, int]
    consumed: int
```

규칙:

- 모든 bid/award/prespec/item/contract/shopping-discovery 요청이 같은 budget을 공유
- 초과 시 `PARTIAL` + `REQUEST_BUDGET_EXHAUSTED`
- retry는 logical request와 physical HTTP attempt를 구분 기록
- 인증오류는 budget을 태우기 전에 첫 실패 후 source 중단

검색 우선순위:

```text
Tier E exact
→ Tier N named/generic
→ Tier G verified official classification
→ Tier A alternatives
```

하위 tier는 상위 tier의 충분한 hit 여부와 남은 budget에 따라 실행한다.

30일 window는 live로 90/365일 요청 허용범위를 확인하기 전까지 유지한다.

### P1 — Narrowed query expansion / classification safety

목표: recall은 넓히되 대체품 가격 오염을 막는다.

#### 5.1 검색어 tier

**Tier E — exact**

- exact model
- manufacturer + model
- product + model
- 검증된 표기 alias

**Tier N — named/generic**

- 견적 한글 품명
- 검증 alias registry
- 파일명 힌트는 입찰/사전규격 discovery에만 사용

파일명 힌트 규칙:

- 1-token generic hint 금지
- 다음 단독 토큰 금지: `장치`, `시스템`, `모니터`, `기기`, `장비`, `세트`, `제품`, `물품`
- 쇼핑몰 특정품목 검색에는 자동 전달하지 않음

**Tier G — official classification**

자동 신뢰 가능:

- verified mapping의 세부품명/세부품명번호
- `research_alias`로 명시 관리된 registry row
- bid item에서 실제로 확보한 official classification code

금지:

- 미검증 row의 substring 매칭
- product label substring만으로 official class 승격

**Tier A — alternatives**

공식 code가 확보된 경우에만 같은 code를 조회한다.

#### 5.2 Research classification label

최소 다음으로 나눈다.

1. `OFFICIAL_CLASS_CODE_EXACT`
   - 세부품명번호 정확 일치
   - Alternative band eligible
2. `OFFICIAL_CLASS_NAME_EXACT_CODE_UNKNOWN`
   - 공식명 정확 일치지만 code 미확인
   - 후보 표 only
3. `TEXT_RELATED_REFERENCE_ONLY`
   - 문자열/검색문맥 관련
   - band 제외
   - dynamic queue 제외

`_terms_semantically_overlap`과 같은 substring/token-intersection 대체품 판정은 삭제한다.

예:

```text
검색어: 냉장고
결과: 시신보관냉장고
→ TEXT_RELATED_REFERENCE_ONLY
→ alternative median에 포함 금지
→ dynamic re-query 금지
```

#### 5.3 dynamic classification queue

v1 기본값은 **비활성 또는 code 기반만 허용**한다.

문자열 label로 queue를 확장하지 않는다.

---

## 6. 가격근거 4계층

### Level 1 — Actual Exact / Comparable Unit Price

- 실제 계약/납품/공개판매 단가
- A/B identity gate 적용
- comparability gate 적용

대표 `EvidenceType`:

- `CONTRACT_UNIT_PRICE`
- `SHOPPING_CONTRACT_UNIT_PRICE`
- `DELIVERY_ORDER_UNIT_PRICE`
- `PUBLIC_SALE_PRICE`

### Level 2 — Alternative Actual Unit Price

- 다른 제조사/모델의 실제 단가
- 공식 세부품명번호 동일 후보가 우선
- 동일제품 range에 절대 혼입하지 않음
- 자동 D 승격 금지

Alternative band 생성조건:

```text
official_class_code_exact == true
AND actual unit price semantics verified
```

### Level 3 — Budget Estimate

입찰/사전규격의 금액을 안전한 조건에서 단가 참고치로 표현한다.

**Research-only projection**이다.

`CollectedPrice`로 변환 금지.

### Level 4 — Procurement Context

단가화할 수 없는 금액/문맥:

- 다품목 총예산
- 기초금액
- 낙찰총액
- 계약총액
- 수량/귀속 불명인 추정가격
- blocked Budget Estimate source

---

## 7. Budget Estimate 데이터 모델

```python
class BudgetEstimateBasis(StrEnum):
    EXPLICIT_ITEM_ESTIMATED_UNIT = "explicit_item_estimated_unit"
    SINGLE_ITEM_TOTAL_DIV_QUANTITY = "single_item_total_div_quantity"

@dataclass(frozen=True)
class BudgetUnitEstimate:
    source_record_id: str
    bid_notice_no: str | None
    bid_notice_order: str | None
    product_name: str | None
    classification_name: str | None
    classification_code: str | None
    relevance_tier: str
    item_list_complete: bool
    quantity: Decimal
    unit: str | None
    source_amount_type: ResearchAmountType
    source_total_amount: Decimal | None
    estimated_unit_price: Decimal
    basis: BudgetEstimateBasis
    vat_status: str | None
    vat_basis_source: str | None
    confidence: str
    calculation_note: str
    source_url: str | None
```

`BLOCKED`는 숫자 estimate 객체를 만들지 않고 별도 eligibility result로 사유를 반환한다.

---

## 8. Budget Estimate eligibility

### 8.1 Explicit item estimated unit price

**실제 bid item API fixture를 확보하기 전에는 BLOCKED.**

기존 parser의 다음 후보 field 목록을 신뢰하지 않는다.

```text
presmptUnitPrce
estmUnitPrc
prdctUnitPrc
unitPrce
unitPrc
```

P0-a가 풀린 뒤 실응답을 캡처하여:

- 공식 API 응답 field
- field meaning
- item-level 여부
- VAT basis

를 확인하고 fixture로 고정한다.

그 전에는 `ResearchAmountType.ESTIMATED_UNIT_PRICE`가 존재해도 Budget Estimate HIGH로 승격하지 않는다.

### 8.2 Single-item total / quantity

다음 조건을 모두 만족해야 한다.

```text
item_list_complete == true
item_count == 1
quantity is integer
quantity >= 1
unit not in PACKAGE_STOPLIST
product/title does not indicate bundled/multi-item procurement
amount attributable to the one item
amount_type is explicitly allowed
official/verified relevance tier is sufficient
```

초기 허용 amount type:

- `ESTIMATED_PRICE`
- `BUDGET_AMOUNT`

단, 반드시 bid item 목록이 완전하고 단일품목임이 확인된 경우만.

### 8.3 PACKAGE_STOPLIST

다음 단위는 자동 derivation을 막는다.

```text
식
일식
SET
set
세트
package
pkg
lot
일괄
```

`대`, `개`, `EA` 등도 품목 semantics가 명확할 때만 허용한다.

### 8.4 bundled/multi-item text gate

다음 패턴은 BLOCKED 예시다.

```text
외 N종
외 N건
외
일괄
패키지
본체 및 부속
설치 포함
교육 포함
유지보수 포함
부대비용 포함
```

단순 `외`는 false positive 가능성이 있으므로 실제 regex/문맥 규칙은 테스트 fixture 기준으로 보수적으로 작성한다.

### 8.5 item list completeness

```text
total_count is known
AND fetched_count == total_count
```

또는 API contract상 완전성이 별도 확인된 경우만 single-item 판정을 허용한다.

`max_pages_per_bid=1`로 일부만 받은 상태에서는 반드시 BLOCKED.

### 8.6 re-bid/order dedupe

같은 `bidNtceNo`에 여러 `bidNtceOrd`가 있으면 최신 유효 order만 Budget Estimate 후보로 사용한다.

원 order들은 Context/Evidence provenance에 남긴다.

### 8.7 quantity

허용:

```text
integer >= 1
```

금지:

- 0
- 음수
- 소수 수량
- OCR/파싱 불확실

### 8.8 prespec budget

사전규격 `asignBdgtAmt`는 사업단위 예산이므로 단독으로 단가 파생하지 않는다.

연결된 bid item 목록이 완전하고 정확히 1개인 경우에만 derivation input 후보가 될 수 있다.

### 8.9 award / contract total

v1에서는 항상 Context로 둔다.

P4에서 single-item gate를 재사용해 별도 검토한다.

---

## 9. VAT 계약

### 9.1 기본 원칙

source가 VAT 포함/별도를 명시하지 않고, 법적/공식 field basis registry도 없으면 `unknown`.

### 9.2 quote delta 허용조건

```text
quote VAT basis known
AND evidence/band VAT basis known
AND bases are comparable or explicitly normalized
```

그 외:

```text
delta = None
```

특히 Shopping band의 VAT basis가 unknown이면 quote가 VAT 포함이어도 `% 높음/낮음` 표시 금지.

### 9.3 VAT registry

향후 amount type별 VAT basis를 추가하려면 반드시:

- 공식 법령/조달청 근거 URL
- 적용 금액 type
- 포함/제외 의미
- parser/test fixture

를 같이 추가한다.

---

## 10. UI 계약

견적 품목 카드의 순서를 고정한다.

### 10.1 동일제품 실제가격

- A/B actual
- source / 거래일
- VAT / 설치 / 보증 / 옵션
- comparability 상태

### 10.2 동일 공식분류 경쟁제품 실제가격

- code-exact 다른 제조사/모델
- actual unit price만
- 동일제품 range와 분리
- code-exact 후보 부족 시 band 숨김, 후보 표만 표시

### 10.3 규격/입찰 예산 참고가격

각 estimate에 표시:

- 공고명
- 공고번호/order
- 품목명
- 공식 분류명/code
- 수량/단위
- 원 금액
- 파생 단가
- 계산식
- VAT 상태
- confidence
- source link

필수 문구:

> 실제 납품·계약단가가 아니라 입찰 당시 예정단가 또는 단일품목 예산을 수량으로 환산한 참고값입니다. 동일제품 시장가격이나 최종 적정성 판정에 자동 포함되지 않습니다.

### 10.4 조달 참고정보

- 사업예산
- 기초금액
- 낙찰총액
- 계약총액
- 사전규격
- BLOCKED estimate source + 차단 사유

### 10.5 첫 화면 요약

예:

```text
동일제품 실제가격: 2건
동일분류 실제가격: 4건
예산 참고가격: 1건
추가 조달참고: 7건
```

`조회 실패`와 `정상 0건`은 반드시 구분한다.

---

## 11. P0-a Research 인증 상태 계약

### 11.1 상태

`ResearchSourceStatus` 또는 동등한 상태에 다음 의미를 둔다.

- `SUCCESS`
- `SUCCESS_0`
- `PARTIAL`
- `FAILURE`
- `NOT_CONFIGURED`
- `NOT_AUTHORIZED`

### 11.2 인증오류 판정

최소 다음을 auth failure로 본다.

- HTTP 403 + service key not registered semantics
- data.go.kr `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`
- `code=30`

auth failure가 발생하면 해당 source는 **첫 term에서 circuit break**한다.

다른 source는 독립 실행한다.

### 11.3 운영 readiness

운영진단은 secret 값을 표시하지 않고 다음만 보여준다.

```text
G2B Shopping credential: configured / missing
selected source: G2B_SERVICE_KEY 등 변수명

G2B Research credential: configured / missing
selected source: DATA_GO_KR_MARKET_SERVICE_KEY 등 변수명
```

credential configured는 API 승인 성공을 의미하지 않는다.

따라서 별도의 live smoke가 필요하다.

### 11.4 Research smoke

버튼 1회 실행으로 bid/award/prespec 각각 `numOfRows=1`, 30일, 단일 keyword를 호출한다.

각 source 결과:

- 정상 + records > 0
- 정상 0건
- NOT_AUTHORIZED
- transport/API FAILURE

를 분리한다.

최대 요청수는 source당 1 logical request로 제한한다.

---

## 12. 요청예산 계약

P0-b에서 구현한다.

### 12.1 기본 상한

```text
item_limit = 40
quote_limit = 200
```

### 12.2 budget exhaustion

초과 시:

- 이미 수집한 Research는 보존
- status `PARTIAL`
- 원인 `REQUEST_BUDGET_EXHAUSTED`
- 미실행 tier/source 표시

### 12.3 early stop

정확 모델 evidence가 충분히 확보되면 불필요한 generic/alternative 검색을 줄일 수 있다.

단, 정확제품 가격 hit이 있다고 해서 사용자 요구상 대체품 Research 자체를 영구 생략하지 않는다. UI 목적/남은 budget에 따라 bounded하게 실행한다.

---

## 13. 테스트 명세

### P0-a tests

1. shopping/research key precedence 분리
2. research key source 이름만 노출
3. secret 값 비노출
4. `403/code=30` 첫 term 후 source circuit break
5. 다른 source는 계속 실행
6. `NOT_AUTHORIZED`와 `SUCCESS_0` 구분
7. research smoke logical request source당 1
8. readiness에 shopping/research credential 별도 표시

### P0-b tests

9. item request budget <= 40
10. quote shared budget <= 200
11. exhaustion → PARTIAL + reason
12. physical retries와 logical requests 분리

### P1 tests

13. `냉장고` → `시신보관냉장고`가 Alternative band에 없음
14. classification code exact만 band eligible
15. name exact/code unknown은 표만
16. substring related는 reference only
17. dynamic queue는 text-related candidate로 확장하지 않음
18. 파일명 `내과 진료실 모니터 견적.pdf`에서 `모니터` 단독 힌트가 쇼핑몰 term으로 나오지 않음
19. 미검증 mapping substring 미사용
20. 띄어쓰기/붙여쓰기 request variant는 API 검색 recall 목적으로 별도 유지 가능

### P2 Budget Estimate tests

21. bid item live fixture 없으면 explicit estimated unit path BLOCKED
22. item list `total_count=150`, fetched=100 → BLOCKED
23. `1 식`, `1 SET`, `1 세트` → BLOCKED
24. `1 대` + 단일품목/완전성 충족 → eligible
25. `외 N종` → BLOCKED
26. quantity 0/음수/소수 → BLOCKED
27. 동일 bid no order 001/002 → 최신 order estimate 1건
28. prespec budget + linked item 2개 → BLOCKED
29. prespec budget + linked item 1개 + 완전성 → MEDIUM 후보
30. 설치/교육/유지보수 별도 행 또는 bundled text → BLOCKED
31. provenance에 source id/order/item completeness/formula 저장
32. duplicate query term → estimate dedupe

### VAT/UI isolation tests

33. VAT unknown band → quote delta None
34. Alternative actual → exact actual range 불변
35. Budget Estimate → `CollectedPrice` 생성 없음
36. Budget Estimate → `DIRECT_PRICE_EVIDENCE_TYPES` 미포함
37. Budget Estimate → `assess_prices()` 입력 금지
38. 4 UI 영역 문구 분리
39. 조회 실패 / 정상 0건 분리
40. `EvidenceType.BID_BASE_AMOUNT`, `BUDGET_AMOUNT` 생성 금지 contract test 또는 deprecated guard

---

## 14. Controlled UAT

### UAT-00 Research readiness

Production 또는 실제 승인 key 환경에서:

```text
keyword=마취
lookback=30
bid / award / prespec 모두 정상 응답
```

`success_0` 허용, 403 불허.

### UAT-01 ExoAtlet-II

- OCR: `엑소아틀레트 - II`, 140,000,000원
- exact / 일반품명 Research
- 공식분류가 실제로 확보되면 code 기반 alternatives
- Actual / Alternative / Budget / Context 분리

### UAT-02 Maquet FLOW-C

- exact model candidate와 `가스마취기` Research 분리
- 다른 마취기 가격은 FLOW-C direct range에 미포함
- budget estimate는 single-item gate 통과 건만

### UAT-03 IT 제품

- verified official classification actual hit
- 같은 code 다른 제조사/모델 alternative 분리

### UAT-04 다품목 묶음

- 총예산을 개별단가로 나누지 않음
- Context에 차단사유 표시

---

## 15. 구현 PR 계획

| 단계 | 내용 | merge gate |
| --- | --- | --- |
| P0-a | key routing + readiness + research smoke + 403 breaker | CI + live 3/3 정상 |
| P0-b | request budget | P0-a live gate 이후, item <=40 / quote <=200 |
| P1 | narrowed expansion + classification labels | substring 대체 band 오염 0 |
| P2 | bid-item fixture + budget estimate | 실응답 field semantics fixture + fail-closed matrix |
| P3 | 4-section UI + VAT-safe delta | UI contract + Production UAT |
| P4 | dynamic code queue / award derivation / advanced category | 별도 명세 |

---

## 16. #108 처리

PR #108은 그대로 merge하지 않는다.

### 흡수할 것 — P0-a

- config key family split
- collector shopping key routing
- research key routing
- probe key source

추가해야 할 것:

- runtime readiness research credential
- research live smoke
- NOT_AUTHORIZED
- 403 circuit breaker

### P1에서 재설계 후 흡수

- query expansion
- file hint
- mapping term expansion
- classification label
- dynamic classification
- alternative band

삭제/변경:

- `_terms_semantically_overlap` 삭제
- mapping substring 제거
- filename hint의 shopping 적용 제거
- code 미확인 candidate의 alternative band 제외

---

## 17. 현재 미검증 사항

다음은 사실로 단정하지 않는다.

1. Production Secrets의 어떤 key가 Research 3 API에 승인돼 있는지
2. bid item 예정단가의 실제 response field
3. amount type별 VAT legal basis
4. 30일을 넘는 Research API 허용 검색 window
5. ExoAtlet-II의 exact 조달 단가 존재 여부
6. FLOW-C exact 조달 단가 존재 여부

---

## 18. v1.1 완료 정의

명세 관점 완료:

- [x] Claude Blocker/High 반영
- [x] #108 split 결정
- [x] request budget 초기값 결정
- [x] VAT unknown 정책 결정
- [x] award derivation v1 제외 결정
- [x] alternative band code-exact 정책 결정

구현 완료는 다음이 모두 충족될 때다.

- [ ] P0-a CI green
- [ ] Research API live smoke 3/3 정상
- [ ] P0-b request budget green
- [ ] P1 substring alternative 오염 차단
- [ ] bid item live fixture 확보
- [ ] P2 Budget Estimate fail-closed tests green
- [ ] P3 UI 4분리 + VAT-safe delta
- [ ] UAT-00~04 증거 보존
- [ ] 기존 Ruff / pytest / match benchmark / Controlled UAT 통과

---

## 19. 구현 원칙

- 테스트 green을 Production 기능 정상의 대체증거로 사용하지 않는다.
- live 미검증은 `미검증`으로 기록한다.
- API 권한 문제는 코드로 숨기지 않는다.
- 검색 결과가 많다는 이유로 좋은 Research라고 판단하지 않는다.
- 실제 단가, 대체품 실제 단가, 예산 추정값, 총액 Context를 숫자 하나의 "시장가격"으로 합치지 않는다.
- 잘못된 직접가격 1건을 넣는 것보다 근거부족으로 남기는 것을 우선한다.
