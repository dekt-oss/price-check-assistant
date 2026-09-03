# F4 — Phase 0 일괄 검증 리포트 계약

## 목적

20개 benchmark를 한 번에 실행하여 **공개 가격조사 시스템이 실제로 어디까지 가능한지** 정량화한다.

이 단계의 목적은 높은 점수를 만드는 것이 아니다. 공개 근거가 없거나, G2B 표준 세부품명 매핑이 아직 검증되지 않았거나, 동일모델 가격이 없으면 그 상태를 그대로 `not_evaluated` 또는 `근거 없음`으로 보고한다.

## 핵심 원칙

1. 검증되지 않은 G2B 세부품명 매핑을 자동 추정하지 않는다.
2. `mapping_unverified`는 `source miss`로 계산하지 않는다.
3. 실제 API 호출이 성공한 품목만 Source Hit / Direct Evidence의 분모에 들어간다.
4. collector 오류는 source miss와 별개로 계산한다.
5. A/B 제품 동일성과 직접가격 `EvidenceType`을 모두 만족해야 Direct Evidence다.
6. C/D/X는 Direct Evidence에 들어가지 않는다.
7. source가 하나뿐일 때 Multi-source Rate를 0%로 만들지 않고 `N/A`로 둔다.
8. 확인할 수 없는 조건을 임의로 채우지 않는다.

## 실행

### Live

로컬 `.env` 또는 배포 Secret에 `DATA_GO_KR_SERVICE_KEY`가 있어야 한다.

```bash
python -m purchase_price.scripts.run_phase0_validation
```

기본 조회기간은 실행일 포함 최근 31일이다.

기간을 고정하려면:

```bash
python -m purchase_price.scripts.run_phase0_validation \
  --begin-date 20260714 \
  --end-date 20260813
```

### Offline readiness

외부 API를 호출하지 않고 현재 benchmark / mapping 준비상태와 출력계약만 검증한다.

```bash
python -m purchase_price.scripts.run_phase0_validation --offline
```

Offline 결과는 Source Hit나 Direct Evidence 성능값으로 사용하지 않는다.

## 산출물

기본 경로:

- `artifacts/phase0-validation/phase0-products.csv`
- `artifacts/phase0-validation/phase0-summary.json`

### 품목별 CSV

각 benchmark × source 단위로 다음을 기록한다.

- mapping 상태
- evaluation 상태
- source hit 여부
- 조회한 record 수
- API reported total count
- retained evidence 수
- A/B direct evidence 수
- C/D reference evidence 수
- traceable evidence 수
- condition-complete direct evidence 수
- 실행시간
- 근거부족/오류 사유

## 지표 정의

### Evaluation Coverage Rate

`성공적으로 실제 source 평가를 완료한 benchmark 수 / 전체 benchmark 수`

현재 G2B 매핑 미검증 품목이 많으면 이 지표가 낮게 나오는 것이 정상이다.

### Source Hit Rate

`공개 source가 1건 이상을 보고한 성공 평가 / 성공 source-product 평가`

`mapping_unverified`와 collector error는 분모에서 제외한다. 오류율은 별도 지표로 본다.

### Direct Evidence Product Rate

`A/B + direct EvidenceType 근거가 최소 1건 있는 품목 / 성공 평가된 품목`

Direct EvidenceType:

- contract unit price
- shopping contract unit price
- delivery order unit price
- public sale price

### Multi-source Product Rate

`2개 이상 독립 source에서 evidence를 확보한 품목 / 성공 평가 품목`

현재 source adapter가 G2B Shopping 하나뿐이면 **N/A**다.

### Traceability Rate

`source name + source record id + source URL 또는 original title을 가진 evidence / 전체 evidence`

### Condition Completeness Rate v0

현재 normalized schema에는 설치비·배송비·옵션·보증을 개별 필드로 분리하지 않았다.

따라서 v0에서는 Direct Evidence 중 다음이 모두 있는 경우만 complete로 본다.

- quantity
- unit
- transaction date
- VAT status
- conditions

이는 보수적인 임시 정의다. 향후 install/shipping/options/warranty 필드가 구조화되면 지표 버전을 올린다.

### Collector Error Rate

`collector error 평가 / 실제 시도한 source-product 평가`

## 현재 known limitation

2026-09-03 기준 G2B mapping registry에서 명시적으로 verified인 benchmark는 현재 2개다.

- Sophie → 인공호흡기
- NT960XJG-K72AG → 노트북컴퓨터

나머지는 표준 세부품명/번호를 검증하기 전까지 자동 실행하지 않는다.

또한 실제 Ground Truth 10건은 현재 모두 X이므로 direct-match precision/recall은 아직 N/A다. F4 리포트는 이 상태를 숨기지 않고 Evaluation Coverage와 Direct Evidence 결과로 그대로 드러내야 한다.

## 다음 확장

1. verified G2B mapping 확대
2. G2B 계약정보(F2) source adapter 연결
3. 제조사/공개판매가격 source 연결
4. Multi-source Rate 활성화
5. 조건필드 구조화 및 Condition Completeness v1
6. 20개 benchmark 반복 실행 결과를 PoC 지원범위 결정 근거로 사용
