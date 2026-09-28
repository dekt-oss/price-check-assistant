# WORKORDER — 시장가격조사기 Workspace V3 구현 작업지시서

> Source of Truth: GitHub Issue #221  
> Repository: `dekt-oss/price-check-assistant`  
> Production: `https://bp-price-research.streamlit.app/`  
> 작업 브랜치 기준: `plan/workspace-v3-implementation`  
> 작성일: 2026-09-28

---

## 0. 목적

Workspace V3의 목적은 식약처 데이터를 많이 보여주는 화면을 만드는 것이 아니다.

최종 목적은 대학병원 구매담당자가 검색 결과를 보고:

1. **제품 identity를 확정하고**
2. **직접 비교 가능한 실제 가격근거를 확인하고**
3. **식약처 품목 책임주체와 실제 조달 납품업체를 구분하고**
4. **동일 식약처 품목의 다른 후보를 비교하고**
5. **품의서에 붙일 수 있는 근거를 Export**

할 수 있는 구매조사 Workspace를 만드는 것이다.

본 시스템은 구매결정/추천/승인을 자동화하지 않는다.

---

# 1. 시작 전 필수 확인

모든 구현 세션은 아래 순서로 시작한다.

1. GitHub `main` 최신 HEAD 재확인
2. Open PR / Actions / Production 상태 재확인
3. Issue #221 최신 본문과 comment 재확인
4. MFDS Identity Index 최신 백필 상태 확인
5. Production smoke 상태 확인
6. 변경 대상 파일 최신 SHA 확인

아래 SHA/상태는 문서 작성 시점 참고일 뿐 고정 사실로 사용하지 않는다.

**GitHub Repository를 Source of Truth로 한다.**

---

# 2. 작업 운영 규칙

## 2.1 개발 방식

- Codex는 직접 사용하지 않는다.
- GitHub connector 기반으로 작업한다.
- 코드 변경은 작업 브랜치에서 수행한다.
- 기능을 가능한 원자 단위로 나눈다.
- 각 원자 작업마다:
  1. 구현
  2. unit/contract test
  3. CI
  4. 필요 시 Production/UAT
  5. checkpoint
  순서로 진행한다.

## 2.2 PR / Codex 자동리뷰 주의

현재 저장소는 PR 생성 시 `chatgpt-codex-connector[bot]` 자동 리뷰가 실행될 수 있다.

따라서:
- 단순 중간 checkpoint마다 PR을 생성하지 않는다.
- branch에서 먼저 구현/테스트한다.
- 의미 있는 통합 checkpoint에서만 PR을 생성한다.
- 사용자가 별도로 요구하지 않는 한 `@codex review`를 호출하지 않는다.
- 자동 Codex 리뷰가 꺼지지 않은 상태에서는 PR 수를 최소화한다.

## 2.3 Merge 규칙

- 사용자 승인 전 자동 merge 금지.
- CI green만으로 Production 정상으로 간주하지 않는다.
- 확인하지 못한 것은 `미검증`으로 표시한다.

---

# 3. 절대 변경하지 않는 제품 원칙

- A/B 직접비교와 C/Research 참고근거를 분리한다.
- 총액과 단가를 구분한다.
- 식약처 품목 책임주체와 실제 조달 납품업체를 합치지 않는다.
- 품목번호 검색에서 여러 모델이 연결되면 대표모델을 자동선택하지 않는다.
- API/index 장애를 0건으로 표현하지 않는다.
- 임상적 동등성 근거 없이 `동등장비 / 완전대체 / 추천장비`라고 표현하지 않는다.
- 공식 Source가 확인하지 않은 업체 관계·단위·로트·포장·동일성을 추정해서 확정하지 않는다.
- Safety에서 `안전함 / 이상 없음`이라고 표현하지 않는다.
- 가격에서 `적정 / 부적정 / 권고 / 비권고` 자동판단을 하지 않는다.
- 공개 PoC에 내부 민감 견적 원문을 영구 저장하지 않는다.

---

# 4. V3 핵심 정보구조

## 4.1 Discovery mode

검색 전 화면:

- 큰 검색 Hero
- 통합검색
- 상세조건
- 견적서 업로드
- 데이터 기준일/백필 상태는 보조정보

검색 placeholder:

`모델명 · 식약처 품목번호 · UDI-DI · 품목 · 업체 검색`

## 4.2 Result mode

검색 후:

- compact 검색바
- 새 검색
- 견적 업로드
- Identity
- Safety
- 구매판단 요약
- 3개 segmented 영역

세부 영역:

1. **가격 비교**
2. **업체·조달**
3. **동일품목 비교**

별도 `요약` 탭 없음.
별도 `근거·원문` 탭 없음.

근거는 각 숫자/행에 inline으로 연결한다.

---

# 5. 상태 계약

## 5.1 Identity

- `FOUND`
- `NOT_FOUND_IN_COVERAGE`
- `AMBIGUOUS`
- `UNAVAILABLE`

금지:
- 백필 범위 밖을 `미등록`으로 표시

## 5.2 가격/조달 Evidence

- `FOUND`
- `ZERO`
- `UNAVAILABLE`
- `STALE`
- `PARTIAL`

`ZERO`는 아래 조건을 모두 만족해야 한다.

- source/index 정상 조회
- matching pipeline 정상 실행
- 검색키 명확
- exact 직접비교가 실제 0건

표시 문구:

`직접 동일성 확인 거래 0건`

검색키를 함께 표시한다.

## 5.3 Safety

- `NOT_CONNECTED`
- `CHECK_FAILED`
- `CHECKED_NONE`
- `AMBER`
- `RED`

RED는 Source가 제공하는 경우:
- 대상 로트
- 특정/전체 범위
- 조치일자
- 원문
표시.

로트범위 미제공 시 추정 금지.

---

# 6. 의료기기 용어 계약

## 6.1 사용자 UI

`허가번호` 단일 표현을 폐기하고:

**식약처 품목번호**

로 표시한다.

유형 badge:
- `[허가]`
- `[인증]`
- `[신고]`

예:
`[신고] 수신 22-2177호`

## 6.2 업체

`식약처 등록업체` 단일 표현을 폐기한다.

상위 표현:

**품목 책임주체**

세부 역할:
- 제조업자
- 수입업자
- 신고주체
- 공식 Source가 제공하는 기타 역할

수입품 해외 제조원은 공식 Source가 있을 때 별도 표시.

## 6.3 업체 Role

순위형 Tier 폐기.

- 품목 책임주체
- 업 허가·신고 확인
- 조달 계약·납품 실적 업체
- 공식 판매채널 — Phase 2
- 일반 웹 판매처 — Phase 2

---

# 7. 가격 Evidence 필수 필드

직접가격 행은 가능한 범위에서 아래를 표현한다.

- 단가
- 단위
- 포장입수
- 수량
- 거래총액
- VAT 포함여부
- 거래일
- 모델
- 규격
- 공급업체
- 수요기관
- 거래조건
- 매칭근거
- Source
- 원문

미확인 값은 `미확인`.

## 7.1 단가

원문 제공:
- `원문 단가`

총액/수량으로 계산:
- `계산단가`
- 계산근거 표시

## 7.2 단위 불명

단위 미확인 거래:
- A 등급 금지
- 최대 B 또는 Research
- 최종 규칙은 Phase 0에서 MatchGrade 계약과 함께 고정

---

# 8. Phase 0 — UI 개편 전 필수

Phase 0이 끝나기 전 대규모 V3 UI 개편을 시작하지 않는다.

---

## P0-01. Evidence 상태계약 정리

### 목표

Identity / 가격 / Safety 상태를 명시적 domain contract로 만든다.

### 구현

#### Identity
- FOUND
- NOT_FOUND_IN_COVERAGE
- AMBIGUOUS
- UNAVAILABLE

예상:
- `src/purchase_price/services/mfds_identity_index.py`
- `src/purchase_price/services/mfds_identity_r2.py`
- 신규 domain/schema 가능

#### 가격
- FOUND
- ZERO
- UNAVAILABLE
- STALE
- PARTIAL

예상:
- `track_b_r2_quote_index.py`
- `track_b_db_quote_comparison.py`
- schemas / presenter

#### Safety
- NOT_CONNECTED
- CHECK_FAILED
- CHECKED_NONE
- AMBER
- RED

### Acceptance

- R2 강제 장애가 ZERO로 변환되지 않는다.
- 백필 범위 밖 identity가 미등록으로 표시되지 않는다.
- Safety 미연결과 정상조회 0건이 구분된다.

### Test

- unavailable index
- successful zero result
- ambiguous model
- backfill coverage miss
- Safety disconnected / failed / checked-none

---

## P0-02. 의료기기 용어·Identity 표현

### 목표

UI에서 허가/인증/신고를 정확히 분리한다.

### 구현

- `식약처 품목번호`
- badge parser
  - 제허/수허 → 허가
  - 제인/수인 → 인증
  - 제신/수신 → 신고
- `품목 책임주체`
- 제조업자/수입업자 역할 표현
- 해외 제조원은 Source가 있을 때만

예상:
- `pages/1_대시보드.py`
- `pages/4_의료기기_조회.py`
- MFDS presenter/domain

### Acceptance

- `수신 22-2177호`가 `[신고]`로 표시.
- 모든 품목을 허가권자로 일괄 표시하지 않는다.
- UI에 `식약처 등록업체` legacy 표현이 남지 않는다.

---

## P0-03. 가격 단위/계산단가/매칭근거

### 목표

단위 오판을 방지한다.

### 구현

- 가격 필수필드 계약
- 원문 단가 / 계산단가
- 단위 불명 A 금지
- VAT 상태
- 매칭근거 badge

예상:
- transaction row domain
- matching service
- `ui/track_b_transactions.py`
- schemas/tests

### Acceptance

- 총액÷수량 값은 계산단가로만 표시.
- 단위 미확인 거래는 A가 되지 않는다.
- 거래행마다 매칭근거를 표현할 수 있다.

---

## P0-04. Track B fail-closed + multi-model batch

### 목표

다중모델 품목번호 검색에서 성능과 의미를 동시에 보장한다.

### 구현

- Track B UNAVAILABLE → ZERO 금지
- R2 pointer 검색당 1회
- SQLite engine/session 검색당 1회
- model deduplicate
- 가능한 경우 `WHERE model IN (...)`
- lazy detail loading 지원

현재 페이지의 모델별 반복:
- R2 pointer read
- local index resolve
- engine 생성
을 제거.

예상:
- `track_b_r2_quote_index.py`
- `track_b_db_quote_comparison.py`
- 신규 workspace crosslink service

### Acceptance

- 모델 50개 품목번호에서 첫 shell 5초 목표.
- 로그/계측상 R2 pointer + engine 검색당 1회.
- Track B 장애 시 `조회 불가`.
- 직접근거 0건과 장애를 구분.

---

## P0-05. MFDS backfill 운영안전

### 목표

백필 상태 미확인/동시실행/부분 index 노출을 방지한다.

### 구현

#### 상태
- STATE_UNKNOWN / UNAVAILABLE일 때 고속백필 자동 실행 금지.

#### Lock
- workflow concurrency 유지
- backend lock + TTL
- stale lock 복구

#### Atomic serving
- 새 index 완성
- hash/metadata 확인
- pointer 마지막 교체
- old/new 완성본만 제공

#### Refresh
- 상태 변경 upsert
- full-cycle stale row 제거

예상:
- `mfds_identity_status.py`
- collection planner
- R2 state/index store
- workflow

### Acceptance

- R2 상태조회 실패 → 고속백필 미트리거.
- 두 backfill 동시실행 → 실제 write 1개.
- refresh 중 검색 → 깨진 중간 DB를 읽지 않는다.

---

## P0-06. 업체 동일성 + 업로드 보안 + 금지어 회귀

### 업체 identity

- 공식 식별키 일치 → 동일 업체 확인
- 이름 normalization만 일치 → 명칭 유사·미확인

### 업로드

- 원본 영구저장 금지
- temp 삭제
- 로그 원문 금지
- 외부 AI API 전송 여부/보관정책 명시

### UI 금지어 regression

자동판단 문구에서 금지:
- 미등록
- 거래 없음
- 안전
- 이상 없음
- 적정/부적정
- 권고/비권고
- 의미가 섞인 `공식 공급처`

---

# 9. Phase 0 완료 Gate

아래가 모두 통과해야 Phase 1 UI 작업을 시작한다.

- [ ] Identity 4상태
- [ ] 가격 5상태
- [ ] Safety 5상태
- [ ] 품목번호 badge
- [ ] 품목 책임주체
- [ ] 계산단가
- [ ] 단위불명 A 금지
- [ ] 매칭근거
- [ ] Track B unavailable fail-closed
- [ ] multi-model batch
- [ ] R2 STATE_UNKNOWN fail-closed
- [ ] backfill lock/TTL
- [ ] atomic pointer 검증
- [ ] 업체 identity 정책
- [ ] 업로드 보안 contract
- [ ] 금지어 regression

---

# 10. Phase 1 — Workspace V3 MVP

## P1-01. Discovery / Result shell

### Discovery

- Hero
- 통합검색
- 견적업로드
- 상세검색
- 데이터 기준일

### Result

- compact 검색바
- 새 검색
- 견적업로드
- Identity
- Safety
- 구매판단 요약

### State

- `st.query_params`
  - q
  - view
  - 선택 identity

session_state 단독 의존 금지.

예상:
- `pages/1_대시보드.py`
- workspace presenter/helper

---

## P1-02. 항상 노출 Result header

표시:

### Identity
- 품목
- 모델
- 식약처 품목번호 badge
- UDI
- 포장단위
- 책임주체
- ambiguity

### Safety
- 5상태

### 구매판단
- 내 견적가
- 단위
- VAT
- 설치/운송 조건
- A/B 건수
- 직접가격 범위
- 최근거래
- 조달 납품업체
- Research 근거
- data_as_of

---

## P1-03. 내 견적가

견적서 없이 직접 입력:

- 가격
- 단위
- VAT
- 조건

출력:

> 직접 비교자료 상단 대비 +N%. 단위·VAT·설치조건 확인 필요.

근거 부족:

> 직접 비교자료 1건뿐으로 가격대 판단근거 부족.

금지:
- 적정
- 부적정
- 권고

---

## P1-04. 3개 결과 영역

`st.tabs` 폐기.

`st.segmented_control` 또는 가로 radio.

1. 가격 비교
2. 업체·조달
3. 동일품목 비교

선택한 영역만 계산.

가능하면 `st.fragment`.

---

## P1-05. 가격 비교

### A/B

- 모든 필수필드
- inline 원문
- match badge
- ZERO 검색키
- data_as_of

### Research

- 별도 시각영역
- 유사표기 후보
- 동일제품 직접가격이 아님을 명시

---

## P1-06. 업체·조달

### 품목 책임주체
- 제조/수입/신고 역할
- 품목번호
- 모델
- UDI
- Source

### 업 허가·신고
- 업체 속성 badge

### 조달 납품
- 거래수
- 수요기관
- 최신일자
- 가격범위

두 관계 사이:

> 총판·대리점·판매권 관계는 공개자료로 확인되지 않으면 미확인.

---

## P1-07. 동일품목 비교

grouping:

`품목 책임주체 → 모델`

각 model:
- 품목번호 badge
- lifecycle
- 조달 상태
- 가격범위

기본:
- 조달가격 있는 것만
- 취소·취하 숨김
- 현재 모델 표시

---

## P1-08. 검색 Routing

목적지:

1. 후보 선택
2. 제품 Workspace
3. 업체 중심 목록

### 품목번호
- 모든 모델
- 상태 먼저
- 가격 lazy load

### 모델
- 동명 후보 있으면 candidate selection

### UDI
- exact → Workspace
- packaging 표시 가능 범위

### 업체
- 제품 manufacturer로 자동 주입 금지
- 책임주체 결과와 납품업체 결과 분리

### 품목명
- 분류번호/분류명/등급 grouping

---

## P1-09. 인라인 근거

핵심 값마다:
- Source
- 조회일
- data_as_of
- 매칭근거
- 원문

상단:
- 근거 전체보기

---

## P1-10. 시장조사표 Excel

예상 신규:
`src/purchase_price/services/market_survey_export.py`

포함:
- search identity
- 내 견적
- A/B
- C/Research
- 가격단위
- VAT
- matching grade
- match reason
- supplier/institution
- Source
- 조회일
- data_as_of
- 주의문구

Release:
- 품의서 첨부 가능한 형식
- PDF는 Phase 2

---

# 11. Phase 1 Release Gate

## 정상

- [ ] 식약처 품목번호 exact
- [ ] multi-model 대표모델 자동선택 없음
- [ ] 동명 모델 candidate selection
- [ ] UDI packaging
- [ ] 책임주체/납품업체 분리
- [ ] inline 원문

## fail-closed

- [ ] Track B 강제 차단
- [ ] R2 상태조회 실패
- [ ] 백필 coverage 밖
- [ ] Safety 미연결
- [ ] 취소/취하
- [ ] 단위불명
- [ ] 계산단가
- [ ] 직접근거 1건
- [ ] lot 미제공

## 성능

- [ ] 50+ model shell 5초
- [ ] R2 pointer 1회
- [ ] engine/session 1회
- [ ] atomic index

## UX/보안

- [ ] URL 공유
- [ ] 뒤로가기
- [ ] 다품목 견적 부분 실패
- [ ] 업로드 원본 미잔존
- [ ] Excel Source/조회일/조건 포함

---

# 12. Phase 2

- 업체 중심 화면 고도화
- 견적서 확인·수정 table
- Safety 공식 API + lot scope
- 품목 동의어 사전
- 동일제품 아님 feedback
- 공식 판매채널
- 웹 판매점 Research
- PDF 시장조사표
- 동일품목 고급 필터/정렬

---

# 13. UAT 기준 케이스

## 실데이터 필수

### Case A — 품목번호 + direct evidence
`수신 22-2177호`

검증:
- 신고 badge
- 채혈기
- C101
- UDI
- 품목 책임주체
- G2B direct evidence
- 실제 조달업체
- 거래일
- 단위는 Source 확인 후만 표시

주의:
이 사례는 **기능 E2E UAT 샘플**이며 진료소모품 전체 MVP 범위확장을 의미하지 않는다.

### Case B — multi-model 품목번호
대표모델 자동선택 없음.

### Case C — direct evidence 없는 exact identity
ZERO 상태와 검색키.

### Case D — Track B unavailable
UNAVAILABLE.

### Case E — ambiguous model
candidate selection.

### Case F — Safety NOT_CONNECTED
회색 미조회.

---

# 14. 테스트 전략

## Unit

- enums/state
- permit-type badge parser
- price normalization
- calculated unit price
- company identity
- query routing

## Contract

- UI 금지어
- label/terminology
- Source field
- export schema
- workflow fail-closed

## Integration

- MFDS R2
- Track B R2
- multi-model batch
- unavailable simulation

## Production Browser UAT

- Discovery
- Result
- segmented section
- permit exact
- multi-model
- ambiguous model
- quote
- export

---

# 15. 권장 작업 패키지 / PR checkpoint

자동 Codex 리뷰로 인한 불필요한 사용량을 줄이기 위해 PR을 너무 잘게 만들지 않는다.

권장 checkpoint:

## Checkpoint A — Phase 0 Core Semantics
포함:
- P0-01 상태계약
- P0-02 용어/Identity
- P0-03 가격단위

## Checkpoint B — Phase 0 Runtime Safety
포함:
- P0-04 Track B batch/fail-closed
- P0-05 MFDS 운영안전
- P0-06 업체 identity/보안

## Checkpoint C — Phase 1 Shell
포함:
- Discovery/Result
- Result header
- query_params
- segmented navigation

## Checkpoint D — Phase 1 Evidence
포함:
- price
- 업체·조달
- 동일품목
- inline evidence
- routing

## Checkpoint E — Export/UAT
포함:
- Excel
- Production UAT
- performance gate

각 checkpoint는 사용자 승인 전 merge 금지.

---

# 16. 작업 완료 보고 포맷

매 checkpoint 종료 시 아래 형식으로 보고한다.

## 구현
- 변경 기능
- 변경 파일

## 의미론
- 어떤 오판 가능성을 제거했는지

## 테스트
- unit
- contract
- integration
- Production

## 데이터
- MFDS backfill 영향 여부
- Track B 영향 여부

## 미검증
- 확인 못한 항목

## 다음 작업
- 다음 checkpoint

---

# 17. 구현자가 하지 말아야 할 것

- UI부터 먼저 대규모 재작성
- C/Research를 direct와 섞기
- MFDS 업체를 G2B 제조사/공급사로 자동 승격
- 다중모델을 첫 모델 하나로 축약
- ZERO와 UNAVAILABLE 합치기
- 수집 coverage miss를 미등록으로 표현
- 총액÷수량을 원문 단가로 표현
- 단위 불명 A 등급
- 업체명 normalization만으로 동일업체 확정
- Safety API 미연결을 CHECKED_NONE으로 표현
- Source 없는 포장/lot/VAT 추정
- 견적 원문을 공개 서버에 영구 저장
- Codex를 명시적으로 호출
- 사용자 승인 없는 merge

---

# 18. 실행 시작점

V3 실제 개발은 **Phase 0 Checkpoint A**부터 시작한다.

첫 작업 순서:

1. Identity / 가격 / Safety 현재 status contract inventory
2. legacy UI 용어 grep
3. MatchGrade / transaction row field inventory
4. proposed enums/schema 작성
5. unit/contract tests 우선 추가
6. implementation
7. CI
8. Production 영향 없음 확인
9. checkpoint 보고

Phase 0 의미론이 고정되기 전에는 Result UI V3 본체를 구현하지 않는다.

---

# 19. Source of Truth 우선순위

충돌 시:

1. 최신 사용자 지시
2. Issue #221 최신 본문
3. 본 WORKORDER
4. 기존 V2/V3 코드
5. 과거 handoff

Issue #221의 원칙과 본 문서가 충돌하면 먼저 Issue를 재확인하고, 확인되지 않은 해석은 임의 구현하지 않는다.

---

# 20. 시작 명령

새 개발 세션에서 다음을 수행한다.

> GitHub main / open PR / Actions / Production을 다시 확인하고, Issue #221 및 `docs/WORKORDER_WORKSPACE_V3.md`를 읽은 뒤 **Phase 0 Checkpoint A부터 채팅개발모드로 작업한다. Codex는 사용하지 않는다. 사용자 승인 전 merge하지 않는다.**
