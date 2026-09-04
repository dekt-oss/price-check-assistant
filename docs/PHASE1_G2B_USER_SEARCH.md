# Phase 1-A — G2B 사용자 통합검색 계약

작성: 2026-09-04

## 목적

Phase 0에서 live 검증한 조달청 나라장터쇼핑몰 `특정품목조달내역` 경로를 Streamlit 통합검색에 연결한다.

이 단계의 목표는 **검증된 모델에 대해 실제 공공 구매실적 가격근거를 사용자 검색 결과에 추가하는 것**이다. 제품분류를 추정해서 coverage를 넓히는 것이 아니다.

## 활성화 조건

G2B 사용자 검색은 다음 조건을 모두 만족할 때만 실행한다.

1. `DATA_GO_KR_SERVICE_KEY`가 로컬 `.env` 또는 deployment secret에 설정돼 있다.
2. 사용자가 `model_name`을 입력했다.
3. `data/g2b_product_mappings.csv`에 해당 exact model의 `verified` mapping이 정확히 하나 존재한다.

하나라도 만족하지 않으면 G2B 호출을 하지 않는다. 제조사 공개가격 collector는 독립적으로 계속 동작한다.

## 현재 verified mapping

2026-09-04 기준 registry에서 verified 상태인 benchmark 모델은 다음 4개다.

| 모델 | G2B 세부품명 | 세부품명번호 |
| --- | --- | --- |
| Sophie | 인공호흡기 | 4227220901 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 |
| ApeosPrint C5570 GK | 레이저프린터 | 4321210501 |
| ThinkStation P2 Tower | 워크스테이션 | 4321151501 |

verified mapping이 없는 모델은 세부품명을 자동 추정하지 않는다.

이 경로의 실제 서비스키 환경 live end-to-end 검증 결과는 [PHASE1_G2B_LIVE_SMOKE.md](PHASE1_G2B_LIVE_SMOKE.md)에 기록한다.

## Adaptive date partitioning

특정 세부품명은 짧은 기간에도 거래건수가 많아 `max_pages` safety cap을 넘을 수 있다.

기존 동작:

```text
기간 전체 조회
  -> max_pages 초과
  -> incomplete / fail-closed
```

Phase 1-A 동작:

```text
기간 전체 조회
  -> pagination safety limit
  -> 날짜구간 이분할
  -> 왼쪽 완전수집
  -> 오른쪽 완전수집
  -> 필요하면 각 구간을 다시 이분할
```

단, **1일 구간도 safety cap을 넘으면 더 이상 분할하지 않고 fail-closed** 한다. 일부 데이터만 성공한 것처럼 반환하지 않는다.

일반 API 오류, 응답구조 오류, 빈 페이지/totalCount 불일치 등은 거래량 문제로 간주해 분할하지 않고 그대로 오류로 올린다.

## 가격판정 계약

G2B 결과도 기존 Phase 1 pricing safety gate를 그대로 따른다.

- 제품 동일성: F3 `MatchGrade` A/B/C/D/X
- 금액 성격: `EvidenceType`
- 통화: 현재 KRW만 관측 직접가격 범위 대상
- 비교범위: G2B는 현재 `ComparisonScope.OBSERVED_ONLY`

즉 G2B 실제 구매실적 숫자가 확보돼도 VAT·배송·설치·옵션·보증 등이 현재 견적과 동등하다고 검증되기 전에는 **견적이 높다/낮다 판정에 사용하지 않는다.**

## UI

통합검색에서 나라장터 검색기간을 최근 30/90/180/365일 중 선택한다.

결과에는 최소 다음을 보여준다.

- 출처
- 가격/통화
- A/B/C/D/X
- Evidence Type
- Comparison Scope
- 거래일
- 수량/단위
- 조건
- item-level 근거 ID
- 수집일

## Secret 정책

- 서비스키 값은 UI에 표시하지 않는다.
- HTTP transport log에서 `serviceKey`는 마스킹한다.
- Public repository에 실제 key를 저장하지 않는다.

## 검증 상태

### CI에서 검증하는 것

- adaptive split 성공
- 1일 overflow fail-closed
- exact model + verified mapping만 자동 검색
- key가 있을 때만 registry 활성화
- 기존 Ruff / pytest / strict Ground Truth / offline integration 회귀

### CI가 검증하지 않는 것

CI에는 실제 data.go.kr key를 넣지 않는다. 따라서 CI green만으로 **실제 사용자 통합검색의 live API 성공을 주장하지 않는다.**

PR merge 후 실제키 환경에서 Sophie / NT960XJG-K72AG / ApeosPrint C5570 GK 중 하나 이상으로 user-surface smoke를 별도 확인해야 한다.
