# Claude 리뷰 요청 — G2B 가격근거 계층화 + 규격/예산 기반 추정 v1

저장소: `dekt-oss/price-check-assistant`

리뷰 대상 브랜치:

`docs/spec-procurement-price-evidence-v1`

기준 `main`:

`f9999ae6ddc3f6e85261ac9892494bbafa772647`

핵심 문서:

`docs/SPEC_G2B_PRICE_EVIDENCE_AND_BUDGET_ESTIMATE_V1.md`

관련 선행 PR:

`#108 Fix G2B key routing and widen quote research to categories and alternatives`

> #108은 리뷰 요청 시점에 아직 최종 CI green/merge 완료로 가정하지 않는다. 현재 repository/PR 상태를 직접 확인하고 판단할 것.

---

## 리뷰 목적

병원 구매담당자가 견적서를 업로드하면 시스템이 나라장터 자료를 이용해 다음을 한 번에 조사하도록 확장하려 한다.

1. 동일제품 실제 납품/계약 단가
2. 같은 공식 품목군의 다른 제조사/모델 실제 단가
3. 동일제품 가격이 부족할 때 규격/품목이 관련된 입찰의 예정단가 또는 예산기반 추정단가
4. 입찰·낙찰·계약의 총액/기초금액 등 단가로 쓸 수 없는 조달 참고정보

핵심 원칙은 **Research는 넓게, 최종 가격판정은 fail-closed**다.

입찰공고의 총예산을 실제 거래단가처럼 섞거나, 대체품 가격을 동일제품 가격범위에 섞으면 안 된다.

---

## 먼저 읽을 것

1. `docs/SPEC_G2B_PRICE_EVIDENCE_AND_BUDGET_ESTIMATE_V1.md`
2. `docs/F1_G2B_SHOPPING.md`
3. `docs/F3_PRODUCT_MATCHING.md`
4. `src/purchase_price/domain.py`
5. `src/purchase_price/schemas.py`
6. `src/purchase_price/services/g2b_market_models.py`
7. PR #108의 전체 diff와 현재 CI 상태

필요하면 다음도 확인한다.

- `src/purchase_price/services/market_research.py`
- `src/purchase_price/services/g2b_unmapped_discovery.py`
- `src/purchase_price/services/g2b_bid_item_enrichment.py`
- `src/purchase_price/ui/market_research.py`
- `src/purchase_price/ui/quote_market_research.py`
- 관련 tests / fixtures

---

## 적대적으로 검토할 핵심 질문

### A. 가격 의미 / Evidence 모델

1. `Actual Exact / Alternative Actual / Budget Estimate / Procurement Context` 4분리가 충분한가?
2. Budget Estimate를 `CollectedPrice` 밖의 별도 projection으로 유지하는 설계가 기존 코드와 잘 맞는가?
3. 기존 `ResearchAmountType`을 재사용하는 데 의미 충돌이 없는가?
4. 예상보다 안전한 더 단순한 데이터 모델이 있는가?
5. 실제 거래단가와 예산값이 어떤 코드 경로에서 다시 섞일 위험이 있는가?

### B. Budget Estimate fail-closed 규칙

다음 규칙을 공격적으로 검증하라.

```text
명시된 item 예정단가
    → item 귀속/field semantics 확인 시 HIGH

single item + 명확한 qty + 귀속 가능한 budget/estimated total
    → total / qty = MEDIUM

multi item / qty unknown / package ambiguity / total attribution unknown
    → BLOCKED
```

특히 다음 edge case를 찾아라.

- `1 SET` 안에 여러 독립 장비 포함
- 본체 1대 + accessory 여러 개
- 옵션/설치/교육/유지보수 포함 총액
- VAT 포함/별도 혼재
- 품목별 수량과 package 수량이 다름
- 동일 공고의 base amount / estimated price / budget가 서로 다른 의미
- amendment/change order
- 낙찰총액/계약총액을 잘못 item 단가로 나누는 경로
- 품목상세는 1개지만 첨부 규격에는 복수 구성품인 경우

### C. 검색 플래너 / 분류 확장

사용자 요구는 모델명을 그대로 검색하는 것이 아니다.

예:

```text
iPhone 17
→ exact model
→ 제조사+모델
→ 일반 품명(스마트폰 등)
→ 나라장터 공식 세부품명/번호
→ 동일분류 다른 모델/제조사
```

검토할 것:

1. 명세의 exact → generic → official classification → alternatives 흐름이 충분한가?
2. #108의 구현이 이 목표에 실제로 도달하는가, 아니면 여전히 curated alias 의존이 큰가?
3. 잘못된 상위 category expansion으로 noise가 폭증할 위험은 어디인가?
4. whitespace/붙여쓰기/한영 alias를 API 요청 단계에서 어떻게 dedupe해야 recall을 잃지 않는가?
5. official classification을 동적으로 발견해 다시 조회하는 queue가 API budget을 비효율적으로 소모하지 않는가?
6. 범용 category resolver를 이번 v1에 넣어야 하는가, 후속으로 빼야 하는가?

### D. 기존 F1/F3 safety contract 회귀

반드시 확인할 것:

- Budget Estimate가 `DIRECT_PRICE_EVIDENCE_TYPES`에 들어갈 가능성
- `assess_prices()`에 Research 값이 유입될 가능성
- C/D/X가 direct range에 들어갈 가능성
- 동일 공식 세부품명이라는 이유만으로 C/D가 과승격되는지
- query expansion이 MatchGrade 근거로 잘못 사용되는지
- quote comparability gate가 우회되는지

### E. UI 오해 가능성

구매담당자가 아래를 혼동할 수 있는지 검토하라.

- 실제 납품단가
- 대체제품 실제 납품단가
- 입찰 예정단가
- 사업예산/수량 파생 추정단가
- 기초금액
- 낙찰총액
- 계약총액

숫자가 많아져도 사용자가 첫 화면에서 다음 질문에 바로 답할 수 있어야 한다.

> 이 견적 1.4억원과 직접 비교해도 되는 가격은 무엇인가?
> 실제 거래가격이 없으면 어떤 참고가격을 쓸 수 있는가?
> 그 참고가격은 얼마나 믿어도 되는가?

---

## 원하는 리뷰 형식

테스트 통과 여부를 나열하는 리뷰는 원하지 않는다.

다음 형식으로 작성하라.

### 1. Verdict

- `APPROVE`
- `APPROVE WITH CHANGES`
- `REDESIGN REQUIRED`

중 하나.

### 2. Findings

각 finding에:

- Severity: `BLOCKER / HIGH / MEDIUM / LOW`
- 문제
- 왜 위험한지
- 구체적 재현/edge case
- 권장 수정안
- 관련 파일/함수

을 작성한다.

### 3. Scope recommendation

- v1에 반드시 포함
- 후속으로 미뤄도 됨
- 삭제/단순화 권고

으로 나눈다.

### 4. Proposed implementation order

실제 PR 단위로 2~5개 정도의 구현 순서를 제안한다.

### 5. Missing tests

현재 명세에 없는 핵심 회귀/UAT를 적는다.

### 6. Questions requiring product-owner decision

기술적으로 결정할 수 없는 것만 별도로 남긴다.

---

## 특히 답을 받고 싶은 최종 질문

1. 이 명세대로 구현을 시작해도 되는가?
2. Budget Estimate를 `Research-only projection`으로 두는 설계가 최선인가?
3. `single-item total / quantity` 허용조건을 더 좁혀야 하는가?
4. 이번 v1에 범용 Category Resolver까지 포함해야 하는가?
5. PR #108은 수정 후 선행 merge하는 것이 나은가, 아니면 본 작업에서 흡수하는 것이 나은가?

가능하면 추상적인 조언보다 **현재 저장소 코드와 실제 failure path를 근거로** 리뷰하라.
