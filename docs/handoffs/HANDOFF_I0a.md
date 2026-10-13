# HANDOFF — Phase I0-a (통합 1차, H1·H2와 병렬)

## 1. 기준 커밋과 작업 브랜치
- `8a84477`(#341 머지) · 브랜치 `claude/ux-v11-integration` · 워크트리 `.worktrees/ux-v11-integration`

## 2. Phase 목적
H1·H2를 기다리지 않고 할 수 있는 통합 일을 먼저 끝낸다. 뉴스·경영 데이터에 기대는 홈 카드와 화면 점검은 I0-b로 넘긴다.

## 3. 완료한 요구사항
- 통합 담당 Claude 확정, I0 두 단계 분할을 작업지시서 7장과 `UX_V11_BASE.md`에 기록
- 운영 스모크 배포 마커 v21 → v22(`scripts/production_unified_search_smoke.py`와 계약 테스트 2개). P1·P3 HANDOFF의 공통 파일 요청 처리
- 두 트랙 경계 검사: 뉴스·경영 코드와 가격 코드가 서로의 모듈을 불러오지 않음(`tests/test_ux_v11_integration.py`)
- 홈: 이번 접속의 최근 가격 조사(현황 카드 + "최근 조사 · 검색어(시각)" 링크 3개, 누르면 결과 다시 열림)
- 통합 UAT 초안 `docs/uat/UX_V11_INTEGRATION_UAT.md`(가격·홈: 폭, 키보드, 상태, URL)

## 4. 변경 파일
`pages/0_홈.py`, `scripts/production_unified_search_smoke.py`, `tests/test_production_runtime_research_safety.py`, `tests/test_production_unified_search_smoke_contract.py`, `tests/test_ux_v11_integration.py`(신규), `docs/coordination/UX_V11_BASE.md`, `docs/coordination/UX_V11_WORK_ORDER_v1.2.md`, `docs/uat/UX_V11_INTEGRATION_UAT.md`(신규), 이 파일. Track H 파일은 건드리지 않음.

## 5. 데이터 계약
홈은 가격 조사 화면이 세션에 남기는 `home_recent_searches`(`[(검색어, "HH:MM")]`)를 읽기만 한다. 런타임 마커 `HOME_RECENT_SEARCHES_V1`.

## 6. 실행한 테스트
PR 본문 참조.

## 7. 미검증
- 실제 휴대폰 회전 시 그래프 폭(에뮬레이션에서는 폭만 줄이면 이전 폭으로 남음).
- 실시간 확인 실패 화면(외부 API가 정상이라 재현 못 함).

## 8. 알려진 위험
- 홈 최근 조사는 세션 저장이라 새 접속·다른 기기에서는 보이지 않는다(의도).

## 9. 다음 작업 (I0-b, H1·H2 머지 뒤)
1. 홈 "병원 뉴스" 카드가 세션이 아니라 자동 수집 인덱스(H1 군집 포함)의 오늘 주요 이슈 수를 읽게 한다.
2. 홈에 최신 경영 브리핑 상태(H2) 한 줄.
3. 뉴스·경영 화면 1440/1024/390px·키보드·상태 점검으로 UAT 문서 완성.
4. Track P 후속: 거래 기간을 URL에 보존.

## 10. 재현 명령
```bash
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_ux_v11_integration.py tests/test_production_unified_search_smoke_contract.py
```

## 11. 캡처
UAT 문서의 표에 결과를 적었다.

## 12. 공통 파일 변경 요청
없음(이 단계가 통합 담당).
