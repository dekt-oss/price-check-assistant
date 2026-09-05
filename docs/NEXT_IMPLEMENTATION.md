# 다음 구현 순서

기준: 2026-09-04 `main` (`0f143319d5827ec630d237f7f80eefbac335a06d`).

Phase 0는 종료했고, 현재 핵심 엔진은 **Controlled UAT 진입 가능** 상태다.

`main` 반영 완료:

- G2B Shopping/납품 verified exact-model 검색
- G2B 계약정보 근거 조회
- A/B/C/D/X fail-closed 매칭 + 핵심 숫자·단위 규격충돌 차단
- 외부 가격조건 구조화
- 견적서 상업조건 추출
- 견적조건 ↔ 외부조건 `match/conflict/unknown` comparator
- quote comparability **candidate** gate
- evidence freshness
- 출처별 성공/0건/실패 상태 분리
- Excel `.xlsx/.xls` + text PDF 견적 추출
- MFDS 품목/형명 exact identity, 경쟁장비, 업허가 업체, 공급사 우선순위
- UDI-DI exact 조회
- Safety 수동 공식확인 경로와 상태계약

상세 상태는 `docs/V2_IMPLEMENTATION_STATUS.md`를 기준으로 한다.

## P1. Provenance 일관화 마무리

현재 PR #53 `Add safe public evidence provenance for G2B contracts`가 open 상태다.

목표:

- public response allow-list
- secret-like field 차단
- canonical JSON
- SHA-256 fingerprint
- source record id
- original/detail URL
- normalized 계약근거와 raw provenance 연결
- UI fingerprint 표시

PR #53 CI는 별도 확인하되 **사용자 승인 전 merge하지 않는다**. 일반 CI 성공은 live contract API 성공으로 보지 않는다.

## P2. Controlled UAT

새 기능을 계속 추가하기 전에 실제 업무 표본에서 현재 보수적 계약이 어떻게 작동하는지 측정한다.

### 최소 케이스

1. 일반 전산제품 — 정확 모델
2. 일반 전산제품 — 부정확 제품명
3. 병원 일반 비품
4. 의료장비 — MFDS exact identity 가능
5. 다품목 Excel
6. text PDF
7. 조건이 상세한 견적
8. 조건이 거의 없는 견적
9. exact 모델이지만 외부근거 부족
10. 명백히 다른 규격 제품

추가 권장:

11. 동일 모델 + 수량 차이
12. API 정상 0건
13. API 실패
14. MFDS ambiguous permit
15. 취소/취하 또는 수출전용 의료기기

### 측정값

- `extraction_status`
- `identity_human_grade` / `identity_system_grade`
- 제조사/모델/규격 정확도
- 직접가격 Evidence 확보 여부
- false positive / false negative
- 조건별 `match/conflict/unknown` 사람판정 일치
- candidate gate 결과와 보류 이유
- API success-zero / failure 구분
- source record / URL / fingerprint 재검증 가능 여부
- 수동 조사시간 / 시스템 이용시간
- 재사용 가치

실제 본원 견적이나 비공개 자료는 Public repo에 올리지 않는다. 샘플·비식별·사용승인이 명확한 자료만 사용한다.

## P3. 담당자 승인형 `QUOTE_COMPARABLE` workflow

현재 구조는 candidate gate까지만 구현되어 있다.

목표 흐름:

```text
candidate gate
→ 담당자 원문/조건 확인
→ 명시적 승인
→ 현재 검토 session의 quote/evidence pair에만 승인상태 부여
→ 해당 pair만 QUOTE_COMPARABLE로 평가
→ assess_prices
→ 견적 위치 표시
```

### 필수 안전계약

- candidate 통과만으로 자동승격 금지
- 원본 public source record의 영구 `comparison_scope`를 무조건 변경하지 않음
- 승인상태는 **현재 견적 + 현재 외부근거 pair** 기준
- 승인자 확인시점·확인조건·근거ID를 추적 가능하게 설계
- 승인 취소 가능
- session 밖으로 실제 병원 견적정보를 영구 저장하지 않음

### 수량 equality

현재 candidate gate의 양쪽 수량 일치 요구는 의도적으로 보수적이다.

단가 비교에서는 수량이 달라도 비교 가능한 사례가 있을 수 있지만, **규칙을 먼저 완화하지 않는다**. UAT에서 이 규칙 때문에 실제 비교 가능한 사례가 반복적으로 false negative가 되는지 측정한 뒤 변경 여부를 판단한다.

## P4. Live smoke

일반 GitHub CI와 분리한다.

확인 대상:

- G2B Shopping live smoke
- G2B 계약정보 대표 품목 live 조회
- production Streamlit 대표제품 검색
- MFDS 품목/모델 exact identity
- MFDS 업체조회
- UDI-DI known-value exact lookup

각 결과는 `성공 N건 / 정상 0건 / 실패 / 미검증`을 구분해 기록한다.

## P5. Source coverage 확대

UAT에서 실제로 가격근거 확보율이 병목임을 확인한 뒤 진행한다.

우선순위:

1. 제조사 공식 공개가격
2. 검증 가능한 공공계약
3. 신뢰 가능한 B2B/유통 source
4. 일반 웹은 후보 탐색 보조

금지:

- 검색결과 snippet 가격 자동채택
- 비공식 리셀러를 공식가격으로 승격
- 환율 환산값을 KRW 직접 관측가격으로 취급
- 문의가격 추정
- 모델군 가격을 exact 모델가격으로 사용

G2B mapping 숫자만 늘리는 것을 목표로 하지 않는다. 현재 verified mapping은 5개이고, 병원 의료장비 상당수는 G2B exact 거래가 없다는 Phase 1 조사 결과가 이미 있다.

## 외부 계약 확보 즉시 진행

### Safety RED 자동조회

식약처 회수·판매중지정보의 공식 operation/request parameter를 확보한 뒤에만 구현한다.

- exact 모델/허가번호 matching
- hit 시 가격정보보다 우선하는 RED 경고
- 0건과 API 실패 분리
- `검색결과 없음=안전` 표현 금지
- 자동 구매중단 판단 금지

### 모델명 → UDI/상세 identity

공식 모델 검색 request contract가 확보되면 구현한다. 현재는 UDI-DI를 알고 있는 경우의 exact 조회만 자동화되어 있다.

## P6. 최종 UI 통합

Controlled UAT와 승인 workflow 안정화 후 진행한다.

```text
구매검토 1화면
├─ 직접 검색
└─ 견적서 업로드
      ↓
핵심판정
→ identity / Safety
→ 가격근거
→ 견적조건/비교
→ 경쟁장비/공급사
→ 상세 provenance
```

다품목 견적은 master-detail로 유지한다. 기존 개발용 분리 페이지는 parity/AppTest/production smoke 후 사용자 navigation에서 제거한다.

## P7. 내부 이식

Public PoC의 업무효과가 UAT에서 확인되고 내부 승인을 받은 뒤 진행한다.

- 본원 구매단가 Excel import부터 검토
- PostgreSQL에 내부 observation 별도 축적
- ERP 직접연계는 후순위
- 진료재료/간납단가는 내부 단가 승인 이후 별도 확장

## 작업 우선순위 요약

```text
PR #53 provenance
→ Controlled UAT
→ 담당자 승인형 QUOTE_COMPARABLE
→ live smoke
→ source coverage
→ single-screen UI
→ 내부 이식
```

기능을 더 많이 만드는 것보다 **잘못된 직접비교를 하지 않으면서 실제 구매검토 시간을 줄이는지**를 먼저 증명한다.
