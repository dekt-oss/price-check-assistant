# Track B Historical → Rolling Acceptance

## 목적

Track B의 1년 역사 수집이 끝난 뒤 rolling 7-day 수집으로 실제 전환됐는지
GitHub Actions가 자동으로 판정한다.

이 감사는 새 데이터를 수집하지 않는다. R2 operational state와 serving-index pointer를
읽어 현재 상태만 검증한다.

## 상태

`audit_track_b_transition`은 다음 상태를 구분한다.

- `HISTORICAL_IN_PROGRESS`
  - 역사 수집 진행 중
  - 정상 진행 상태이며 실패가 아님
- `HISTORICAL_COMPLETE_WAITING_FIRST_ROLLING`
  - 5,208 code 역사 수집 완료
  - 아직 첫 rolling window를 시작하지 않음
- `ROLLING_STARTED`
  - 첫 rolling window가 고정되어 수집 진행 중
  - 전환 시작 확인 상태
- `ROLLING_ACCEPTED`
  - rolling cycle이 최소 1회 완주했고
  - `rolling_covered_through`가 역사 종료일 이후로 실제 전진
  - Issue #157의 핵심 전환 acceptance 충족

## Fail-closed invariant

다음은 즉시 실패한다.

1. `backfill_complete=true`인데 historical cursor가 `5208/1`이 아님
2. historical 완료 전 rolling window가 열림
3. rolling cycle 완료 수가 있는데 covered-through가 역사 종료일을 넘지 못함
4. serving-index sync 후 pointer cursor가 historical cursor보다 뒤처짐
5. serving-index sync 후 pending raw object가 남음
6. pipeline state 또는 serving pointer 구조가 손상됨

## Workflow 연결

`Track B R2 Serving Index`의 Production sync가 끝난 뒤 자동 실행한다.

`Track B Daily Backfill → R2 Serving Index → transition audit`

따라서 매일 scheduled 수집이 진행될 때 별도 사람이 로그를 읽지 않아도
historical 잔여 code, rolling window, rolling cursor, covered-through, cycle count,
serving sync 상태가 artifact로 남는다.

Artifact:

`artifacts/track-b-daily/transition-audit.json`

## 현재 해석 규칙

역사 수집 완료 자체를 rolling 완료로 보지 않는다.

- historical cursor `5208/1` + `backfill_complete=true`
  → 첫 rolling 시작 대기
- rolling window open
  → 전환 시작
- rolling cycle 1회 완주 + coverage 실제 전진
  → rolling acceptance

이 구분은 CI 성공만으로 운영 수집이 완료됐다고 오판하지 않기 위한 것이다.
