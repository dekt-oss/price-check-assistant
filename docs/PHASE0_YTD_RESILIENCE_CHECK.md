# Phase 0 — G2B YTD 복원력 재검증

작성일: 2026-09-04

## 목적

이전 2026 YTD 장기 scan이 retry 소진 후 raw `httpx.ConnectTimeout`으로 전체 종료된 문제를 수정한 뒤, 동일 유형의 장시간 G2B scan이 **오류를 구조화해 계속 진행하는지** 재검증한다.

## 실행

- GitHub Actions run: `33820409537`
- 기준코드: `cfe46d0365c157588dea870cde9f0b8f66c73e89`
- 기간: 2026-01-01 ~ 2026-09-03
- chunk: 31일
- 최대 페이지: window당 20페이지 × 100행
- verified G2B mapping 4개 전부 실행

## 결과

Workflow 자체는 **success**했다.

scan command는 `exit=1`을 반환했지만 원인은 transport crash가 아니라 한 window의 명시적 pagination safety limit이다. traceback으로 전체 프로세스가 종료되지 않았고, 나머지 window를 계속 처리한 뒤 summary/candidate artifact를 정상 저장했다.

### Sophie

- 8개 window 모두 complete
- records seen: **57**
- exact-model candidate: **0**

### 삼성 NT960XJG-K72AG

- 8개 window 모두 complete
- records seen: **9,072**
- exact-model candidate: **0**

즉 대량의 `노트북컴퓨터` 조달 record가 존재해도 검색대상 exact model 거래가 없을 수 있다.

### FUJIFILM ApeosPrint C5570 GK

- 8개 window 중 7개 complete, 1개 incomplete
- complete-window records seen 합계: **7,014**
- exact identity: **1개**
- retained exact-model transactions: **42건**
- retained grades: **A**

Incomplete window:

- 2026-03-04 ~ 2026-04-03
- 원인: `레이저프린터` 결과가 2,000건을 초과하여 `max_pages=20` safety limit 도달
- transport/network crash 아님
- 이 window는 불완전한 결과를 완전한 결과로 가장하지 않고 candidate 집계에서 제외됨

### ThinkStation P2 Tower

- 8개 window 모두 complete
- records seen: **1**
- exact-model candidate: **0**

고정 검증기간에는 source hit가 0이었지만 YTD 후반 window에는 워크스테이션 record 1건이 있었다. 검색대상 exact model은 아니었다.

## 판정

### 해결된 것

- retry 소진 transport failure가 raw httpx 예외로 전체 scan을 죽이는 경로를 `PublicDataClientError`로 감쌌다.
- window-level 실패/불완전 상태를 기록하고 다음 window로 진행할 수 있다.
- service key redaction 회귀테스트를 추가했다.
- 장시간 scan에서 output artifact를 보존한다.

### 남은 Phase 1 개선

YTD 전체수집에서 단순 `31일 × max 20페이지` 고정은 데이터가 많은 품목에 충분하지 않다.

Phase 1에서는 다음 중 하나를 적용한다.

1. totalCount를 보고 날짜 window를 자동 이분할하는 adaptive date partitioning
2. 안전범위 내에서 페이지 한도를 source별로 동적 상향
3. incomplete window 재시도 큐

권장안은 **adaptive date partitioning**이다. 한도를 무작정 올리는 방식보다 API 호출량과 완전성 계약을 명시적으로 관리할 수 있다.

## Phase 0 영향

이 incomplete는 Phase 0 종료를 막지 않는다. Phase 0의 공식 비교지표는 고정기간 2026-07-14~2026-08-13 live validation이며 해당 실행은 collector error 0%, 완전 성공했다.

YTD 검증은 운영 복원력과 대량 pagination 한계를 확인하기 위한 추가 검증이다.
