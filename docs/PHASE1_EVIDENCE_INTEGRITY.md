# Phase 1 — Evidence integrity / provenance 계약

작성일: 2026-09-04

## 목적

Claude Code 리뷰의 P2-1/P2-4를 반영한다.

Phase 0에서는 `RawEvidence` 원문 저장 기반을 만들었지만 `PriceObservation.evidence_id`가 nullable이었고, 같은 raw record를 같은 parser 의미로 여러 번 정규화해도 observation 중복을 DB가 막지 못했다. 또한 G2B의 `cntrctDlvrReqNo`는 납품요구 컨테이너 번호라 한 납품요구에 여러 품목이 있을 때 품목-level external identity로 충분하지 않았다.

Phase 1에서는 **원문 → 파생버전 → 정규화 관측**과 **G2B 품목 단위 외부키**를 명시적 계약으로 고정한다.

## 1. PriceObservation provenance

실제 DB에 저장되는 `PriceObservation`은 반드시 `RawEvidence`에 연결한다.

- `evidence_id`: NOT NULL
- `derivation_version`: 어떤 normalization/matching 계약으로 관측을 만들었는지 표시
- `(evidence_id, product_id, derivation_version, evidence_type)` UNIQUE

같은 raw evidence를 같은 파생버전으로 다시 처리하면 기존 observation을 반환한다. parser/matcher 의미가 바뀌어 재처리 결과를 역사적으로 보존해야 하면 새 `derivation_version`을 사용한다.

`EvidenceType`을 unique key에 포함하는 이유는 한 raw record에서 향후 서로 다른 금액 의미가 별도로 파생될 가능성을 허용하기 위해서다.

## 2. ComparisonScope persistence

Phase 1 가격안전 계약의 `ComparisonScope`와 `comparison_note`를 DB observation에도 보존한다.

- observed_only
- quote_comparable
- reference_only
- exclude

메모리상 가격판정과 DB 재조회 가격판정이 다른 의미를 갖지 않도록 한다.

## 3. Legacy migration

기존 `0001` DB에는 RawEvidence 없는 개발/demo observation이 있을 수 있다.

`0002_observation_provenance` migration은 이런 행을 삭제하지 않는다. 대신 원래 raw payload가 존재하지 않았다는 사실을 명시한 **synthetic migration backfill RawEvidence**를 만든다.

- parser_version: `legacy-observation-backfill-v1`
- payload에는 `original raw payload unavailable; synthetic migration backfill` 경고 포함

이 backfill을 실제 원문으로 오인하면 안 된다. 목적은 기존 행의 provenance 결손을 숨기지 않으면서 NOT NULL 계약으로 이동하는 것이다.

마이그레이션 완료 후 임시 server defaults는 제거한다. 신규 observation은 애플리케이션 경로에서 derivation/comparison 의미를 명시적으로 받아야 한다.

## 4. Demo seed

개발용 `seed_demo`도 RawEvidence 없이 PriceObservation을 직접 생성하지 않는다.

synthetic demo payload를 RawEvidence로 먼저 저장한 뒤 일반 observation repository를 통해 파생한다. payload와 comparison note에서 개발용 synthetic 데이터임을 명시한다.

## 5. G2B item-level source_record_id

기존에는 `cntrctDlvrReqNo`를 우선 source record id로 사용했다. 그러나 하나의 납품요구에 여러 `prdctSno`/`prdctIdntNo`가 존재할 수 있어 품목별 식별 충돌 가능성이 있다.

Phase 1부터 가능한 필드를 조합해 외부키를 만든다.

예:

```text
delivery:R26TB02131828|change:00|product:24138760|line:1
```

구성 우선순위:

1. delivery request number 또는 contract number
2. delivery request change order (있을 때)
3. product identification number (있을 때)
4. product line sequence (있을 때)

필드가 없는 옛/다른 operation은 확보된 필드까지만 사용하고 payload hash dedupe 계약을 계속 유지한다.

parser와 raw ingestion이 **같은 `build_g2b_source_record_id()` 함수**를 사용해야 한다. 서로 다른 키 규칙을 중복 구현하지 않는다.

## 6. Historical Ground Truth 호환성

Phase 0의 정적 Ground Truth/보고서에 저장된 과거 source record id는 당시 capture 식별자다. 감사 추적 기록이므로 일괄 재작성하지 않는다.

Phase 1 이후 새 parser/ingestion 결과는 composite item-level id를 사용한다. 필요한 경우 parser/derivation version으로 어느 형식에서 생성된 값인지 구분한다.

## 7. 검증 계약

CI에서 최소 다음을 고정한다.

- 같은 evidence/product/derivation/EvidenceType 반복 저장은 1개 observation
- derivation version 변경 시 새 observation으로 역사 보존
- RawEvidence와 normalized observation source mismatch 거부
- PriceObservation schema의 evidence_id NOT NULL
- 0001 legacy observation을 0002로 실제 upgrade하여 synthetic provenance backfill 확인
- downgrade 시 migration-generated synthetic evidence 정리 및 nullable legacy schema 복구
- 같은 G2B delivery request 안의 서로 다른 product/line이 서로 다른 source_record_id를 가짐
- parser와 raw ingestion 모두 composite source_record_id 사용

## 8. 후속

이 PR은 provenance/identity 기반만 다룬다. 다음 단계는 실제 G2B collector를 사용자 검색 surface에 연결하는 것이다.

별도 후속으로 남기는 항목:

- ~~`_product_class_state`의 단순 substring C 판정 개선~~ (P2-2에서 exact equality로 fail-closed 처리)
- numeric-only raw unit(`182`)의 공식 의미 확인 및 normalized unit 분리
- adaptive date partitioning
- G2B 계약정보 collector
