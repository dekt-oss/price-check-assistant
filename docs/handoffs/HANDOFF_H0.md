# HANDOFF H0 — 병원 뉴스·경영 현재 구현 조사

> 보완 1차(리뷰 반영) · 2026-10-13 KST

## 1. 기준 커밋과 작업 브랜치

- 작업지시서 BASE_SHA: `ecb888bada895fec30443a951dfc09ab2e90a54e`
- 최초 H0 PR: #344, squash merge `9b38d8ec778c05b0c32c9493301c83032ecc41f0`
- 보완 브랜치: `codex/ux-v11-news-management`
- 워크트리: `.worktrees/ux-v11-news-management`
- 리뷰 입력: `PROMPT_2026-10-12_H0_review_for_codex.md`
- PR #341: `087fae2`, 2026-10-13 확인 시 `OPEN`, 두 CI job 성공

## 2. Phase 목적

H1·H2에서 기존 기능을 중복 구현하거나 약관·데이터 의미를 바꾸지 않도록 현재 뉴스·경영 계약과 다음 Phase 제안을 분리한다. 이 보완은 리뷰 B1~B6을 닫고 R1~R7을 반영하되 실행 코드는 바꾸지 않는다.

## 3. 완료한 요구사항

- 뉴스 허용 필드 5종, description·본문·AI 미사용, 21일 보관 경계를 유지했다.
- 운영 상태 쓰기 권한을 단정하지 않고 비파괴 점검 결과 `미검증`으로 정정했다.
- 현재 기사 중요도 점수와 H1 이슈 정렬의 연결 원칙을 기록했다.
- 제목 불일치 검색 결과를 H1 군집·수치·평가 표본에서 제외하고 `본문에서만 언급` 단정을 수정 대상으로 등록했다.
- 경영의 현재 `describe_findings()` 동작과 H2 신규 브리핑 계약을 분리했다.
- 2024년 8개 병원 × 비교군 4종의 선택 N·핵심 7지표 유효 n을 계산했다.
- 뉴스·경영 빈 상태에 현재 문구·코드 위치·유지/수정/신규 분류를 추가했다.
- R1~R7의 세부 구현 사실과 보류 결정을 문서화했다.

## 4. 변경 파일 목록과 허용목록 대조

| 파일 | 변경 | 소유권 |
| --- | --- | --- |
| `docs/metrics/news.md` | 리뷰 보완 | Track H 허용 문서 |
| `docs/metrics/hospital_management.md` | 리뷰 보완 | Track H 허용 문서 |
| `docs/handoffs/HANDOFF_H0.md` | 리뷰 보완 | Track H 허용 문서 |

코드, 설정, 공통 파일, 가격 파일은 변경하지 않았다.

## 5. 데이터 계약·API·인덱스 버전 변경

- 실행 코드/API/인덱스 버전 변경 없음.
- 현재 뉴스 인덱스는 `news/v1/index.json.gz`, `version=1`.
- H1 예정: 제목 일치 기사만 군집하고, 허용된 필드만으로 이슈를 저장하며 v1 읽기 호환을 유지한다.

## 6. 실행한 검증과 실제 결과

H0 최초 PR #344의 CI `test`, `bundled-ocr`는 모두 성공했다. 최초 로컬 전체 테스트는 `1670 passed, 7 failed`였고, 4건은 알려진 Windows OCR 실환경 실패다. 나머지 Track P 테스트 3건은 **Windows 로컬에서만 관찰했으며 원인은 조사하지 않았다**. H0가 원인인 회귀라고 확정하지 않으며, 최초 PR CI는 녹색이었다.

보완 PR 로컬 검증:

- `ruff check .`: `All checks passed!`.
- `pytest -q tests/test_streamlit_startup_smoke.py`: `1 passed in 16.46s`.
- 작업지시서의 Track H 지정 17개 테스트 파일: `164 passed, 1 warning in 22.31s`.
- 첫 두 Track H 실행은 각각 `C:\tmp` 쓰기 권한과 저장소 내부 basetemp 부모 폴더 부재로 `129 passed, 35 setup errors`였고, 부모 폴더를 만든 뒤 같은 테스트를 재실행해 위 통과 결과를 얻었다. 애플리케이션 assertion 실패는 아니었다.
- 보완 PR #351 첫 CI: `test` 1분 39초 성공, `bundled-ocr` 51초 성공. 아래 최종 문서 커밋 뒤 CI도 병합 전에 다시 확인한다.

## 7. 미검증 항목

- 운영 R2 상태 객체의 실제 쓰기 권한: 미검증(비파괴 코드·설정 경로만 점검, 상태 쓰기 미실행).
- PR #341 병합 뒤 실제 화면: 미검증(PR이 아직 열림).
- 운영 R2 인덱스의 현재 기사 내용·건수와 최근 1주 수집 간격: 미검증(H1 평가에서 확인).
- 8개 병원 × 비교군 5종의 H2 브리핑: H2 미구현. H0에서는 custom을 제외한 4종의 2024 유효 n만 계산.
- 운영 배포와 캡처: 보완은 문서 전용이라 미실행.

## 8. 리뷰 B1~B6·R1~R7 처리 결과

| 항목 | 처리 |
| --- | --- |
| B1 | 운영 쓰기 권한을 `미검증`으로 정정하고 확인 방법·날짜·현재 UI의 낙관적 문구·H1 중립 문구·미확인 unread 제외 결정을 기록 |
| B2 | 현재 +3/+4/+2/출처 가중치, 동점 최신순, 출처 tier와 H1 재사용 원칙 기록 |
| B3 | 제목 불일치 항목을 H1 군집·수치·평가에서 제외하고 `본문에서만 언급`을 수정 대상으로 기록 |
| B4 | 5-A 현재 최대 7개+추이 결합과 5-B 최대 3+2개·n≥3·헤더·추가확인 안내를 분리 |
| B5 | 두 빈 상태 표에 현재 문구·위치·유지/수정/신규·이유를 추가. stale 다음 행동 유지, 전체 실패 예외 노출을 H1 수정으로 등록 |
| B6 | 8×4×7 계산 완료. 32조합 중 17개 n≥3, 15개 n<3. 임시 스크립트 미커밋 |
| R1 | core 2016~2024, size peers 2019~2024로 정정 |
| R2 | 회계기간 경고, AI, ALIO, KHIDI, 주간 리포트, 중립 지표, 화면 4/리포트 3 추이를 기록 |
| R3 | AI 미연결 안내를 H2에서 상단 브리핑 아래 보조 영역으로 이동하는 대상으로 등록 |
| R4 | CAGR ×100·양수·정확 연도, 재료비 부분 합산, 700~850/±100, custom 2~10 UI, R2 날짜 폴더 삭제, 반올림 전 허용폭 기록 |
| R5 | 최근 1주 실제 간격 자료가 없어 H1 평가로 보류. 1시간 stale 적합성을 평가표에서 결정 |
| R6 | 뉴스 제목은 #341 소유, 경영 제목은 H2에서 Track H 페이지 안에서 변경. 공통 메뉴는 미수정 |
| R7 | 로컬 3개 실패를 Windows 로컬 관찰·CI 녹색·원인 미조사로 정정 |

Fable Review에서 중간 심각도 1건(8×4 표가 선택 N과 지표별 유효 n을 한 숫자로 축약해 B6 확인이 모호함)과 낮은 심각도 1건(동시 Track P 병합 뒤 조사 기준 SHA가 오래됨)을 찾았다. 표를 `선택 N / 유효 n×7` 형식으로 바꾸고 기준을 `2206160`으로 갱신해 닫았다. 남은 Critical/High 결함은 발견하지 못했다.

## 9. 사용자 결정과 다음 Phase 시작 조건

현재 작업지시서와 리뷰를 함께 적용한 결정 상태:

1. 제목 불일치 기사: H1 군집·기사 수·매체 수·평가 표본에서 제외(확정).
2. unread 상단 지표: 저장 능력 미확인 상태에서는 제외(확정, PR #341 구조와 일치).
3. 최소 유효 n=3: 작업지시서 값은 유지하되, 15/32 조합 전체 보류 결과를 근거로 H2 전 사용자 재확인 필요.
4. 재료비 부분 합산: 현재 동작은 확인했으나 H2 표시/자료 없음 정책은 사용자 결정 필요.

H1 착수 조건은 (a) H0 보완 PR 병합, (b) PR #341 병합, (c) B1 결과 문서화다. (c)는 완료했으나 (b)는 아직 충족되지 않았다.

## 10. 재현 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:NEWS_RADAR_INDEX_PATH = '.local/news-radar.json.gz'
python -m purchase_price.scripts.collect_news_radar --output .local/news-radar.json.gz --no-alert
streamlit run Home.py --server.port 8602
```

유효 n 계산은 저장소 uv Python으로 `load_benchmark_data()`를 읽고 core 8곳, `region/network/similar_size/same_type`, `bed_range=(700,850)`, `fiscal_year=2024`, `HEADLINE_METRICS`의 `peer_count`를 출력했다. 별도 파일은 만들지 않았다.

## 11. 캡처·결과 예시 경로

- H0 보완은 화면 변경 없음: 캡처 없음.
- 뉴스 계약: `docs/metrics/news.md`.
- 경영 계약 및 8×4 계산표: `docs/metrics/hospital_management.md`.

## 12. 공통 파일 변경 요청

없음. PR #341의 홈·뉴스 단순화 변경은 기존 PR 범위이며 Track H에서 수정하거나 병합하지 않았다.
