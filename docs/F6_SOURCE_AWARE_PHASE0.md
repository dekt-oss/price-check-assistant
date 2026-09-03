# F6 — Source-aware Phase 0 검증

## 목적

F4의 G2B 중심 일괄 검증기를 여러 공개가격 source를 같은 benchmark 계약으로 평가할 수 있는 구조로 확장한다.

핵심 질문은 다음 두 가지를 분리하는 것이다.

1. **이 source에서 해당 품목을 검색·검증할 준비가 됐는가?** — Mapping Readiness
2. **실제로 source를 평가했을 때 근거가 있었는가?** — Source Hit / Direct Evidence

매핑이 없거나 검증되지 않은 품목은 source miss로 계산하지 않는다.

## 현재 source adapters

### G2B Shopping

- 네트워크 API source
- 검증된 G2B 세부품명 매핑이 있어야 실행 가능
- `--offline`에서는 실제 API 호출을 하지 않고 `not_run_offline`으로 기록

### Manufacturer Public Catalog

- 제조사 공식 웹페이지에서 사람이 검증한 공개가격 snapshot registry
- 로컬 registry 읽기만 수행하므로 `--offline`에서도 실제 평가 가능
- snapshot이 없는 품목은 `mapping_unverified`
- snapshot의 상업조건이 공개되지 않았으면 VAT·배송·설치 등을 채우지 않음

## 출력 계약 v2

`phase0-summary.json`의 schema version은 `phase0-validation-v2`다.

기존 전체 summary 외에 `source_summaries`를 추가한다.

각 source별로 다음을 기록한다.

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

Source Hit는 원천 source에 해당 mapping의 record가 있었는지를 뜻한다.

Direct Evidence는 그 record가 추가로 다음을 만족해야 한다.

- 제품 동일성 A/B
- direct EvidenceType

따라서 source record는 존재하지만 제조사/모델/규격 검증에서 탈락하면 `source_hit=true`, `direct_evidence_count=0`이 가능하다.

## Offline 의미

`--offline`은 "모든 평가를 건너뛴다"가 아니다.

- 네트워크가 필요한 G2B: 건너뜀
- 로컬에 검증 snapshot이 있는 Manufacturer source: 실제 평가

따라서 offline 결과는 네트워크 source의 성능평가가 아니지만, 이미 확보된 공식 공개가격 snapshot에 대한 실제 제품동일성·근거품질 평가는 포함한다.

## Multi-source 활성화 조건

Multi-source Rate는 단순히 adapter가 코드에 존재한다고 활성화하지 않는다.

최소 2개 독립 source adapter가 실제 `success` 평가를 수행했고, 같은 benchmark 품목에서 2개 source 모두 **사용 가능한 A/B/C/D evidence**를 확보해야 해당 품목을 multi-source evidence로 집계한다. X-only 결과는 multi-source 근거로 인정하지 않는다.

## 현재 기대되는 구조적 변화

F5에서 다음 readiness가 존재한다.

- G2B verified mapping: Sophie, NT960XJG-K72AG, ThinkStation P2 Tower, C5570
- Manufacturer verified snapshot: GMSR-182

서로 다른 5개 benchmark가 최소 한 source에서 verified 상태이므로 aggregate Mapping Readiness는 5개 품목이 된다.

정확한 실행 지표는 CI의 `Phase 0 offline integration check`와 실제 live validation 결과를 source of truth로 사용한다.

## 안전성 유지

- G2B timeout/retry는 설정값을 사용한다.
- API 실패 reason은 service key를 마스킹한 뒤 저장한다.
- `totalCount`가 없으면 실제 fetched record 수로 source hit를 판정한다.
- verified/unverified duplicate mapping은 verified resolver로 fail-closed 처리한다.
- 제조사 catalog의 비-KRW·NaN·Infinity 가격은 거부한다.

## 후속

1. F6 offline 결과 검증
2. G2B live validation에서 4개 verified mapping 실제 source hit 확인
3. G2B와 Manufacturer가 같은 품목에서 근거를 확보하는 사례 확보
4. 공개가격 snapshot freshness 정책 추가
5. 20개 benchmark에서 source별 지원가능 품목군 판단
