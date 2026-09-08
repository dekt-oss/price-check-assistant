# 관리부 시장가격조사기 — Procurement Coverage / Spec Intelligence 작업지시서

기준일: 2026-09-08  
Repository: `dekt-oss/price-check-assistant`  
기준 main: `bf53a40e0d2086cf72b00f201eede150a1fb374a` (PR #114 포함)  
Production: `https://bp-price-research.streamlit.app/`

## 0. 목적

병원 구매담당자가 견적 PDF를 올렸을 때, 타 기관 공개 조달 구매사례와 공식 제품·규격·옵션 정보를 최대한 회수하되 서로 다른 제품·구성·총액을 동일제품 단가로 오인하지 않도록 검색·식별·비교 구조를 개선한다.

이번 계획의 핵심은 **검색량을 무작정 늘리는 것**이 아니다.

- APC-30D / CO₂ Incubator: 실제 관련 공개자료를 놓칠 가능성이 큰 **Recall 문제**
- Maquet FLOW-C: 후보는 많지만 동일모델·경쟁사·옵션/패키지를 구분하지 못하는 **Precision / Configuration 문제**

두 문제를 같은 알고리즘으로 해결하지 않는다.

## 1. 확인된 현재 문제

### P0 즉시 수정 대상

1. 사전규격 PPSSrch 요청이 `bfSpecNm`을 사용하며 공식 계약의 품명 검색 필드와 불일치 가능성이 있다.
2. 계약 PPSSrch의 입찰번호 연결 요청이 `bidNtceNo`를 사용하며 공식 계약의 `ntceNo`와 불일치한다.
3. UI 조회기간은 1/2/3/5년이지만 입찰·낙찰·사전규격은 `min(lookback_days, 90)`으로 최대 90일만 조회한다.
4. 입찰 seed가 없으면 품목상세·계약·과정통합을 실제 호출하지 않고도 `SUCCESS_0`로 표기한다.
5. catalog는 검색 전 resolver가 아니라 이미 발견한 쇼핑 후보 최대 3개의 품목속성 사후 보강에 머문다.
6. `CO₂ Incubator(Water Jacket)`가 `CO Incubator`로 손상되고 `Water Jacket`이 검색/규격정보에서 소실된다.
7. 모델 substring 로직으로 `FLOW-C20` 또는 accessory 문구가 `FLOW-C` 동일모델 후보가 될 수 있다.
8. 옵션은 `포함`, 보증은 `무상` binary state가 먼저 일치하면 세부값이 달라도 MATCH가 될 수 있다.
9. 공고 품목의 원시 `prdctSno`, `prdctSpecNm`, 품목식별번호·기관·수량·단위·납품조건 등 provenance가 충분히 보존되지 않는다.
10. `추가 웹 조사`는 실제 자동 검색이 아니라 Google 검색 링크 생성이다.

## 2. 절대 유지할 Safety Contract

아래 규칙은 모든 PR의 non-regression contract다.

- 동일모델과 대체품 가격을 한 band로 합치지 않는다.
- 같은 공식분류를 규격동등으로 판단하지 않는다.
- 공식분류 미확정 Research 후보를 `assess_prices()`에 넣지 않는다.
- 입찰 추정가격, 사전규격 예산, 낙찰총액, 계약총액을 제품 단가로 사용하지 않는다.
- 총액 ÷ 수량으로 임의 단가를 생성하지 않는다.
- API 실패 / 미실행 / 부분조회 / 완전조회 0건을 구분한다.
- 정보 부재는 `미확인`이며 자동 `불일치`로 판단하지 않는다.
- 옵션 금액을 추정 차감하여 본체가격을 만들어내지 않는다.
- API resolver가 돌려준 분류/품목 후보는 자동 verified mapping으로 저장하지 않는다.

## 3. 목표 구조

```text
Quote PDF
  ↓
Quote Intelligence
  ↓
Canonical Product Resolver
  ↓
Official PPS Classification / Product ID Resolver
  ↓
Adaptive Retrieval
  ├─ Exact product / same model
  ├─ Shopping procurement history
  ├─ Delivery request detail / MAS / unit-price products
  ├─ Bid / award / prespec
  ├─ Independent contract / contract detail
  ├─ Lifecycle links
  └─ Conditional Web fallback
  ↓
ProcurementProductFingerprint
  ↓
Spec / Option Comparator
  ↓
Evidence Buckets
  ↓
Safety Gate
  ↓
Price Assessment
```

## 4. 구현 순서

# P0 — 검색 의미, Recall, 즉시 오판 방지

### P0-01 공식 API 요청계약 수정

목적:
- 사전규격 품명 검색 파라미터를 공식 계약과 일치시킨다.
- 계약 입찰번호 연결 파라미터/응답 linking key를 공식 계약과 일치시킨다.

변경 후보:
- `src/purchase_price/services/g2b_market_sources.py`
- `src/purchase_price/services/g2b_contract_research.py`
- 관련 request-contract tests / live probe

테스트:
- 잘못된 필드가 outgoing params에 존재하지 않음을 단언.
- `ntceNo` round-trip 보존.
- API error가 `success_0`로 변환되지 않음.

UAT 종료조건:
- known-positive 사전규격/계약 식별자로 live 응답 확인.
- 서비스 미승인/권한오류면 `미검증`으로 종료하고 0건으로 보고하지 않음.

### P0-02 조사 완전성 상태모델

목적:
- `SUCCESS_0`를 "실제로 전체 조회 후 0건"에만 사용한다.
- seed 부족으로 미실행한 후속 source를 별도 상태로 표시한다.

필요 상태:
- success
- complete_zero
- partial
- failure
- not_configured
- not_authorized
- not_run / skipped_no_seed

변경 후보:
- `g2b_market_models.py`
- `g2b_bid_item_enrichment.py`
- `g2b_contract_enrichment.py`
- `g2b_lifecycle_enrichment.py`
- `ui/g2b_market_research.py`

UAT 종료조건:
- 입찰 seed 0일 때 계약/품목상세/과정통합이 `0건`이 아니라 `미조회`로 보임.
- partial/truncated와 완전 0건이 UI에서 구분됨.

### P0-03 모델·옵션·보증 즉시 안전수정

목적:
- 동일모델 Research band에 명백히 다른 모델/액세서리가 들어오는 것을 막는다.
- 옵션/보증 세부값을 binary state보다 먼저 또는 함께 비교한다.

필수 금지 테스트:
- `FLOW-C != FLOW-C20`
- `FLOW-C != FLOW-C accessory`
- `Desflurane vaporizer 포함 != Sevoflurane vaporizer 포함`
- `무상 3년 != 무상 1년`
- `missing != conflict`

변경 후보:
- `g2b_unmapped_discovery.py`
- `quote_condition_comparison.py`
- `market_price_research.py`
- UI warning/caption

### P0-04 Canonical / Official PPS Resolver

목적:
- 견적 원문을 손상하지 않고 한글/영문 품명과 공식 세부품명/품목식별번호 후보를 검색 전에 확보한다.

규칙:
- `CO₂ → CO2`처럼 의미 보존 정규화.
- 괄호 안 `Water Jacket`은 제거하지 않고 specification token으로 보존.
- API 결과는 `RESEARCH_CANDIDATE`.
- 사용자 확인은 session scope.
- `data/g2b_product_mappings.csv` 자동 기록 금지.

활용 후보 operation:
- `getPrdctClsfcNoUnit10Info02`
- `getThngPrdnmLocplcAccotListInfoInfoPrdlstSearch02`
- `getThngPrdnmLocplcAccotListInfoInfoPrdnmSearch02`

UAT:
- APC-30D가 `CO Incubator` 1개 검색어로 끝나지 않음.
- `이산화탄소배양기` 등 공식분류 후보를 근거와 함께 제시하되 자동 확정하지 않음.

### P0-05 코드/ID 기반 Targeted Shopping + 납품 경로

목적:
- 세부품명 문자열 substring 중심에서 official code / product ID 중심 검색으로 전환.
- 실제 기관·수량·단가·단위가 있는 구매사례를 구조적으로 보존.

우선순위:
1. `getSpcifyPrdlstPrcureInfoList` code/ID 조건
2. `getDlvrReqDtlInfoList`
3. MAS / 일반단가 / 제3자단가 상품

새 source는 필드 의미·중복키·change order 검증 전 Research-only 유지.

### P0-06 독립 계약검색 + 조회기간 정책

목적:
- 입찰 seed가 없어도 계약/납품 자료를 검색할 수 있게 한다.
- UI의 1/2/3/5년 선택과 실제 source 기간을 일치시킨다.
- 항상 최대검색하지 않고 근거 부족 시에만 단계적으로 확장한다.

권장 정책:
- 1차: 짧은/표적 검색
- 부족: 1년
- 여전히 sparse: 3년
- 5년은 low-frequency 장비에서 명시적 확장

### P0-07 Raw provenance 보존

최소 보존 필드:
- institution
- supplier
- product_id
- detail_product_code
- item_sequence
- original_specification
- quantity
- unit
- original unit price / amount type
- delivery condition
- record/change order
- source URL

목적:
- 같은 공고 안의 서로 다른 품목을 덮어쓰지 않고 P1 fingerprint의 재료를 확보한다.

# P1 — Quote Spec / Option Intelligence

### P1-01 Quote Configuration

실제 견적 PDF에서 다음을 원문 근거와 함께 구조화한다.
- 제조사 / 모델 / 본체
- core specifications
- gas mixer / ventilation / gas module / monitoring
- vaporizer 종류·개수
- auxiliary O₂ / suction
- 설치
- warranty 기간·비용
- accessories / consumables

기본 탑재인지 옵션인지 근거 없이는 추정하지 않는다.

### P1-02 Procurement Product Fingerprint

조달 후보에서:
- 제조사
- 모델
- 분류/품목식별번호
- 규격 속성
- 수량/단위
- 패키지/옵션 신호
- 계약 line item
- 납품조건
- 첨부 규격 근거
을 한 구조에 결합한다.

### P1-03 제품관계 × 구성상태 2축

제품관계:
1. Exact product
2. Same model
3. Same manufacturer, other model
4. Comparable competitor
5. Same official category only
6. Related research candidate

구성상태:
- matched
- differs
- unknown

동일모델도 구성상태는 unknown일 수 있다.

### P1-04 본체/패키지 가격 UI

별도 표시:
- 본체끼리 비교 가능한 사례
- 동일모델 구성 미확인
- 동일모델 다른 구성
- 경쟁사 동급
- 같은 공식분류만 일치

옵션 차감 추정은 금지한다.

### P1-05 조건부 Web Research

조달 근거가 부족할 때만:
- 공식 제조사
- 병원/대학/공공기관 구매문서
- 공급업체 공개 구성/가격 문서
을 자동 탐색한다.

검색 snippet은 근거가 아니며 URL·수집일·원문 위치·가격 종류·통화·VAT·단위·구성을 보존한다.

# P2 — 성능·확장·운영 Evidence

- adaptive retrieval planner
- cache / 병렬화
- 외자장비 경로
- 기관/공급자 resolver
- 장기 파일데이터 index
- Production 배포 SHA/trace
- known-positive / known-negative / sparse / bundled / partial / error UAT
- recall / precision / unknown-rate / p50 / p95 latency 지표

## 5. Golden UAT Cases

### APC-30D / CO₂ Incubator / ASTEC / 8,000,000원

성공조건:
- 관련 공식 분류·구매사례를 발견할 수 있음.
- 관련품과 동일 APC-30D 실거래를 구분.
- 동일모델이 없으면 `동일모델 단가 미확인`으로 종료.
- 조회기간·source별 complete/partial/not-run 상태가 보임.

실패조건:
- 관련 CO₂ incubator 가격을 APC-30D 동일모델 가격으로 승격.

### Maquet FLOW-C / 66,000,000원

성공조건:
- FLOW-C / 다른 Maquet 모델 / 경쟁사 / 같은 분류만 일치가 분리.
- FLOW-C20 및 accessory가 동일모델 band에 들어가지 않음.
- vaporizer / gas module / monitoring / 설치 / 3년 보증이 `일치/차이/미확인`으로 표시.
- 본체/패키지 비교가능성이 별도 표시.

실패조건:
- 후보 수만 줄이고 제품/구성 identity가 그대로 불명확.

## 6. PR 운영 규칙

- 각 PR은 하나의 관심사만 변경한다.
- PR 본문에 목적 / 변경파일 / 테스트 / live UAT / 미검증을 명시한다.
- live workflow는 `workflow_dispatch` 수동 실행 원칙을 유지한다.
- 테스트 통과만으로 기능 완료를 선언하지 않는다.
- 실제 API 미승인·timeout·외부 장애는 기능 0건과 분리한다.
- 사용자 승인 없이 자동 merge하지 않는다.

## 7. 작업 시작 순서

1. P0-01 공식 request contract 수정
2. P0-02 complete/partial/not-run 상태 분리
3. P0-03 모델·옵션·보증 즉시 안전수정
4. P0-04 official resolver
5. P0-05 targeted shopping/delivery
6. P0-06 independent contract/lookback
7. P0-07 provenance
8. APC/FLOW golden UAT 후 P1 진입

이 문서는 2026-09-07~08 두 차례의 조달 coverage 감사와 최신 `main` 코드 재검증을 통합한 실행 기준이다. 구현 중 공식 API 계약이나 live 결과가 문서와 다르면 **실측/공식 계약을 우선**하고 차이를 PR에 기록한다.
