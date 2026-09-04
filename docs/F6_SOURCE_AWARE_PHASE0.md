# F6 — Source-aware Phase 0 검증

## 목적

F4 일괄 검증기를 여러 공개가격 source를 같은 benchmark 계약으로 평가할 수 있는 구조로 확장한다.

핵심은 다음을 분리하는 것이다.

1. **이 source에서 해당 품목을 검증할 준비가 됐는가?** — Mapping Readiness
2. **실제로 source를 평가했을 때 근거가 있었는가?** — Source Hit / Direct Evidence

매핑이 없거나 검증되지 않은 품목은 source miss로 계산하지 않는다.

Phase 0 최종 수치는 `docs/PHASE0_FINAL_REPORT.md`를 기준으로 한다.

## 현재 source adapters

### G2B Shopping

- 네트워크 API source
- 검증된 G2B 세부품명 매핑이 있어야 실행
- 실제 납품요구 단가를 direct evidence로 만들 수 있음
- Phase 0 최종 verified mapping: 4/20

### Manufacturer Public Catalog

- 제조사 공식 페이지에서 사람이 검증한 공개가격 snapshot registry
- 현재 snapshot: 2개
  - GMSR-182
  - ApeosPrint C5570 GK
- `--offline`에서도 평가 가능
- VAT·배송·설치 등 공개되지 않은 조건은 추정하지 않음

## 출력 계약 v2

`phase0-summary.json` schema version은 `phase0-validation-v2`다.

전체 summary와 `source_summaries`에 다음을 기록한다.

- mapping ready products / rate
- attempted pairs
- successful pairs
- source hit pairs / rate
- direct evidence products / rate
- evidence records
- traceability rate
- direct evidence condition completeness
- collector errors / rate
- average elapsed milliseconds

## Source Hit와 Direct Evidence의 차이

Source Hit는 원천 source에 해당 mapping record가 있었음을 뜻한다.

Direct Evidence는 추가로 다음을 만족해야 한다.

- 제품 동일성 A/B
- direct EvidenceType

따라서 source hit가 있어도 exact model이 아니면 direct evidence는 0일 수 있다. 최종 live에서 Sophie와 삼성 노트북이 이 차이를 보여줬다.

## Multi-source 활성화

Multi-source는 adapter 존재만으로 계산하지 않는다. 같은 benchmark에서 2개 독립 source가 실제 성공 평가되고, 두 source 모두 usable A/B/C/D evidence를 제공해야 한다.

2026-09-04 최종 live에서 **ApeosPrint C5570 GK**가 최초 multi-source positive로 재현됐다.

- G2B: exact-model 납품요구 단가 2,981,000원, 3건
- Manufacturer: 공식몰 공개판매가 5,500,000원

관측범위는 2,981,000~5,500,000원이지만 조건차이가 완전히 구조화되지 않았으므로 적정가격 판정으로 사용하지 않는다.

## 최종 Live 결과

Run `33820748853`, 2026-07-14~2026-08-13:

### Aggregate

- Mapping Readiness: **5/20 = 25%**
- Evaluation Coverage: **5/20 = 25%**
- Source Hit: **5/6 = 83.3%**
- Direct Evidence Product: **2/5 = 40%**
- Multi-source Product: **1/5 = 20%**
- Traceability: **100%**
- Condition Completeness: **0%**
- Collector Error: **0%**

### G2B Shopping

- mapping: 4/20
- success: 4/4
- hit: 3/4
- direct evidence products: 1
- evidence records: 3
- errors: 0

### Manufacturer Public Catalog

- mapping: 2/20
- success: 2/2
- hit: 2/2
- direct evidence products: 2
- evidence records: 2
- errors: 0

## 안전성 유지

- API timeout/retry는 설정값을 사용한다.
- retry 소진 transport failure는 `PublicDataClientError`로 감싸 장기 scan에서 window-level incomplete로 기록 가능하다.
- service key는 오류와 로그에서 마스킹한다.
- `totalCount`가 없으면 실제 fetched record 수로 source hit를 판정한다.
- verified/unverified duplicate mapping은 fail-closed 처리한다.
- 비-KRW·NaN·Infinity 제조사 snapshot은 거부한다.
- A/B라도 예산·입찰기초금액은 direct range에 넣지 않는다.

## Phase 0 이후

F6는 완료한다. Phase 1에서 다음을 진행한다.

1. G2B mapping coverage 확대
2. Manufacturer snapshot freshness/가격변경 감지
3. VAT·설치·배송·옵션·보증 조건 구조화
4. G2B 계약정보 source adapter 추가
5. raw evidence와 normalized observation의 장기 provenance 강화
