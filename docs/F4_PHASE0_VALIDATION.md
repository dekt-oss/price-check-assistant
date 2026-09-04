# F4 — Phase 0 일괄 검증 리포트 계약

## 목적

20개 benchmark를 한 번에 실행하여 **공개 가격조사 시스템이 실제로 어디까지 가능한지** 정량화한다.

높은 점수를 만드는 것이 목적이 아니다. 공개 근거가 없거나 source mapping이 검증되지 않았거나 동일모델 가격이 없으면 그 상태를 그대로 `mapping_unverified`, `근거 없음`, `source miss` 등으로 구분해 보고한다.

Phase 0 최종 결과와 해석은 `docs/PHASE0_FINAL_REPORT.md`를 Source of Truth로 한다.

## 핵심 원칙

1. 검증되지 않은 G2B 세부품명 매핑을 자동 추정하지 않는다.
2. `mapping_unverified`는 `source miss`로 계산하지 않는다.
3. 실제 source 평가가 성공한 품목만 Source Hit / Direct Evidence의 성능 분모에 들어간다.
4. collector 오류는 source miss와 별개로 계산한다.
5. A/B 제품 동일성과 direct `EvidenceType`을 모두 만족해야 Direct Evidence다.
6. C/D/X는 Direct Evidence에 들어가지 않는다.
7. Multi-source는 2개 독립 source가 실제 성공 평가되고 같은 품목에 usable evidence가 있을 때만 집계한다.
8. 확인할 수 없는 VAT·설치·배송·옵션·보증 조건을 임의로 채우지 않는다.

## 실행

### Live

```bash
python -m purchase_price.scripts.run_phase0_validation \
  --begin-date 20260714 \
  --end-date 20260813
```

`DATA_GO_KR_SERVICE_KEY`는 환경변수/Secret으로만 주입한다.

### Offline readiness

```bash
python -m purchase_price.scripts.run_phase0_validation --offline
```

Offline에서는 G2B 네트워크를 호출하지 않지만, 로컬에 검증 snapshot이 있는 Manufacturer source는 실제 평가한다.

## 산출물

- `phase0-products.csv`
- `phase0-summary.json`

각 source-product row에 다음을 기록한다.

- mapping 상태
- evaluation 상태
- source hit 여부
- 조회 record 수 / reported total
- retained evidence 수
- A/B direct evidence 수
- C/D reference evidence 수
- traceable evidence 수
- condition-complete direct evidence 수
- 실행시간
- 근거부족/오류 사유

## 지표 계약

### Mapping Readiness Rate

`최소 1개 source에서 명시적으로 verified mapping/snapshot이 있는 benchmark / 전체 benchmark`

### Evaluation Coverage Rate

`최소 1개 source를 성공 평가한 benchmark / 전체 benchmark`

### Source Hit Rate

`source record가 1건 이상 있었던 성공 source-product 평가 / 성공 source-product 평가`

### Direct Evidence Product Rate

`A/B + direct EvidenceType 근거가 최소 1건 있는 품목 / 성공 평가된 품목`

Direct EvidenceType은 실제 계약/쇼핑계약/납품요구 단가와 검증된 공개판매가다. 예산·입찰 기초금액은 제외한다.

### Multi-source Product Rate

`2개 이상 독립 source에서 usable A/B/C/D evidence를 확보한 품목 / 성공 평가 품목`

### Traceability Rate

`source name + source record id + source URL 또는 original title을 가진 evidence / 전체 evidence`

### Condition Completeness Rate v0

Direct Evidence 중 다음이 모두 있는 경우만 complete로 본다.

- quantity
- unit
- transaction date
- VAT status
- conditions

설치·배송·옵션·보증이 별도 필드로 구조화되면 지표 버전을 올린다.

### Collector Error Rate

`collector error 평가 / 실제 시도한 source-product 평가`

## Phase 0 최종 실측

2026-09-04, 고정기간 2026-07-14~2026-08-13, live run `33820748853` 기준:

- Benchmark: 20
- Mapping Readiness: **5/20 = 25.0%**
- Evaluation Coverage: **5/20 = 25.0%**
- Source Hit: **5/6 = 83.3%**
- Direct Evidence Product Rate: **2/5 = 40.0%**
- Multi-source Product Rate: **1/5 = 20.0%**
- Traceability: **100%**
- Condition Completeness: **0%**
- Collector Error: **0%**

G2B verified mapping은 4개이며, Manufacturer official price snapshot은 2개다. C5570이 두 source에 겹치므로 aggregate Mapping Readiness는 5개다.

## 종료 해석

F4는 완료됐다. 결과는 공개정보가 모든 품목에서 충분하다는 뜻이 아니라, **지원 가능한 source/품목과 근거부족 영역을 정량적으로 구분할 수 있는 실행 계약이 완성됐음**을 뜻한다.

Phase 1에서는 G2B mapping 확대, 제조사 공식가격 freshness/조건 구조화, G2B 계약정보 collector 추가를 우선한다.
