# HANDOFF — Phase I0 (통합, 최종)

I0-a(`HANDOFF_I0a.md`)와 I0-b(`HANDOFF_I0b.md`)를 합친 최종 인계다. 세부는 두 문서를 본다.

## 1. 기준 커밋과 작업 브랜치
- main `266c64b`(#357 H2 후속까지) · 브랜치 `claude/ux-v11-integration` · 워크트리 `.worktrees/ux-v11-integration`
- 머지된 통합 PR: #352, #353(I0-a), #358(I0-b)
- 머지된 Track H: #354, #355, #356, #357 · Track P: #343~#350

## 2. Phase 목적
두 트랙의 결과물을 한 앱으로 묶고(홈·내비게이션·스모크), 운영과 같은 환경에서 UAT를 끝낸다.

## 3. 완료한 요구사항(작업지시서 7장 인수 조건 대조)

| 인수 조건 | 결과 |
| --- | --- |
| 가격·뉴스·경영 메뉴가 서로 상태를 깨뜨리지 않음 | 세션 키가 서로 다르고(`home_search_state*`, `news_radar_*`, `benchmark_*`), 트랙 경계 테스트로 서로의 모듈을 import하지 않음을 검사. 운영 스모크가 세 화면을 한 세션에서 차례로 연다 |
| 트랙 단독 테스트와 전체 테스트 모두 실행 | CI(전체) + 각 PR의 트랙 테스트. 로컬 전체 1,799 통과(알려진 Windows OCR 7건 제외) |
| 1440·1024·390px에서 핵심 결론 읽힘 | UAT 1장 표. 전부 확인(뉴스 1024px은 두 번째 시도에서 확인) |
| 키보드로 주요 이동·필터·접기·버튼 | UAT 2장. 홈 카드 Tab 이동, 나머지는 Streamlit 기본 컨트롤 |
| 그래프 핵심 숫자를 텍스트·표로 | 가격 기간별 표, 경영 "숫자로 보기", 브리핑 문장 |
| URL 보존 상태가 새로고침 뒤 유지 | 검색어 `?q=`와 거래 기간 `?period=`(P4 #359 머지) 모두 됨. 로컬과 운영(Reboot 뒤) 양방향 확인 |
| 준비 중·빈 결과·외부 조회 실패 상태 실제 확인 | UAT 4장 표(가격·뉴스·경영·홈 각각) |

추가로 한 것: 운영 스모크 배포 마커 v22→v23과 뉴스·경영 화면 직접 확인(H1 배포 때 두 페이지만 옛 코드로 남은 사고의 재발 방지), 홈 카드(최근 조사·주요 이슈 수·경영 브리핑), 탭 제목 통일, H1·H2 리뷰와 후속 리뷰(`docs/coordination/history/UX_V11_REVIEW_*_claude.md`), H1 홀드아웃 평가 대행.

## 4. 변경 파일
I0-a·I0-b 문서 참조. 이 단계(최종)에서는 문서만: 이 파일, `UX_V11_REVIEW_H1H2_FOLLOWUP_claude.md`.

## 5. 데이터 계약
- 홈 ← 뉴스 인덱스 v2(`issues`, 72시간, 기사 2건 이상), 홈 ← `build_report(...).briefing`.
- 배포 마커 `purchase-workspace-runtime-v23`. 다음 배포 검증이 필요하면 대시보드와 스모크를 v24로 함께 올린다(`tests/test_ux_v11_integration.py`가 일치를 강제).

## 6. 실행한 테스트
각 PR 본문. 운영 스모크 2026-10-13 10:00Z 수동 실행 전 단계 통과.

## 7. 미검증
- 실제 휴대폰 회전.
- 외부 조회 실패 화면(식약처 정상이라 재현 못 함; 코드 경로는 테스트).

## 8. 알려진 위험
- Streamlit Cloud가 배포 때 페이지 파일 일부를 옛 것으로 남길 수 있다(2026-10-13 H1 배포). 스모크가 잡으면 사용자가 Reboot한다. 인덱스 형식을 바꿀 때는 리더 먼저 배포(`docs/metrics/news.md`).
- H1 군집은 일반어 제목(AI·디지털 그룹)에서 서로 다른 회사 소식을 한 이슈로 묶는다(후속 리뷰 2장). Codex H1 후속 2에서 불용어 추가로 닫는다.
- 머지 직후 운영 스모크는 앱 재시작과 겹쳐 실패할 수 있다. 몇 분 뒤 다시 돌린다.

## 9. 다음 작업
1. Codex: H1 후속 2(일반어 불용어, 두 표본 재평가). 후속 리뷰 2장 4항의 방법으로 홀드아웃을 직접 돌릴 수 있다.
2. 운영 확인이 필요한 PR은 배포 마커(v24…)를 함께 올린다(#359는 마커 없이 배포 지연을 겪음).
3. 1주일 측정 뒤 P2b 2차(같은 품목 모델 집계 5초, 거래 0건 경로 8.7초, 차가운 기동).

## 10. 재현 명령
```bash
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_ux_v11_integration.py tests/test_streamlit_startup_smoke.py tests/test_production_unified_search_smoke_contract.py
gh workflow run "Production Browser Smoke" --ref main
```

## 11. 캡처
UAT 문서 표. 운영 홈·뉴스·경영 캡처는 PR #358 본문과 대화 첨부.

## 12. 공통 파일 변경 요청(처리 내역)
- H2 HANDOFF 12항 두 건(홈 브리핑 연결, 스모크 화면 확인) 반영.
- Track H 테스트 `test_hospital_intelligence_phase1_contract.py` 홈 문구 단언 2줄 갱신(I0-b).
