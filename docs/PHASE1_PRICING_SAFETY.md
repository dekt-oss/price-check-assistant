# Phase 1 — 가격판정 안전계약

작성일: 2026-09-04

## 목적

Phase 0에서 실제 공개가격 근거는 확보했지만 `Condition Completeness=0%`였다. 따라서 Phase 1에서는 **숫자가 관측됐다는 사실**과 **현재 견적과 조건동등 비교가 가능하다는 사실**을 분리한다.

## 1. 가격사용 범위

`ComparisonScope`를 별도 축으로 둔다.

- `observed_only`: 실제·추적 가능한 직접가격 근거지만 VAT·단위·배송·설치·옵션·보증 등 비교조건이 충분히 정규화되지 않음. 관측범위에는 표시 가능, 견적 높고 낮음 판정에는 사용 금지.
- `quote_comparable`: 비교조건까지 명시적으로 검증됨. 현재 견적과 상대비교 가능.
- `reference_only`: 외국시장·중고·유사조건 등 참고자료. 직접 관측범위에서 제외.
- `exclude`: 가격분석 제외.

`ComparisonScope`는 MatchGrade나 EvidenceType을 대체하지 않는다. 직접 관측가격이 되려면 다음을 모두 만족해야 한다.

1. MatchGrade A/B
2. direct EvidenceType
3. KRW
4. 양의 유한 가격
5. `observed_only` 또는 `quote_comparable`

견적 높고 낮음 판정에는 추가로 `quote_comparable`이 필요하다.

현재 Phase 0에서 확보한 G2B/제조사 직접가격은 조건완전성이 0%였으므로 기본적으로 `observed_only`다.

## 2. Observed range와 Quote-comparable range

UI와 서비스는 다음을 구분한다.

- **관측 직접가격 범위**: 공개 source에서 확인한 A/B 직접가격 숫자 범위
- **조건비교 가능 범위**: 거래조건까지 동등비교 가능하다고 검증된 subset

조건비교 가능 근거가 없으면 사용자가 견적을 입력해도 `상단 초과/하단 미만/범위 내`를 출력하지 않는다. 대신 거래조건 검증 부족으로 판정을 보류한다.

## 3. 통화 안전성

현재 PoC의 견적 입력은 KRW 단가다. 따라서 pricing service 자체에서 KRW가 아닌 근거를 직접범위에서 제외한다.

향후 외화 비교가 필요하면 환율 source, 환율 기준일, 환산 provenance를 별도 계약으로 추가한 후 지원한다. 단순 숫자 혼합은 금지한다.

## 4. Confidence의 source independence

같은 source의 반복 거래는 관측 건수를 늘릴 수 있지만 독립적인 교차검증 source는 아니다.

따라서 `높음`은 최소 2개 독립 source가 있어야 한다. 동일 G2B source의 A 거래가 여러 건 존재한다는 이유만으로 high confidence로 승격하지 않는다.

현재 source independence key는 `(source_type, source_name)`이다. 향후 source identity registry가 생기면 안정적인 source ID로 교체한다.

## 5. Mock collector

개발용 mock 가격은 사용자 화면 기본 registry에서 제외한다.

- `build_collectors()` 기본값: mock OFF
- 테스트/개발에서만 `include_mock=True`로 명시적 활성화
- 사용자 검색화면은 synthetic price를 실가격처럼 보여주지 않는다.

## 6. 아직 남은 조건정규화

`quote_comparable` 승격을 자동화하려면 최소 다음 필드를 구조화해야 한다.

- VAT 포함/별도/면세/미상
- 수량 및 단위
- 배송비
- 설치비
- 옵션·부속품 구성
- 보증
- 유지보수/서비스 계약
- 신품/중고/리퍼 등 condition
- 거래/기준일

이 구조화가 완료되기 전에는 현재 공개근거를 일괄 `quote_comparable`로 승격하지 않는다.

## 7. 후속 작업

별도 DB 무결성 PR에서 다음을 처리한다.

1. PriceObservation derivation/provenance version
2. 실데이터 observation의 RawEvidence 연결 강제 정책
3. deterministic observation identity / 중복방지
4. G2B `source_record_id`를 품목 단위 composite external key로 개선

그 다음 실제 G2B search adapter를 사용자 검색 surface에 연결하고 mapping coverage를 확대한다.
