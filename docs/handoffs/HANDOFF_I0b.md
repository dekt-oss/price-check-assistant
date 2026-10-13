# HANDOFF — Phase I0-b (통합 2차, H1·H2 머지 뒤)

## 1. 기준 커밋과 작업 브랜치
- main `2ccd2b9`(#356 H1 후속까지) 병합 · 브랜치 `claude/ux-v11-integration` · 워크트리 `.worktrees/ux-v11-integration`
- 선행: #354(H1), #355(H2), #356(H1 후속), #352·#353(I0-a)

## 2. Phase 목적
H1·H2가 만든 자료(뉴스 이슈 인덱스 v2, 경영 브리핑 객체)를 홈에 연결하고, 뉴스·경영 화면까지 통합 UAT를 끝낸다. Track H 파일은 수정하지 않는다(H2 리뷰 후속은 Codex가 진행 중).

## 3. 완료한 요구사항
- 홈 "병원 뉴스" 카드: 세션 숫자 대신 자동 수집 인덱스의 **최근 3일 주요 이슈 수**(기사 2건 이상 묶인 이슈만), 오늘 제목 일치 기사 수, 마지막 자동 확인 시각. 인덱스를 못 읽으면 "확인 안 됨", 저장소가 없으면 I0-a의 세션 기준 카드로 돌아감.
- 홈 "병원 경영 비교" 카드: 부산백병원 × 지역 경쟁군 × 최신 회계연도의 **경영 브리핑 첫 줄**(회계연도·비교병원 수)과 한 문장(보류 상태 또는 가장 큰 차이). 화면·리포트와 같은 `ManagementBriefing` 객체.
- 브라우저 탭 제목을 화면 제목과 맞춤(`Home.py`: 병원 뉴스 / 병원 경영 비교).
- 운영 스모크: 배포 마커 v23, 뉴스·경영 화면을 열어 새 제목과 첫 블록(주요 이슈 / 경영 브리핑)을 확인하는 단계 추가. H1 배포 때 두 페이지만 옛 코드로 남았던 일을 자동으로 잡기 위함.
- Track H 문서 허용목록에 `docs/NEWS_*.md` 추가(H1 평가 문서 경로).
- 통합 UAT 문서 완성(`docs/uat/UX_V11_INTEGRATION_UAT.md`).

## 4. 변경 파일
`pages/0_홈.py`, `Home.py`, `pages/1_대시보드.py`(마커 v23 한 줄), `scripts/production_unified_search_smoke.py`, `tests/test_ux_v11_integration.py`, `tests/test_production_unified_search_smoke_contract.py`, `tests/test_production_runtime_research_safety.py`, `tests/test_hospital_intelligence_phase1_contract.py`(홈 문구 단언 2줄 — 12항), `docs/coordination/UX_V11_OWNERSHIP.md`, `docs/coordination/UX_V11_BASE.md`, `docs/uat/UX_V11_INTEGRATION_UAT.md`, 이 파일.

## 5. 데이터 계약
- 홈은 읽기만 한다. 뉴스: `news_radar_index.resolve_store(settings).read_index()` → `issues`(v2) + `items`. 경영: `hospital_report.build_report(data, 부산백병원, "region", 최신 연도).briefing`.
- 홈 캐시: 뉴스 인덱스 5분(`st.cache_data(ttl=300)`, 뉴스 페이지와 같음), 브리핑은 프로세스 캐시(공시 자료는 배포 때만 바뀜).
- 런타임 마커 `HOME_TRACK_H_CARDS_V1`, 배포 마커 `purchase-workspace-runtime-v23`.
- 홈의 "주요 이슈 수"는 뉴스 페이지 상단 5개와 다르다: 페이지는 점수 상위 5개(기사 1건짜리 포함), 홈은 72시간 안에 기사 2건 이상으로 묶인 이슈 전체 수. 그룹 토글은 홈에 없다(모든 그룹).

## 6. 실행한 테스트
PR 본문 참조.

## 7. 미검증
- 운영 뉴스 화면 1024px(에뮬레이션 캡처가 시간 초과로 실패, 390px·데스크톱은 확인).
- 운영 홈의 새 카드(머지·배포 뒤 확인).
- 실제 휴대폰 회전.

## 8. 알려진 위험
- `build_report()`는 브리핑 외에 추이 표까지 계산하므로 홈 첫 로딩에 얹힌다(H2 리뷰 M-4). 지금은 프로세스 캐시로 가리고, Codex가 브리핑 전용 함수를 만들면 바꾼다.
- 홈 브리핑 기준(부산백병원·지역 경쟁군)은 코드 상수다. 사용자별 기준 병원은 범위 밖.

## 9. 다음 작업
1. H2 리뷰 후속(Codex) 머지 뒤 홈 브리핑 호출을 가벼운 함수로 교체.
2. Track P 후속: 거래 기간을 URL에 보존.
3. 1주일 측정 뒤 P2b 2차.

## 10. 재현 명령
```bash
PYTHONPATH="$PWD/src" ../../.venv/Scripts/python.exe -m pytest -q tests/test_ux_v11_integration.py tests/test_hospital_intelligence_phase1_contract.py tests/test_production_unified_search_smoke_contract.py tests/test_streamlit_startup_smoke.py
```

## 11. 캡처
UAT 문서 표. 운영 캡처는 PR 본문.

## 12. 공통 파일 변경 요청(처리 내역)
- H2 HANDOFF 12항(홈에서 `build_report(...).briefing` 사용): 반영.
- Track H 테스트 `tests/test_hospital_intelligence_phase1_contract.py`의 홈 문구 단언 2줄을 새 카드 문구("공시 기준", `load_benchmark_data()`)로 바꿨다. 루트 주소·AI 미사용 단언은 그대로다.
