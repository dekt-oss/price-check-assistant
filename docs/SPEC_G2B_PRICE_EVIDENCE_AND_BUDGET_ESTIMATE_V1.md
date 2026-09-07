# SPEC — G2B 가격근거 계층화 + 규격/예산 기반 추정 v1

- 상태: **Draft — 외부 리뷰 전 구현 금지**
- 작성일: 2026-09-07
- 기준 `main`: `f9999ae6ddc3f6e85261ac9892494bbafa772647`
- 관련 선행 작업: PR #108 `Fix G2B key routing and widen quote research to categories and alternatives`
- 대상 저장소: `dekt-oss/price-check-assistant`

---

## 1. 목적

이 작업의 목적은 나라장터 자료를 단순히 많이 보여주는 것이 아니라, **견적 제품의 실제 거래가격, 같은 품목군의 대체제품 가격, 규격이 유사한 입찰의 예산기반 참고가격을 서로 다른 근거로 분리하여 구매담당자에게 제공하는 것**이다.

최종 사용 흐름은 다음을 목표로 한다.

```text
견적서 업로드
  → 제품/모델/규격 추출
  → exact 제품명 + 일반 품명 + 나라장터 공식 세부품명/분류 검색
  → 실제 단가 Evidence 탐색
  → 동일제품 자료가 부족하면 동일분류 경쟁·대체제품 탐색
  → 입찰/사전규격의 수량·예산·예정단가를 이용한 Budget Estimate 생성
  → 실제가격 / 대체품가격 / 예산추정 / 단순 조달문맥을 분리 표시
  → 최종 판정에는 기존 strict gate 유지
```

핵심은 **Research recall은 넓히되 Verdict precision은 훼손하지 않는 것**이다.

---

## 2. 현재 저장소 계약과 절대 유지할 원칙

### 2.1 기존 F1 계약

`docs/F1_G2B_SHOPPING.md`의 계약을 유지한다.

- 특정품목 조달내역의 `prdctUprc`는 실제 단가 Evidence가 될 수 있다.
- `prdctAmt` 총액만으로 단가를 임의 생성하지 않는다.
- 조달 가격을 수집해도 제품 동일성 검증 전에는 직접가격 범위에 넣지 않는다.
- raw evidence와 원 출처를 보존한다.

### 2.2 기존 F3 계약

`docs/F3_PRODUCT_MATCHING.md`의 `MatchGrade A/B/C/D/X` 의미를 바꾸지 않는다.

- A/B만 직접가격 후보가 될 수 있다.
- C는 동일 제품군 참고, D는 사람이 확인한 기능적 대체관계, X는 제외다.
- 문자열 유사도만으로 A/B/D를 만들지 않는다.
- `EvidenceType`과 `MatchGrade`는 독립 축이다.

### 2.3 Research와 CollectedPrice 분리

`G2BResearchRecord`는 계속 Research 전용 타입으로 유지한다.

입찰공고, 사전규격, 낙찰총액, 사업예산, 파생 예산단가는 **자동으로 `CollectedPrice`로 변환하지 않는다.**

`assess_prices()`에는 기존 직접가격 Evidence와 기존 comparability gate를 통과한 자료만 들어간다.

---

## 3. 문제 정의

Production UAT에서 다음 구조적 문제가 확인됐다.

### P1. 견적의 모델명만 검색하면 recall이 지나치게 낮다

예:

```text
견적 표기: 엑소아틀레트 - II
```

나라장터 입찰공고/사전규격에서는 제조사·모델명 대신 다음과 같은 일반/공식 품명으로 공고될 수 있다.

```text
로봇보조 정형용 운동장치
로봇보조정형용운동장치
보행재활로봇
정형용 운동장치
```

따라서 exact 문자열 검색만으로는 시장자료를 놓친다.

### P2. 입찰공고는 discovery에는 유용하지만 제품 단가 source가 아닌 경우가 많다

입찰공고에는 다음 정보가 자주 부족하다.

- 제조사
- exact 모델
- 개별 품목 단가
- 실제 계약/납품 가격

반면 다음 정보는 유용하다.

- 구매 목적/품명
- 품목상세
- 수량/단위
- 예정단가가 있는 경우 해당 값
- 사업예산/추정가격/기초금액
- 사전규격과 첨부문서

따라서 입찰공고는 **제품분류와 가격추정 context source**로 사용해야 한다.

### P3. 실제 거래가격과 예산가격이 UI에서 같은 "시장가격"처럼 보이면 위험하다

예:

- 나라장터 납품요구 실제 단가: 140,000,000원
- 유사 입찰 사업예산 / 수량: 150,000,000원/대
- 여러 장비 묶음 입찰 총예산: 500,000,000원

세 값의 의미는 전혀 다르다.

가격 근거의 의미를 모델과 UI에서 강제 분리해야 한다.

---

## 4. 목표 / 비목표

### 4.1 목표

1. **실제 단가 Evidence를 최우선으로 찾는다.**
   - 나라장터쇼핑몰 특정품목 조달/납품요구
   - 계약 단가
   - 그 밖의 검증된 direct price source
2. exact 제품명이 없더라도 **일반 품명·공식 세부품명·분류로 검색을 확장**한다.
3. 같은 공식 품목군의 다른 제조사/모델을 **대체제품 Research**로 제시한다.
4. 입찰/사전규격의 명시된 예정단가 또는 안전하게 계산 가능한 단일품목 예산을 **Budget Estimate**로 제시한다.
5. Actual / Alternative / Budget / Context를 UI에서 명시적으로 분리한다.
6. 사용자가 결과의 원문, 계산식, 수량, VAT 상태, 근거 수준을 추적할 수 있게 한다.

### 4.2 비목표

이번 v1에서는 다음을 하지 않는다.

- 여러 품목이 포함된 총예산을 모델이 임의 배분
- 단순 텍스트 유사도로 의료기기의 임상적 대체 가능성 확정
- 입찰 예산을 실제 계약단가로 승격
- 예산 추정값을 `assess_prices()` 직접가격 범위에 혼입
- LLM만으로 세부품명번호를 확정하고 직접가격 검색에 사용
- 사전규격 첨부 PDF 전체의 고도화된 성능 ontology 비교

---

## 5. 검색 플래너 계약

### 5.1 Query Plan

한 품목마다 검색어를 다음 tier로 생성한다.

#### Tier E — Exact identity

- exact 모델
- 제조사 + 모델
- 견적 품명 + 모델
- 한글/영문 표기 alias

#### Tier N — Named product/category

- 견적서의 한글 일반 품명
- 파일명에서 부서명/문서명을 제거한 제품군 힌트
- 검증된 alias registry

#### Tier G — G2B official classification

- 검증된 `g2b_product_mappings.csv` 세부품명
- 입찰 품목상세에서 발견한 공식 품명
- 쇼핑몰 결과의 `dtilPrdctClsfcNoNm`
- 가능하면 세부품명번호

#### Tier A — Alternatives

Tier G에서 확보한 동일 공식 분류를 다시 조회하여 다른 제조사/모델 후보를 수집한다.

### 5.2 검색 결과의 역할

검색어가 넓어졌다고 MatchGrade가 상승하지 않는다.

```text
search term / classification expansion
    = recall 도구
    != 제품 동일성 증거
```

모델/제조사/규격 검증은 기존 matcher가 담당한다.

### 5.3 PR #108과의 관계

PR #108의 다음 작업은 이 명세의 선행조건으로 간주한다.

- 쇼핑몰 API와 입찰/낙찰/사전규격 API의 key family 분리
- exact + category research term 확장
- filename research hint
- official detail product name 재검색
- 동일모델 / 동일제조사 / 동일분류 후보 분리

단, #108은 이 명세 작성 시점에 CI가 완전히 green인 상태가 아니므로 **그대로 완료된 전제로 구현하지 않는다.**

구현 전 #108을 수정·머지하거나, 이 작업 브랜치에서 동등한 변경을 명시적으로 흡수해야 한다.

---

## 6. 가격근거 계층

UI와 내부 모델에서 최소 다음 4개 그룹을 구분한다.

### Level 1 — Actual Exact/Comparable Unit Price

실제 단가이며 제품 동일성/비교가능성 검증 대상이다.

예:

- `EvidenceType.CONTRACT_UNIT_PRICE`
- `EvidenceType.SHOPPING_CONTRACT_UNIT_PRICE`
- `EvidenceType.DELIVERY_ORDER_UNIT_PRICE`
- `EvidenceType.PUBLIC_SALE_PRICE`

사용 규칙:

- A/B + 기존 comparability gate 통과 시 직접 비교 가능
- A/B라도 VAT/설치/보증/옵션 불명확하면 기존 `OBSERVED_ONLY` 유지

### Level 2 — Alternative Actual Unit Price

동일 공식 세부품명/품목군의 다른 제조사 또는 모델에서 관찰된 실제 단가다.

- 가격 자체는 실제 거래값일 수 있다.
- 그러나 검색대상과 exact 제품이 아니므로 동일제품 가격 range에 넣지 않는다.
- 자동 D 승격은 하지 않는다.
- 기본적으로 Research/reference 영역에 둔다.

### Level 3 — Budget Estimate

입찰/사전규격/품목상세의 예산 또는 예정단가를 이용한 **참고 추정값**이다.

`G2BResearchRecord`/별도 derived result로 유지하고 `CollectedPrice`로 자동 변환하지 않는다.

### Level 4 — Procurement Context

제품 단가로 사용할 수 없는 금액이다.

예:

- 다품목 사업 총예산
- 낙찰 총액
- 계약 총액
- 기초금액
- 추정가격이나 배정예산이지만 수량/품목 귀속 불명확

화면에는 보여줄 수 있으나 "가격범위" 계산에는 사용하지 않는다.

---

## 7. Budget Estimate 안전 규칙

### 7.1 직접 명시된 예정단가

입찰 품목상세에 품목별 `ESTIMATED_UNIT_PRICE` 또는 의미가 검증된 예정단가 필드가 있으면 다음 조건에서 Budget Estimate로 채택한다.

필수:

- 금액이 item-level임이 source field semantics로 확인됨
- 어떤 품목의 금액인지 연결됨
- 통화가 KRW이거나 명시적으로 변환 가능
- 해당 품목의 공식명/분류 또는 product identity 근거가 있음

이 경우 계산하지 않고 원문 값을 사용한다.

### 7.2 단일품목 총예산 ÷ 수량 파생

명시 단가가 없고 다음 조건을 **모두 만족**할 때만 파생 단가를 계산한다.

```text
single_item_scope == true
quantity != null
quantity > 0
budget_or_estimated_total != null
budget_or_estimated_total > 0
multi_item_ambiguity == false
unit_ambiguity == false
```

계산식:

```text
budget_estimated_unit_price = attributable_budget_total / quantity
```

파생 결과에는 반드시 다음 provenance를 저장한다.

- 원 공고/사전규격 ID
- 사용한 총액 필드명/amount type
- 수량
- 단위
- 계산식
- VAT 상태
- single-item 판정 근거
- product/category 연결 근거

### 7.3 자동 계산 금지 조건

다음 중 하나라도 있으면 계산하지 않는다.

- 품목이 2개 이상
- package/set에 여러 독립 장비가 포함
- 수량 없음 또는 OCR/파싱 신뢰 불충분
- 총액이 계약/사업 전체인지 품목별인지 불명
- VAT 포함 여부가 계산에 치명적이고 상태 불명
- 단위가 서로 다른 복수 품목
- 옵션/설치/교육/유지보수 비용이 총액에 포함되나 분리 불가
- `AWARD_TOTAL`/`CONTRACT_TOTAL`을 개별제품 수량으로 단순 나누려는 경우

이때는 `Procurement Context`로만 표시한다.

### 7.4 VAT

Budget Estimate v1은 VAT를 임의 추정하지 않는다.

- source가 VAT 포함/별도를 명시하면 그대로 저장
- quote와 VAT basis가 다르면 delta 계산 금지 또는 명시적 normalization을 거친 후에만 계산
- VAT 불명이면 `VAT 미확인`으로 표시하고 직접 비교 문구를 금지

---

## 8. 제안 데이터 모델

기존 `ResearchAmountType`에는 이미 다음 타입이 있다.

- `UNIT_PRICE`
- `ESTIMATED_UNIT_PRICE`
- `ESTIMATED_PRICE`
- `BASIC_AMOUNT`
- `BUDGET_AMOUNT`
- `AWARD_TOTAL`
- `CONTRACT_TOTAL`

이를 최대한 재사용한다.

파생 추정치 자체를 `CollectedPrice`로 만들지 않고 별도 projection을 권장한다.

예시:

```python
class BudgetEstimateBasis(StrEnum):
    EXPLICIT_ITEM_ESTIMATED_UNIT = "explicit_item_estimated_unit"
    SINGLE_ITEM_TOTAL_DIV_QUANTITY = "single_item_total_div_quantity"

@dataclass(frozen=True)
class BudgetUnitEstimate:
    source_record_id: str
    product_name: str | None
    classification_name: str | None
    quantity: Decimal
    unit: str | None
    source_total_amount: Decimal
    estimated_unit_price: Decimal
    basis: BudgetEstimateBasis
    vat_status: str | None
    confidence: str
    calculation_note: str
    source_url: str | None
```

### 8.1 Confidence

v1은 정교한 확률값 대신 규칙 기반 `HIGH / MEDIUM / BLOCKED`를 사용한다.

#### HIGH

- source가 품목별 예정단가를 명시
- 품목 식별/분류 명확
- 단가 field semantics 검증

#### MEDIUM

- 단일품목 입찰
- 수량 명확
- 총 예산/추정가격의 품목 귀속 명확
- `total / quantity` 계산

#### BLOCKED

- 다품목/귀속불명/수량불명 등 금지조건

BLOCKED는 숫자 단가를 생성하지 않는다.

---

## 9. 규격/품목 관련성 v1

고급 사양 비교 엔진은 이번 범위 밖이지만 Budget Estimate의 잡음을 줄이기 위해 최소 관계등급은 필요하다.

### 9.1 관계 tier

- `EXACT_MODEL` — exact model evidence
- `OFFICIAL_CLASS_EXACT` — 동일 G2B 세부품명/세부품명번호
- `CATEGORY_ALIAS_VERIFIED` — 검증된 alias/registry로 동일 제품군
- `TEXT_RELATED_UNVERIFIED` — 문자열/문맥만 관련
- `UNRELATED`

Budget Estimate 자동 생성은 기본적으로 다음까지만 허용한다.

```text
EXACT_MODEL
OFFICIAL_CLASS_EXACT
CATEGORY_ALIAS_VERIFIED
```

`TEXT_RELATED_UNVERIFIED`는 Research 화면에만 보이고 예산단가 range에는 포함하지 않는다.

### 9.2 의료기기 성능 대체성

동일 세부품명이라도 임상적 대체 가능성을 의미하지 않는다.

UI 문구는 "동일분류/대체 후보" 또는 "유사 조달 규격" 수준으로 제한한다.

---

## 10. UI 계약

견적 품목 카드에서 아래 순서를 고정한다.

### 10.1 실제 동일제품/직접가격

```text
동일제품 실제가격
- 직접가격 A/B
- VAT/설치/보증/옵션 상태
- 출처/거래일
```

### 10.2 동일분류 실제 거래가격

```text
동일분류·경쟁제품 실제가격
- 다른 제조사/모델
- 실제 납품/계약단가
- 동일제품 range와 완전히 분리
```

### 10.3 규격/입찰 예산 참고가격

```text
규격 유사 입찰의 예산 참고가격
- 공고명
- 품목명/공식 분류
- 수량
- 원 예산/예정단가
- 파생 단가
- 산출 방식
- VAT 상태
- 신뢰도 HIGH/MEDIUM
```

경고문:

> 실제 납품·계약단가가 아니라 입찰 당시 예정단가 또는 예산을 수량으로 환산한 참고값입니다. 동일제품 시장가격이나 최종 적정성 판정에 자동 포함되지 않습니다.

### 10.4 조달 참고정보

단가로 사용할 수 없는 공고/낙찰/계약 총액은 별도 expander로 표시한다.

```text
조달 참고정보
- 사업예산
- 기초금액
- 낙찰총액
- 계약총액
- 사전규격
```

### 10.5 Delta 표기

- actual exact/comparable price: 기존 규칙에 따라 가능
- alternative actual price: 동일제품 대비 delta 문구 금지
- Budget Estimate: `견적 대비 예산 참고값 차이`라고 명시할 때만 별도 계산 가능
- VAT 또는 quantity basis가 다르면 delta 금지

---

## 11. 예시 시나리오

### 11.1 ExoAtlet-II

입력:

```text
견적 제품: 엑소아틀레트 - II
견적 단가: 140,000,000원
파일명 힌트: 재활의학과 로봇보조 정형용 운동장치 견적2.pdf
```

검색 plan 예:

```text
엑소아틀레트 II
ExoAtlet II
로봇보조 정형용 운동장치
로봇보조정형용운동장치
정형용 운동장치
[검색/품목상세에서 발견한 공식 세부품명]
```

결과 표시 예:

```text
동일제품 실제가격: 없음/발견값
동일분류 실제가격: 경쟁제품 A/B/C
규격 유사 예산참고: A병원 1대 150M → 150M/대 (MEDIUM)
조달문맥: B병원 의료장비 3종 총예산 500M → 개별단가 산출 금지
```

### 11.2 iPhone 17

입력:

```text
제품: iPhone 17
```

목표 흐름:

```text
iPhone 17
→ Apple + model
→ 스마트폰/휴대용단말기 등 검증 가능한 제품군 후보
→ G2B 공식 세부품명/번호 확보
→ 동일분류 조달이력 조회
→ Galaxy 등 다른 모델은 Alternative 영역에 표시
```

단, 범용 `iPhone 17 → 스마트폰` inference가 검증된 registry/공식 분류 없이 자동 확정되는 것은 v1 완료조건이 아니다.

---

## 12. 구현 단계

### Phase A — PR #108 안정화/선행조건

1. API key family routing CI green
2. exact/category search expansion 회귀테스트 green
3. 검색어 띄어쓰기/붙여쓰기 recall 보존
4. Production에서 403과 transport failure를 구분 표시
5. merge 또는 본 작업에 동등 변경 흡수

**Phase A가 끝나기 전 Budget Estimate 구현을 main에 merge하지 않는다.**

### Phase B — Budget Estimate domain/service

1. `budget_estimate.py` 등 순수 서비스 계층 추가
2. G2B Research record에서 eligible input 선택
3. single-item 판정 함수
4. explicit unit estimate 처리
5. total/quantity safe derivation
6. prohibited matrix 구현
7. provenance/calculation note
8. VAT/quantity validation

### Phase C — Research pipeline integration

1. bid item / prespec / notice 연결 데이터를 estimator 입력으로 연결
2. exact/category relevance와 estimate eligibility 결합
3. 중복 공고/동일 source record dedupe
4. 실제가격 Research와 별도 collection 유지

### Phase D — UI

1. Actual Exact
2. Alternative Actual
3. Budget Estimate
4. Procurement Context

네 구역을 명확히 분리한다.

### Phase E — UAT / 운영 gate

실제 견적서와 공개 조달 사례로 Production UAT를 수행한다.

---

## 13. 테스트 명세

### 13.1 Unit tests — 반드시 추가

#### BUD-01 explicit 예정단가

```text
item estimated unit = 118,500,000
qty = 1
→ HIGH / 118,500,000
```

#### BUD-02 single-item total/qty

```text
single item
budget = 300,000,000
qty = 2
→ MEDIUM / 150,000,000
```

#### BUD-03 multi-item block

```text
A 1대 + B 2대
사업예산 = 300,000,000
→ BLOCKED / no unit estimate
```

#### BUD-04 quantity missing

```text
budget present, qty absent
→ BLOCKED
```

#### BUD-05 award/contract total block

```text
AWARD_TOTAL 또는 CONTRACT_TOTAL
개별 item allocation 없음
→ BLOCKED
```

#### BUD-06 VAT mismatch

```text
quote VAT included
estimate VAT unknown
→ 숫자 표시 가능, quote delta 금지
```

#### BUD-07 alternative isolation

동일분류 경쟁제품 실제단가가 동일제품 actual range에 들어가지 않아야 한다.

#### BUD-08 Research isolation

Budget Estimate가 `CollectedPrice`, `DIRECT_PRICE_EVIDENCE_TYPES`, `assess_prices()` 입력으로 자동 승격되지 않아야 한다.

#### BUD-09 provenance

파생 estimate에 source id, total, qty, formula가 반드시 보존돼야 한다.

#### BUD-10 dedupe

같은 공고/품목/금액이 여러 query term에서 발견돼도 estimate는 중복 집계하지 않는다.

### 13.2 Query expansion tests

- exact model
- manufacturer + model
- quote generic Korean name
- filename category hint
- verified G2B official detail name
- dynamic official detail name
- whitespace/compact Korean variants

각 search term은 recall만 확장하고 MatchGrade를 직접 승격하지 않아야 한다.

### 13.3 UI contract tests

문구/섹션에 다음이 구분되어야 한다.

- `동일제품 실제가격`
- `동일분류·경쟁제품 실제가격`
- `규격 유사 입찰의 예산 참고가격`
- `조달 참고정보`

Budget Estimate 화면에는 반드시 `실제 거래단가가 아님` 취지의 문구가 있어야 한다.

---

## 14. Controlled UAT 세트

최소 다음 케이스를 실제 Production 또는 live API 허용 환경에서 확인한다.

### UAT-01 ExoAtlet-II

목표:

- 견적 OCR 성공
- exact + 파일명 일반품명 검색
- 공식 품명/분류 확장 여부 확인
- 실제 단가/대체품/예산참고 분리 확인

### UAT-02 Maquet FLOW-C

목표:

- exact 모델 후보와 일반 `가스마취기` Research 분리
- 품목상세 예정단가가 있으면 Budget Estimate로 표시
- 다른 마취기 가격이 FLOW-C direct range에 혼입되지 않음

### UAT-03 일반 IT 제품

예: 노트북컴퓨터 또는 스마트폰 계열.

목표:

- 공식 세부품명 기반 actual unit-price hit
- 여러 제조사/모델을 alternative로 분리

### UAT-04 다품목 묶음 입찰

목표:

- 총예산을 개별 제품 단가로 계산하지 않음
- Procurement Context로만 표시

---

## 15. 완료 기준

다음이 모두 만족되어야 구현 완료로 본다.

- [ ] #108 선행 검색/key-routing 계약이 green 상태로 반영됨
- [ ] 실제 거래단가와 Budget Estimate가 타입/UI에서 분리됨
- [ ] Budget Estimate가 `CollectedPrice`로 자동 승격되지 않음
- [ ] 단일품목 + 수량 명확 조건에서만 total/qty 파생 가능
- [ ] 다품목·수량불명·총액귀속불명은 fail-closed
- [ ] VAT 미확인 시 직접 quote delta를 만들지 않음
- [ ] actual exact / alternative / budget / context 4개 UI 영역 분리
- [ ] query expansion이 exact → generic → official class → alternatives로 동작
- [ ] UAT-01~04 결과 증거 보존
- [ ] Ruff / pytest / benchmark / Controlled UAT 기존 gate 통과
- [ ] Production에서 API 인증 실패와 정상 0건을 구분 표시

---

## 16. 구현 시 예상 변경 지점

외부 리뷰 후 확정하며, 현재 예상은 다음과 같다.

```text
src/purchase_price/services/
  g2b_unmapped_discovery.py
  market_research.py
  g2b_bid_item_enrichment.py
  [new] budget_estimate.py

src/purchase_price/services/g2b_market_models.py
src/purchase_price/ui/market_research.py
src/purchase_price/ui/quote_market_research.py

data/g2b_research_terms.csv 또는 관련 mapping registry

tests/
  test_budget_estimate.py
  test_g2b_unmapped_discovery.py
  test_market_first_ui_contract.py
  관련 UAT fixtures
```

`domain.py`의 `EvidenceType`을 불필요하게 늘리기보다, Budget Estimate는 Research projection으로 유지하는 방안을 우선 검토한다.

---

## 17. 리스크

### R1. 잘못된 category expansion

너무 넓은 품목으로 확장하면 무관한 경쟁제품이 쏟아질 수 있다.

대응:

- official classification / verified alias 우선
- text-only 관련 후보는 estimate eligible에서 제외

### R2. 총예산 오배분

가장 위험한 실패다.

대응:

- multi-item면 파생 금지
- single-item provenance 없으면 금지

### R3. 실제가격과 예산가격 혼동

대응:

- 데이터 타입/section/copy 모두 분리
- 예산값을 direct price summary에 전달하지 않음

### R4. API 호출량 폭증

exact + category + dynamic classification 검색으로 요청 수가 늘 수 있다.

대응:

- bounded query budget
- term dedupe
- official classification 발견 후 우선순위 재조정
- 캐시/동일 source dedupe

### R5. 규격 유사도 과신

v1은 고급 specification similarity 점수를 만들지 않는다.

대응:

- 공식 분류/verified category 기반만 자동 estimate 대상
- 성능 비교/임상대체성은 별도 후속

---

## 18. 외부 리뷰에서 반드시 답할 질문

1. Budget Estimate를 별도 dataclass/projection으로 두는 것이 기존 `EvidenceType` 확장보다 안전한가?
2. `single-item` 판정 계약이 충분히 fail-closed한가? 빠진 위험 사례가 있는가?
3. `ESTIMATED_PRICE / BUDGET_AMOUNT / BASIC_AMOUNT` 중 어떤 amount type을 total/qty 파생의 input으로 허용해야 하는가?
4. `AWARD_TOTAL / CONTRACT_TOTAL`은 item allocation 필드가 없으면 항상 금지하는 것이 맞는가?
5. VAT unknown 상태에서 숫자 자체를 보여주는 것은 안전한가, 아니면 range에서도 제외해야 하는가?
6. official G2B classification을 발견해 다시 검색하는 2-pass/queue 구조에 recall 또는 비용상 결함이 있는가?
7. 동일 공식 분류의 실제 가격을 `Alternative Actual`로 보여주는 것이 C/D 계약과 충돌하지 않는가?
8. #108의 query expansion/key routing 변경 중 이 명세와 충돌하거나 다시 설계해야 할 부분은 무엇인가?
9. 테스트/fixture가 Production 오판 리스크를 충분히 막는가?
10. 이 v1 범위를 더 작게 잘라야 한다면 어떤 단계가 최소 고가치 slice인가?

---

## 19. 리뷰 후 작업 원칙

- 외부 리뷰에서 **Blocker / High**로 지적된 사항을 먼저 반영한다.
- 명세 수정 커밋을 별도로 남긴다.
- 이후 구현 PR을 시작한다.
- 검증하지 못한 live 동작은 `미검증`으로 표시한다.
- 테스트 green을 Production 기능 정상의 대체증거로 사용하지 않는다.
