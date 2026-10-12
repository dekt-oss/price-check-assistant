# HANDOFF H0 — 병원 뉴스·경영 현재 구현 조사

## 1. 기준 커밋과 작업 브랜치

- 작업지시서 BASE_SHA: `ecb888bada895fec30443a951dfc09ab2e90a54e`
- Phase 시작 HEAD: `020224cf50f9e054e02982e1fac9d319dd6b6cd1`
- 브랜치: `codex/ux-v11-news-management`
- 워크트리: `.worktrees/ux-v11-news-management`
- 원격 확인일: 2026-10-12 KST
- PR #341: 커밋 `087fae2`, 조사 시점 `origin/main` 미머지

## 2. Phase 목적

H1·H2에서 기존 기능을 중복 구현하거나 약관·데이터 의미를 바꾸지 않도록 뉴스 데이터 계약, 운영 지속성, 경영 지표와 비교 규칙, 빈 상태 문구를 코드 기준으로 확정한다. H0에서는 화면과 실행 코드를 변경하지 않는다.

## 3. 완료한 요구사항

- 뉴스에서 사용할 수 있는 필드 5종과 금지 데이터를 문서화했다.
- NAVER description·본문·AI 미사용과 21일 보관 경계를 명시했다.
- 운영 앱의 읽음·중요 상태가 현재 세션에만 유지되는 이유를 기록했다.
- PR #341 반영 뒤 예정 화면 구조를 커밋 diff로 정리했다.
- 키워드 정본, 화면 토글의 저장 위치와 지속성을 분리했다.
- 경영 지표 16개, 핵심 지표 7개, 비교군 5종을 기록했다.
- 공시연도 2016~2024와 8개 기본 병원 범위를 확인했다.
- 심평원 현재 병상수와 공시연도 병상수의 우선순위를 기록했다.
- 경영 브리핑 평균·n·차이·허용폭·비교 보류 산식을 확정했다.
- 뉴스·경영 빈 상태 매트릭스의 문구를 확정했다.
- 화면·로컬·Actions·R2 리포트 경로를 기록했다.

## 4. 변경 파일 목록과 허용목록 대조

| 파일 | 변경 | 소유권 |
| --- | --- | --- |
| `docs/metrics/news.md` | 신규 | Track H 허용 문서 |
| `docs/metrics/hospital_management.md` | 신규 | Track H 허용 문서 |
| `docs/handoffs/HANDOFF_H0.md` | 신규 | Track H 허용 문서 |

코드, 설정, 공통 파일, 가격 파일은 변경하지 않았다.

## 5. 데이터 계약·API·인덱스 버전 변경

- 실행 코드 변경 없음
- API 변경 없음
- 인덱스 버전 변경 없음. 현재 `news/v1/index.json.gz`, `version=1`
- H1 예정: 허용된 5개 필드만으로 이슈 정보를 저장하고 v1 읽기 호환을 유지해야 함

## 6. 실행한 테스트와 실제 결과

환경:

- Python `3.11.15`
- 저장소 루트 uv 가상환경 Python 사용
- `PYTHONPATH=<Track H worktree>/src`

문서·정적 검사:

```powershell
ruff check .
```

결과: `All checks passed!`.

Streamlit 기동 스모크:

```powershell
python -m pytest -q --basetemp C:\tmp\price-check-h0-startup-20261012-2220 `
  tests/test_streamlit_startup_smoke.py
```

결과: `1 passed, 1 warning in 23.35s`.

Track H 지정 회귀 테스트:

```powershell
python -m pytest -q --basetemp C:\tmp\price-check-h0-trackh-20261012-2222 `
  tests/test_news_radar.py tests/test_news_radar_index.py tests/test_news_radar_page.py `
  tests/test_news_radar_workflow_contract.py tests/test_news_relevance_and_alerts.py `
  tests/test_news_subscriptions.py tests/test_collect_news_radar.py `
  tests/test_naver_news_client.py tests/test_next_news_radar_run.py `
  tests/test_hospital_benchmark.py tests/test_hospital_intelligence_phase1_contract.py `
  tests/test_hospital_master.py tests/test_hospital_metrics.py tests/test_hospital_phase4.py `
  tests/test_khidi_financials.py tests/test_alio_disclosure.py tests/test_hira_hospital_info.py
```

결과: `164 passed, 2 warnings in 26.54s`.

H0 기준 테스트:

```powershell
python -m pytest -q --basetemp C:\tmp\price-check-h0-baseline-20261012-2215 `
  tests/test_news_radar_page.py `
  tests/test_hospital_intelligence_phase1_contract.py `
  tests/test_hospital_metrics.py `
  tests/test_hospital_benchmark.py
```

결과: `25 passed, 2 warnings in 18.66s`.

전체 테스트:

```powershell
$env:PYTHONUTF8 = '1'
python -m pytest -q --basetemp C:\tmp\price-check-h0-full-utf8-20261012-2230
```

결과: `1670 passed, 7 failed, 3 warnings in 100.07s`.

Windows OCR 환경 문제로 확인된 4건:

- `test_ocr_execution_readiness_real.py::test_synthetic_pdf_rasterize_and_tesseract_execution`
- `test_pdf_ocr_real_e2e.py::test_real_image_only_pdf_runs_tesseract_and_extracts_quote`
- `test_quote_image_ocr_e2e.py::test_real_image_quote_ocr_e2e[.png]`
- `test_quote_image_ocr_e2e.py::test_real_image_quote_ocr_e2e[.jpg]`

별도 독립 실행에서도 실패한 Track P 소유 테스트 3건:

- `test_quote_ruled_table_ocr.py::test_quote_extraction_prefers_ruled_table_recovery`
- `test_quote_single_item_ocr_fallback.py::test_quote_extraction_uses_footer_fallback_only_after_zero_items`
- `test_quote_uat_streamlit_upload.py::test_quote_uat_page_survives_real_xlsx_upload`

독립 실행 결과는 `3 failed, 2 warnings in 7.28s`다. H0는 문서만 변경했고 해당 가격·견적 파일과 테스트는 Track P 소유이므로 수정하지 않았다. CI 녹색 여부를 병합 기준으로 삼는다.

경고:

- Python 3.12에서 제거 예정인 `load_module()` deprecation 1건
- 한글 사용자 경로의 `.pytest_cache` 생성 권한 경고 1건

처음 두 차례는 Windows 기본 pytest 임시 폴더 및 샌드박스 `C:\tmp` 쓰기 권한 때문에 `14 passed, 11 errors`였으며, 코드 실패가 아니라 fixture 임시 디렉터리 생성 실패였다. 권한이 허용된 실행에서 명시적 `--basetemp`로 재실행해 위 결과를 얻었다.

## 7. 미검증 항목

- PR #341 병합 뒤 실제 Track H 브랜치 화면: 미검증(아직 main 미머지)
- 운영 R2 인덱스의 현재 기사 내용·건수: 미검증
- 운영 Streamlit의 읽음·중요 상태 동작: 문서·코드로 확인, 브라우저 실동작 미검증
- 8개 병원 × 비교군 5종 브리핑: H2 미구현
- 운영 배포와 캡처: H0는 화면 변경이 없어 미실행

## 8. 알려진 위험

1. H1은 PR #341 위에서 작업해야 한다. 머지 전에 페이지 구현을 시작하면 뉴스 페이지 충돌 가능성이 높다.
2. 현재 인덱스 로더는 `version=1`만 허용한다. H1이 버전을 올릴 때 v1 변환 경로가 없으면 운영 인덱스를 읽지 못한다.
3. 운영 앱 R2 키가 읽기 전용이므로 읽음·중요 상태를 중요도 입력으로 쓰면 세션마다 결과가 달라진다.
4. 경영 지표별 유효 비교병원 수가 다르므로 화면 첫 줄의 선택 비교병원 N과 지표별 n을 혼동하면 안 된다.
5. 실행계획 보조 스크립트 `sdd-workspace`는 한글 Windows 경로를 처리하지 못해 임시 ledger를 만들지 못했다. 저장소 변경은 없었고 이 HANDOFF를 재개 기록으로 사용한다.
6. 전체 로컬 테스트에서 Track P 소유 견적 fallback/UAT 테스트 3건이 OCR 환경 4건과 별도로 실패했다. H0 변경과 무관한 기존 상태로 보이지만 CI 확인 전에는 회귀가 없다고 확정하지 않는다.

## 9. 다음 Phase 시작 지점

1. `git fetch origin main`으로 PR #341 병합 여부를 다시 확인한다.
2. `087fae2`가 `origin/main`의 조상이면 브랜치를 확인한 뒤 `git merge origin/main`을 한 번 수행한다.
3. H1을 위한 저장 뉴스 30~50건 표본을 로컬 `.local/news-radar.json.gz` 또는 허가된 R2 읽기로 확보한다.
4. 표본의 같은 사건 정답 묶음을 `docs/NEWS_ISSUE_CLUSTER_EVAL_<날짜>.md`에 먼저 만든다.
5. 실패하는 군집·인덱스 호환·페이지 계약 테스트를 먼저 작성하고 RED를 확인한다.

## 10. 재현 명령

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:NEWS_RADAR_INDEX_PATH = '.local/news-radar.json.gz'
python -m purchase_price.scripts.collect_news_radar --output .local/news-radar.json.gz --no-alert
streamlit run Home.py --server.port 8602
```

PR #341 확인:

```powershell
git fetch origin main
git merge-base --is-ancestor 087fae2 origin/main
```

종료 코드 0이면 병합된 상태다.

## 11. 캡처·결과 예시 경로

- H0 화면 변경 없음: 캡처 없음
- 뉴스 계약: `docs/metrics/news.md`
- 경영 계약: `docs/metrics/hospital_management.md`

## 12. 공통 파일 변경 요청

없음. PR #341의 `pages/0_홈.py` 변경은 기존 PR 범위이며 H0에서 수정하지 않았다.
