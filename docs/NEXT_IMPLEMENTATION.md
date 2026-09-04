# 다음 구현 순서

Phase 0는 2026-09-04 종료했고, 2026-09-04 기준 아래 기능이 `main`에 반영됐다.

- G2B Shopping/납품 verified exact-model 검색
- G2B 계약정보 근거 조회
- A/B/C/D/X fail-closed 매칭 + 명백한 숫자·단위 규격충돌 차단
- 외부 가격조건 구조화
- 출처별 성공/0건/실패 상태 분리
- Excel `.xlsx/.xls` + 텍스트 PDF 견적 품목 추출
- MFDS 품목/형명 exact identity, 업허가 업체, 공급사 우선순위
- UDI-DI exact 조회
- Safety 수동 공식확인 경로와 상태계약

상세 상태는 `docs/V2_IMPLEMENTATION_STATUS.md`를 기준으로 한다.

## 현재 최우선 — 견적조건을 실제 비교계약까지 연결

최종 사용자 가치의 핵심은 아래 흐름을 완성하는 것이다.

```text
견적서
→ 제품 identity
→ 견적단가 + 견적조건
→ 외부 직접가격 + 외부조건
→ 조건 일치/불일치/미확인
→ quote_comparable 여부
→ 현재 견적 위치 또는 판정보류
```

### P1. 견적 상업조건 추출

현재 브랜치 `feat/quote-commercial-conditions`에서 진행한다.

추출 대상:
- VAT
- 배송/운송
- 설치
- 옵션/부속품/구성
- 보증/무상보증
- 유지보수/서비스계약
- 기타조건

원문에 명시되지 않은 조건은 추정하지 않는다.

### P2. 견적조건 ↔ 외부 가격조건 comparator

P1 완료 후 바로 진행한다.

목표 상태:
- `match`: 조건이 명시적으로 동일
- `conflict`: 조건이 명시적으로 상충
- `unknown`: 한쪽 또는 양쪽 근거가 부족

`quote_comparable` 자동 승격은 최소한의 필수조건이 모두 명시적으로 맞는 경우에만 허용한다.
명시율이 높다는 이유만으로 승격하지 않는다.

## P3. 근거 최신성(freshness)

- 거래일 우선, 없으면 검증/수집일 사용
- source 유형별 오래된 근거 경고
- Manufacturer public snapshot 재검증 예정일 표시
- 오래된 근거를 최신가격으로 표현하지 않음
- 신뢰도 계산에 최신성 신호를 추가하되 source 독립성 원칙 유지

## P4. provenance 일관화

G2B 계약정보를 포함한 모든 신규 source에 아래를 일관되게 둔다.

- public allow-list raw payload
- canonical JSON
- SHA-256 fingerprint
- source record id
- original/detail URL
- normalized observation 연결

서비스키·요청 URL의 secret query·병원 내부자료는 저장하지 않는다.

## P5. 실사용 E2E 검증

- 대표 제품군별 검색
- 비식별 실제 또는 대표 견적 `.xlsx/.xls/.pdf`
- 여러 공급조건이 포함된 견적
- G2B hit / 0건 / API 실패 각각 검증
- MFDS exact / ambiguous / inactive 각각 검증
- 조건 일치 / 충돌 / 미확인 각각 검증

기능 CI와 실사용 검증을 구분한다.

## 외부 계약 확보 즉시 진행

### Safety RED 자동조회

식약처 회수·판매중지정보의 공식 operation/request parameter를 확보한 뒤에만 구현한다.

- exact 모델/허가번호 matching
- hit 시 가격영역보다 우선하는 RED 경고
- 0건과 API 실패 분리
- `검색결과 없음=안전` 표현 금지
- 자동 구매중단 판단 금지

### 모델명 → UDI/상세 identity

공식 모델 검색 request contract가 확보되면 구현한다.
현재 UDI-DI를 알고 있는 경우의 exact 조회만 자동화되어 있다.

## 이후 source 확대

- G2B verified 세부품명 mapping coverage 확대
- 제조사 official price freshness/변경감지
- 신뢰 가능한 B2B/유통/일반 공개가격 source adapter
- 제조사 공식 총판/파트너 provenance

## 최종 UI 통합

기능이 먼저 완성된 뒤 진행한다.

최종 사용자 화면 목표:

```text
구매검토 1화면
├─ 직접 검색
└─ 견적서 업로드
      ↓
identity → Safety → 가격 → 조건비교 → 경쟁/공급사 → 상세근거
```

기존 개발용 분리 페이지는 parity/AppTest 후 제거한다.

## 내부 이식

Public PoC의 실제 업무효과가 확인되고 승인된 뒤 진행한다.

- 본원 구매단가 Excel import부터 검토
- PostgreSQL에 내부 observation 별도 축적
- ERP 직접연계는 후순위
- 진료재료/간납단가는 내부 단가 승인 이후 별도 확장
