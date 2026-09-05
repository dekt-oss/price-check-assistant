# Live UAT 실행 가이드

기준일: 2026-09-05

## 1. 목적

일반 CI green과 실제 외부 API 성공을 분리해 검증한다.

이 문서의 live workflow는 모두 `workflow_dispatch` 수동 실행만 허용한다. push/PR에서 외부 API를 자동 호출하지 않는다.

## 2. Secret 위치는 서로 다르다

Streamlit Community Cloud의 **App Secrets**와 GitHub Actions의 **Repository Secrets**는 별도 저장소다.

Production Streamlit에서 API가 동작하더라도 GitHub Actions workflow에 같은 secret이 자동 전달되지 않는다.

GitHub Actions live 검증을 실행하려면 repository Actions secret에 필요한 키가 별도로 있어야 한다.

권장 변수:

- G2B: `G2B_SERVICE_KEY`
- MFDS: `MFDS_SERVICE_KEY`

하위호환:

- `DATA_GO_KR_SERVICE_KEY`

애플리케이션과 live workflow 모두 source-specific key를 우선한다. source-specific key가 없을 때만 legacy common key를 사용할 수 있다.

secret 값은 로그/문서/artifact에 출력하지 않는다.

## 3. G2B Live Smoke

Workflow: `.github/workflows/g2b-live-smoke.yml`

목적:

- 조달청 특정품목조달내역 공식 operation의 인증/통신 확인
- API failure와 정상 response를 구분

입력:

- `detail_product_name`
- `begin_date`
- `end_date`

주의:

- 성공은 해당 request가 정상 처리됐다는 의미다.
- 결과 0건이어도 API 호출 성공일 수 있다.
- 이 smoke 자체가 exact 제품가격 확보를 의미하지 않는다.

## 4. Phase 0 Live Validation

Workflow: `.github/workflows/phase0-live-validation.yml`

목적:

- verified G2B mapping에 대해 실제 live 수집 경로 검증
- 결과를 artifact로 저장

주요 결과:

- source hit
- direct evidence
- traceability
- collector error

일반 CI의 offline Phase 0 결과와 혼동하지 않는다.

## 5. G2B Ground Truth Capture

Workflow: `.github/workflows/g2b-ground-truth-capture.yml`

목적:

- `sample`: 사람이 검토할 bounded candidate 표본
- `scan`: 날짜창별 exact-model candidate 조사

자동 MatchGrade 승격 근거로 사용하지 않는다. 사람이 원문을 확인하기 위한 조사 artifact다.

## 6. MFDS Live Validation

Workflow: `.github/workflows/mfds-live-validation.yml`

공식 request 계약이 코드에서 확인된 범위만 사용한다.

- 모델/형명정보: `PRDLST_NM` 품목명 조회 후 서버 응답 안에서 exact 모델 local filter
- 업허가 업체: `Entrps` 업체명 조회

모델명을 공식 API의 존재하지 않는 server-side filter로 보내지 않는다.

### expectation

#### `api-only`

공식 API 호출 자체의 성공/0건/실패를 확인한다.

0건은 실패가 아니며 `success_0`으로 기록한다.

#### `exact-active`

사용자가 입력한 모델명이 공식 품목 조회 결과 안에서 exact match되고:

- 서로 다른 복수 permit로 ambiguous하지 않으며
- 취소·취하 상태가 없고
- 수출전용이 아닌 exact record가 존재하는지 확인한다.

#### `exact-ambiguous`

동일 exact 모델명이 서로 다른 복수 permit number에 연결되는 known sample을 검증한다.

이 결과는 자동 identity 연결 금지 케이스다.

#### `exact-inactive`

exact 모델은 확인되지만 exact records가 모두 취소·취하 또는 수출전용인 known sample을 검증한다.

이 결과는 국내 신규구매 후보 자동승격 금지 케이스다.

### artifact

`mfds-live-validation/report.json`

포함:

- API 성공/0건 상태
- exact match 수
- ambiguous 여부
- active exact 수
- inactive/export exact 수
- 선택적으로 업체 업허가 조회 상태

포함하지 않음:

- API key
- serviceKey query
- 내부 구매자료
- 회수·판매중지 자동판정

## 7. Controlled UAT와 연결

MFDS live workflow는 Controlled UAT 중 다음 케이스의 실제 검증 기반이다.

- UAT-04: `exact-active`
- UAT-14: `exact-ambiguous`
- UAT-15: `exact-inactive`

단, UAT-14/15에는 실제 공식 응답으로 확인된 known sample이 필요하다. 적절한 표본을 확보하지 않은 상태에서 임의 모델/permit을 만들어 성공으로 기록하지 않는다.

## 8. Safety 경계

이 live validation은 **식약처 등록 identity와 업허가 상태** 검증이다.

다음을 의미하지 않는다.

- 회수 없음
- 판매중지 없음
- 안전함
- 구매 적합

회수·판매중지 자동 adapter는 공식 operation/request parameter 계약을 확보하기 전까지 별도 외부차단 상태를 유지한다.

## 9. Live 결과 기록 원칙

각 실행에 대해 최소 다음을 기록한다.

```text
workflow / run id
실행일
입력 품목/모델 (공개 제품정보만)
API status
0건인지 실패인지
exact identity status
ambiguous / inactive 여부
artifact 존재 여부
검증자 메모
```

GitHub Actions 성공 자체가 Production Streamlit UI 성공을 의미하지 않는다. Production 브라우저 smoke는 별도로 수행한다.
