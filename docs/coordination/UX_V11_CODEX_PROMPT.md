# Codex 작업 지시 프롬프트 — Track H (병원 뉴스·경영)

아래 내용을 그대로 Codex에 붙여 넣는다. `BASE_SHA`는 `docs/coordination/UX_V11_BASE.md`의 값으로 바꾼다.

---

당신은 `dekt-oss/price-check-assistant` 저장소에서 **Track H (병원 뉴스·병원 경영정보)** 를 맡는다. 가격 조사 쪽(Track P)은 다른 에이전트(Claude)가 같은 시간에 작업하므로, 아래 규칙을 어기면 서로의 작업을 망가뜨린다.

## 1. 먼저 읽을 문서 (저장소 `main`에 있음)
1. `docs/coordination/UX_V11_WORK_ORDER_v1.2.md` — 최종 작업지시서. 6장(Track H)과 3·4·8·9장을 정독.
2. `docs/coordination/UX_V11_OWNERSHIP.md` — 당신이 고칠 수 있는 파일의 전체 목록. **여기 없는 파일은 고치지 않는다.**
3. `docs/coordination/UX_V11_BASE.md` — 기준 커밋(BASE_SHA), 브랜치, 포트.
4. `docs/HOSPITAL_INTELLIGENCE_PHASE1_20261008.md`, `docs/NEWS_RADAR_ALERTS.md` — 현재 구현 상태.
5. `CLAUDE.md`의 "작업 결과 보고" 형식 — 각 Phase 보고에 같은 형식을 쓴다.

## 2. 작업 환경
- 브랜치 `codex/ux-v11-news-management`는 이미 `origin`에 있다(BASE_SHA에서 분기). 새로 만들지 말고 체크아웃한다. 워크트리는 `.worktrees/ux-v11-news-management`가 준비돼 있다. 자체 워크트리를 쓰려면 반드시 이 브랜치에서 만든다.
- `main` 체크아웃(`C:\Users\임준혁\projects\price-check-assistant`)에서는 절대 커밋하지 않는다. 커밋·푸시 전에 `git branch --show-current`가 `codex/ux-v11-news-management`인지 확인한다.
- `git stash`를 쓰지 않는다(워크트리 간 공유). 임시 WIP 커밋을 쓴다.
- 로컬 앱 포트는 **8602~8609**만 쓴다. 뉴스 인덱스는 `NEWS_RADAR_INDEX_PATH=.local/news-radar.json.gz`로 로컬 파일을 쓴다(`docs/HOSPITAL_INTELLIGENCE_PHASE1_20261008.md`의 "로컬에서 R2 없이 확인" 참조).
- 파이썬은 레포의 uv 3.11 가상환경을 쓴다. `PYTHONPATH=src`.
- PR #341(홈 카드·뉴스 화면 단순화)이 BASE_SHA 뒤에 `main`에 머지됐으면 시작 전에 `git merge origin/main`을 한 번 한다. 충돌이 나면 당신 파일(`pages/20_…`, `tests/test_news_radar_page.py`, `tests/test_hospital_intelligence_phase1_contract.py`)만 해결한다.

## 3. 절대 규칙
- `UX_V11_OWNERSHIP.md`의 Track H 목록 밖 파일을 수정하지 않는다. 특히 `Home.py`, `pages/0_홈.py`, `src/purchase_price/ui/theme.py`, `widgets.py`, `runtime_secrets.py`, `config.py`, `requirements.txt`, `pyproject.toml`, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/test_streamlit_startup_smoke.py`, `tests/test_navigation_contract.py`, 그리고 `track_b_*`·`g2b_*`·`mfds_*`·`quote_*`·`result_*`·`category_market` 등 가격 쪽 파일 전부. 필요하면 HANDOFF의 "공통 파일 변경 요청"에 적는다.
- `requirements.txt`의 `# Revision` 줄을 바꾸지 않는다(운영 앱 재시작·리소스 한도 사고 원인).
- 네이버 검색 API 약관: 기사 `description`(본문 요약)을 읽지 않고, 검색 결과를 AI 요약·분류·학습에 넘기지 않으며, 21일 넘게 보관하지 않는다. `tests/test_hospital_intelligence_phase1_contract.py`가 이를 검사한다. 이 단언을 약화하지 않는다.
- 결정적 규칙만 쓴다. 뉴스 군집·점수·경영 브리핑 문장에 LLM을 쓰지 않는다. 기존 AI 경영 설명(`hospital_ai_explanation.py`)은 선택 기능으로 그대로 둔다.
- 금지 표현(작업지시서 3.5): 적정, 권장, 싸다·비싸다, 절감액, 대체 가능, 안전한 제품, 원인 확정, 개선 필요·우수·부진, 인기·대표·추천.
- 화면 동작을 바꾼 모듈에는 런타임 마커(예: `hospital_benchmark.MODULES_REVISION` 올리기, 뉴스 페이지는 같은 방식의 상수)를 둔다. 운영 Streamlit Cloud는 배포 뒤 옛 모듈을 붙드는 일이 있다.
- 작업 한도에 도달하면 "완료"라고 쓰지 않는다. HANDOFF에 현재 상태와 재개 지점을 남긴다.

## 4. 순서 — Phase 하나 = PR 하나(대상 `main`, 제목 `[H0] …`, `[H1] …`, `[H2] …`)

### Phase H0 — 현재 구현 조사 (코드 변경 없음)
산출물: `docs/metrics/news.md`, `docs/metrics/hospital_management.md`, `docs/handoffs/HANDOFF_H0.md`.
반드시 담을 것: 뉴스 데이터 계약(쓸 수 있는 필드 5개, 쓸 수 없는 것), 읽음·중요 상태가 운영에서 세션에만 남는 사실, #341 반영 뒤 뉴스 화면 구조, 경영 지표 목록·비교군 5종·공시연도 범위(2016~2024)·병상수 출처 두 가지(심평원 동기화 vs 공시 `info.bsNum`)·리포트 경로, 뉴스·경영 빈 상태 매트릭스의 확정 문구, 키워드 설정 요구사항과 저장 위치. 경영 브리핑 지표 산식(비율 지표 %p 차이, 금액 지표 % 차이, 평균 = 유효값 단순 평균 + n, 허용폭 ±1%p/±5%, 유효값 3곳 미만 = 비교 보류)을 문서에 적는다.

### Phase H1 — 병원 뉴스 주요 이슈
1. 저장된 뉴스 인덱스(R2 `news/v1/index.json.gz` 또는 로컬 수집분)에서 30~50건 표본을 뽑아 수작업으로 "같은 사건" 묶음을 만든다. 이것이 평가 기준이다.
2. `services/news_radar_index.py`(또는 새 `services/news_issues.py`)에 제목·매체·시각·키워드 그룹만 쓰는 군집·점수 함수를 순수 함수로 만든다. 시간 창·유사도 임계는 1번 표본으로 잘못 묶임·누락 비율을 재고 정한 뒤 문서에 적는다.
3. 수집 Job(`scripts/collect_news_radar.py`)이 군집을 계산해 인덱스에 저장한다. 인덱스 버전을 올리고 v1을 읽을 수 있게 한다.
4. `pages/20_병원_News_Radar.py` 상단에 `오늘의 주요 이슈` 최대 5개(이슈 제목, 관련 병원·분류, 매체 수, 기사 수, 최초·최근 보도 시각, 대표 기사 링크, `관련 기사 N건` 접기). 기존 목록과 #341의 `준비 중` 알림 안내는 유지한다.
5. 인수 조건(작업지시서 6장 H1) 전부 확인. 산출물: `docs/NEWS_ISSUE_CLUSTER_EVAL_<날짜>.md`(표본 평가표), 캡처, `HANDOFF_H1.md`.

### Phase H2 — 병원 경영 브리핑
1. `services/hospital_metrics.py`의 `describe_findings`·`gap_trend`를 확장해 브리핑 문장(차이 큰 지표 최대 3개 + 최근 변화 큰 지표 최대 2개 + 추가 확인 안내)을 결정적으로 만든다. 첫 줄은 항상 `YYYY 회계연도 공시 기준 · 비교병원 N곳`.
2. `pages/21_병원_경영_Benchmark.py` 상단에 브리핑을 두고 정보 계층을 브리핑 → 핵심 지표 → 그래프 → 비용 구조 → 전체 지표·자료 상태로 정리한다.
3. `services/hospital_report.py`의 Markdown·Excel 리포트 상단에 같은 브리핑을 넣고 화면과 수치가 같은지 테스트한다.
4. 8개 병원 × 비교군 5종에서 예외 없이 생성되는 테스트, 금지어 테스트, `비교 보류` 테스트. 산출물: 브리핑 예시, `HANDOFF_H2.md`.

## 5. PR 전 확인
```bash
ruff check .
pytest -q tests/test_streamlit_startup_smoke.py
pytest -q tests/test_news_radar.py tests/test_news_radar_index.py tests/test_news_radar_page.py tests/test_news_radar_workflow_contract.py tests/test_news_relevance_and_alerts.py tests/test_news_subscriptions.py tests/test_collect_news_radar.py tests/test_naver_news_client.py tests/test_next_news_radar_run.py tests/test_hospital_benchmark.py tests/test_hospital_intelligence_phase1_contract.py tests/test_hospital_master.py tests/test_hospital_metrics.py tests/test_hospital_phase4.py tests/test_khidi_financials.py tests/test_alio_disclosure.py tests/test_hira_hospital_info.py
pytest -q
```
Windows에서 OCR 실환경 테스트 4건 실패는 알려진 환경 문제다. HANDOFF에 적고 CI 녹색을 기준으로 삼는다. PR 본문에 실행한 명령과 결과를 적는다. CI가 녹색이면 스쿼시 머지하고, 머지 뒤 운영 `https://bp-price-research.streamlit.app`에서 `/news-radar`, `/hospital-benchmark`를 열어 캡처를 HANDOFF에 넣는다.

## 6. 각 Phase 끝에 보고할 것
`docs/handoffs/HANDOFF_H<n>.md`(작업지시서 8장의 12항목) 작성 후, `CLAUDE.md`의 다섯 덩어리 형식(시키신 것 / 문제가 뭐였나 / 어떻게 해결했나 / 이렇게 확인하세요 / 다음 작업)으로 사용자에게 보고한다. 확인하지 못한 것은 `(미검증)`으로 표시한다.
