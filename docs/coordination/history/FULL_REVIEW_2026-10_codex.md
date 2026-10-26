# 전체 리뷰 — UI/UX·DB·운영·속도·코드

**미완료 — 끝낸 영역:** A~E 핵심 경로 정적 리뷰, 운영 7개 URL 각 3회, HeartOn·사이드바 이동 추가 측정, 전체 pytest/Ruff/importtime, 합성 견적·부분조회·SQL·메모리 재현. **남은 영역:** 정상 R2 full-index 로컬 함수 프로파일·RSS 피크, 정상 서버 cold 3회, 최신 데이터 정답셋 감사. **재개 지점:** 7절. 아래 확인된 결함은 이 누락과 독립적으로 재현되며, 전체 리뷰 완료·운영 승인으로 해석하지 않는다.

- 리뷰 SHA: `c7d775da7550750e25f61b987d16eff809d27605` (`origin/main`, PR #373). 2026-10-26 fetch로 확인.
- 리뷰 날짜: 2026-10-26~27 KST. 파일명은 요청대로 2026-10을 유지.
- 브랜치: `codex/full-review-2026-10`, Codex 관리 전용 워크트리.
- 변경 범위: 리뷰 본문·수신 프롬프트 원문만. 코드/설정/운영 데이터 변경, 운영 업로드, 상태 저장, 워크플로 실행, Reboot, 머지 없음.
- 심각도: 치명 0건 관측(전수 보증 아님), 높음 7건, 중간 9건.

## 1. 총평

1. 우선 차단할 것은 같은 이름의 새 견적서를 이전 견적으로 처리하는 오류와, 끝까지 읽지 않은 실시간 조회를 성공·0건으로 표시하는 오류다.
2. 반복 조회 때 빠르게 보이지만 첫 NT960 13.742초·HeartOn 16.006초와 당일 CI 14초대가 남는다. 참고거래 25행에 SELECT 105회가 재현된다.
3. 감시가 실제 과업에 닿지 않는다. 주간 OCR 스모크는 숨긴 메뉴에서 실패했고 기사 포함 보고서의 보관 시계는 원본 기사와 다르다.
4. 같은 구조로 3개월간 이력·문서가 늘면 게시 메모리, 대기 실행 교체, 낡은 검증 결과 오인 비용이 커질 가능성이 있다(추정).
5. 관측가격/조건 확인 분리, 불변 원본·버전 인덱스, 지표 회귀 테스트는 존재한다. 테스트 개수만으로 경계 오류와 운영 과업을 보증하지는 못한다.

## 2. 측정 결과표

### 2.1 환경과 정의

로컬: 저장소 기존 uv 가상환경(`pyvenv.cfg`: uv 0.11.28, CPython 3.11), Python 3.11.15, Streamlit 1.63.0, pandas 2.3.3, SQLAlchemy 2.0.52, pytest 8.4.2, Ruff 0.16.6. `PYTHONPATH=<리뷰 워크트리>/src`, `PYTHONUTF8=1`. .env/운영 키를 복사하지 않았으며 R2/G2B/MFDS 미설정은 불리언으로 확인했다.

운영: Windows Playwright Chromium, 1440×1000, 한 브라우저·페이지로 순차 재진입. q 검색은 iframe 내부 `#purchase-conclusion-v1`, 그 밖은 실제 본문 `.pc-title`/제목 표시까지 측정했다. 제목 표시는 모든 블록 완료와 다르다. 마커는 `purchase-search-timings-v2`, `purchase-render-timings-v1`이다. 외곽 HTML/iframe 생성만 잰 예비값, 잘못된 제목 선택자로 생긴 90초 대기는 제외했다.

모든 검색 마커는 `cold=0`, `warmup_wait=0`. 첫 브라우저 방문을 서버 cold로 부르지 않는다. Reboot/캐시 삭제를 하지 않았다. n=3에는 중앙값·범위를 사용하고 장기 p95를 추정하지 않는다.

### 2.2 운영 직접 측정

| 항목 | 원시 표본(초), n=3 | 중앙값 초 | 완료 지점 / 일시(KST) |
| --- | --- | ---: | --- |
| `/` | 7.683 / 3.452 / 2.569 | 3.452 | 본문 제목, 10-27 00:03 |
| `/?q=PNB-704&period=5y` | 6.766 / 5.845 / 5.339 | 5.845 | 결론 카드, 10-27 00:03 |
| `/?q=SJ-DFM100` | 5.887 / 5.332 / 5.356 | 5.356 | 결론 카드, 10-27 00:04 |
| `/?q=NT960XJG-K72AG` | 13.742 / 7.895 / 5.296 | 7.895 | 결론 카드, 10-27 00:04 |
| `/news-radar` | 3.996 / 3.227 / 3.199 | 3.227 | 본문 제목, 10-27 00:05 |
| `/hospital-benchmark` | 2.586 / 2.682 / 2.569 | 2.586 | 본문 제목, 10-27 00:05 |
| `/home` | 2.593 / 2.509 / 3.678 | 2.593 | 본문 제목, 10-27 00:05 |
| HeartOn A16-DS 추가 검색 | 16.006 / 7.641 / 8.001 | 8.001 | 카드, 10-27 00시대 |
| 사이드바 → 병원 뉴스 | 1.502 / 0.918 / 1.987 | 1.502 | 목적 제목, 10-27 00시대 |
| 사이드바 → 병원 경영 비교 | 2.655 / 2.449 / 1.651 | 2.449 | 목적 제목, 10-27 00시대 |
| 사이드바 → 홈 | 1.032 / 2.425 / 1.844 | 1.844 | 목적 제목, 10-27 00시대 |

첫 `/` 표본 7.683초에는 브라우저·페이지 초기 비용이 포함된다. 운영 견적 업로드는 금지 범위여서 미실행. 뉴스 새 기사 확인·읽음·중요·구독도 변경하지 않았다. 7개 경로 모두 본문/결론에 도달했다.

### 2.3 서버 단계와 기준선 비교

| 모델 | 서버 total | 동일 조회 | 다른 모델 집계 | 제품군 | live | 안전 | 카드 렌더 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PNB-704 | 1.561 | 0.407 | 0.000 | 0.000 | 0.434 | 0.662 | 0.591 |
| SJ-DFM100 | 1.154 | 0.400 | 0.015 | 0.037 | 0.000 | 0.666 | 0.650 |
| NT960XJG-K72AG | 1.738 | 1.031 | 0.000 | 0.000 | 0.000 | 0.637 | 0.639 |
| HeartOn A16-DS | 2.873 | 0.351 | 0.892 | 0.502 | 0.443 | 0.675 | 미수집 |

단위는 초, 같은 직접 표본의 중앙값. 중첩 단계이므로 합산하지 않는다. HeartOn 렌더 마커는 추가 측정에서 미수집.

HeartOn 첫 표본은 same_item_models=4.559, category_market=1.240, total=7.939초였지만 반복 집계는 0.892/0.792초다. NT960 조회는 9.442→1.031→0.937초다. warm 마커는 모델별/디스크 캐시의 온도를 보증하지 않는다.

기준선 `docs/performance/UX_V11_PRICE_BASELINE.md` 11장(10-13, 새 페이지 n=10)의 wall p50/p95는 PNB 10.370/13.057, SJ 10.139/10.961, HeartOn 16.116/19.755, NT960 18.348/19.855초다. 이번 n=3 중앙값은 5.845/5.356/8.001/7.895초이나 **개선 배포의 인과 증거는 아니다**. PNB는 5년이고 브라우저 수명·진입 방식·시점·원본 행 수가 다르다.

[당일 Price Search Timings run 40271023077](https://github.com/dekt-oss/price-check-assistant/actions/runs/40271023077)의 artifact를 읽었다(10-26 13:50~13:51 KST, 모델당 n=1). wall은 PNB 8.642, SJ 8.079, HeartOn 14.368, NT960 14.660초. HeartOn 집계 4.487·제품군 1.162초, NT960 조회 7.310초다. 소스 SHA는 동일하다. 실행 success와 모든 모델의 속도 목표 충족은 다르다.

### 2.4 로컬 견적·프로파일·확장성

| 항목 | 측정값 | 방법 / 시점 |
| --- | --- | --- |
| 가짜 XLSX 직접 추출 | 0.0095/0.0032/0.0047초, 중앙값 0.0047초, 매번 품목 1개 | openpyxl, 가상 업체·모델·123456원 1행 → extract_quote_file, 10-27 00시대 |
| 로컬 업로드→카드 | 0.914/7.401/0.859초, 중앙값 0.914초 | localhost:8602, 재진입→file input→결론 마커. 가격 연결 불가 상태 포함 |
| 같은 파일명 내용 교체 | 새 002·654321원을 올려도 이전 001·123456원 표시 | same-quote.xlsx 두 payload, A-01 |
| 키 없는 실제 검색 함수 | PNB 0.0816초, NT960 0.1052초, Track B unavailable | 실제 _execute_search cProfile. 정상 운영과 비교 불가 |
| 0건 뒤 참고거래 SQL | 1/5/25행→SELECT 9/25/105회, deferred 4/20/100회 | 새 합성 SQLite·Session, before_cursor_execute, D-01 |
| 참고 25행 프로파일 | 전체 0.0874초, 참고 조회 0.068, 조건 읽기 0.061초 | 실제 comparator cProfile. 운영 SQL 실행시간 대용 아님 |
| 인덱스 게시 메모리 | SQLite 16.03MiB→Python 할당 피크 61.40MiB/0.597초, 32.05MiB→109.44MiB/1.111초 | 난수 BLOB SQLite, 실제 put_sqlite·가짜 S3·tracemalloc. RSS 아님 |

가짜 견적은 파일 선택/업로드 뒤 첫 품목 카드로 자동 이동한다. 최소 UI 조작은 업로더 열기와 파일 선택이며 OS 파일창 동작은 자동 주입으로 대체했다. **실제 결재 근거 확보 시간·클릭 수는 미검증**이다. 가상 모델에 가격을 만들지 않고 연결 불가로 끝났기 때문이다. 원문·조건 대조·승인·내보내기를 업로드 시간에 합쳐 추정하지 않았다.

로컬 비검색 페이지에서 없는 검색창을 15초 기다린 초기 스크립트 값은 폐기했다. 정상 full-index 로컬 n=3 프로파일은 미확보다.

**참고거래 경로 cProfile 상위 10개(누적 초)**

| 함수 | 초 | 호출 |
| --- | ---: | ---: |
| track_b_db_quote_comparison.compare_track_b_quote | 0.087 | 1 |
| _find_reference_candidates | 0.068 | 1 |
| SQLAlchemy attributes.__get__ | 0.061 | 1039 |
| _row_conditions | 0.061 | 25 |
| attributes.get | 0.060 | 100 |
| _fire_loader_callables | 0.060 | 100 |
| strategies._load_for_state | 0.060 | 100 |
| loading.load_scalar_attributes | 0.058 | 100 |
| loading.load_on_ident | 0.055 | 100 |
| loading.load_on_pk_identity | 0.054 | 100 |

중첩시간이므로 합산하지 않는다. 키 없는 실제 검색 함수에서는 Settings 생성·환경 분석이 대부분이었다(PNB Settings 생성 누적 0.057초, NT960 0.098초). 데이터 경로를 타지 않은 값을 정상 운영의 상위 함수라고 주장하지 않는다.

### 2.5 Ruff·pytest·import

전용 워크트리에서 기존 uv Python으로 `-m ruff check .`, `-m pytest -q --durations=25`, `-X importtime -c "import streamlit; import purchase_price"`를 실행했다. Ruff: `All checks passed!`. pytest: **7 failed, 1875 passed, 3 warnings in 126.32s**(10-26 23:54~23:56 KST). 요청문의 1834 passed보다 41건 늘었다. 제한 환경의 최초 파일 권한 오류는 버리고 허용 권한 재실행만 집계했다.

실패는 OCR 4/fallback 2/XLSX UAT 업로드 1로 알려진 실패군과 일치한다. 범주가 같다는 뜻이며 운영에서 원인이 같다는 뜻은 아니다. 이 실행의 그 밖 실패는 0건. UTF-8 모드여서 cp949 재현은 미실행이다.

- test_ocr_execution_readiness_real.py::test_synthetic_pdf_rasterize_and_tesseract_execution
- test_pdf_ocr_real_e2e.py::test_real_image_only_pdf_runs_tesseract_and_extracts_quote
- test_quote_image_ocr_e2e.py::test_real_image_quote_ocr_e2e[.png]
- test_quote_image_ocr_e2e.py::test_real_image_quote_ocr_e2e[.jpg]
- test_quote_ruled_table_ocr.py::test_quote_extraction_prefers_ruled_table_recovery
- test_quote_single_item_ocr_fallback.py::test_quote_extraction_uses_footer_fallback_only_after_zero_items
- test_quote_uat_streamlit_upload.py::test_quote_uat_page_survives_real_xlsx_upload

**느린 테스트 25개(call 시간)**

| 초 | 테스트 |
| ---: | --- |
| 12.43 | `tests/test_doctor.py::test_real_environment_has_no_blocking_check` |
| 11.12 | `tests/test_track_b_db_quote_comparison.py::test_missing_db_is_unavailable_not_zero_results` |
| 8.64 | `tests/test_streamlit_startup_smoke.py::test_all_streamlit_pages_start_without_runtime_exception` |
| 6.21 | `tests/test_doctor.py::test_service_key_value_is_never_printed` |
| 4.60 | `tests/test_hospital_phase4.py::test_reports_build_for_eight_core_hospitals_and_all_five_peer_groups` |
| 4.07 | `tests/test_device_research_handoff.py::test_device_research_page_prefills_quote_identity` |
| 3.12 | `tests/test_doctor.py::test_database_error_reports_a_reason_for_an_unreachable_url` |
| 2.90 | `tests/test_hospital_benchmark.py::test_page_marks_briefing_on_hold_when_valid_peers_are_below_three` |
| 2.06 | `tests/test_track_b_search_index.py::test_side_index_returns_exactly_the_original_results` |
| 2.02 | `tests/test_market_reference_summary_call_contract.py::test_all_market_reference_summary_calls_pass_query_keyword` |
| 1.78 | `tests/test_hospital_intelligence_phase1_contract.py::test_hospital_intelligence_tables_migrate_and_downgrade` |
| 1.70 | `tests/test_quote_uat_streamlit_upload.py::test_quote_uat_page_survives_real_xlsx_upload` |
| 1.50 | `tests/test_hospital_benchmark.py::test_page_shows_loaded_values_and_quality_box` |
| 1.38 | `tests/test_ux_v11_integration.py::test_price_code_does_not_import_track_h_modules` |
| 1.31 | `tests/test_pdf_ocr_real_e2e.py::test_real_image_only_pdf_runs_tesseract_and_extracts_quote` |
| 1.10 | `tests/test_track_b_search_index.py::test_index_behind_the_table_is_ignored_until_the_sync_catches_up` |
| 1.07 | `tests/test_news_radar_page.py::test_page_presents_a_simple_primary_news_workflow` |
| 1.07 | `tests/test_safety_support.py::test_safety_supplier_page_loads_without_live_api_calls` |
| 0.97 | `tests/test_news_radar_page.py::test_status_survives_a_new_session` |
| 0.85 | `tests/test_observation_provenance_migration.py::test_0002_backfills_legacy_observation_and_enforces_provenance` |
| 0.75 | `tests/test_search_source_status.py::test_source_status_page_loads` |
| 0.74 | `tests/test_quote_comparability_page.py::test_quote_comparability_is_absorbed_into_quote_review_page` |
| 0.71 | `tests/test_news_radar_page.py::test_page_explains_how_to_get_issues_when_old_index_has_none` |
| 0.68 | `tests/test_track_b_delivery_lines_migration.py::test_track_b_serving_table_migrates_and_downgrades` |
| 0.65 | `tests/test_hospital_benchmark.py::test_page_shows_no_numbers_when_no_accounts_are_loaded` |

importtime 1회 누적은 streamlit 2.618295초, purchase_price 0.008705초. 내부 누적 상위는 delta_generator 1.308843, cursor 1.090558, script_run_context 0.896752, runtime.runtime 0.893951, config 0.739336, config_util 0.601616, asyncio 0.402067, app_session 0.327469, cli_util 0.254928, urllib.request 0.213953초다. 부모·자식을 합산하지 않는다. 이 명령은 전체 앱/페이지 import를 재지 않는다.

원시 로그·스크립트·캡처·합성 XLSX는 OS 임시 경로에만 두고 커밋하지 않는다. 핵심 입력·재현·원시 표본은 이 문서에 보존한다.

## 3. 발견 사항 목록

### [A-01] 같은 이름의 새 견적서가 이전 견적으로 남는다
- 심각도: 높음
- 영역: A(UI/UX)
- 증상: 공급사가 같은 파일명으로 수정 견적을 보내면 새 모델·단가를 올려도 이전 품목·결과로 작업할 수 있다.
- 근거: `pages/1_대시보드.py:4878,4886`, `ui/quote_market_research.py:1151`, `ui/quote_review_steps.py:208`. 로컬 same-quote.xlsx를 SYNTH-REVIEW-001/123456원→SYNTH-REVIEW-002/654321원으로 교체해도 001/123456이 표시됐다. 같은 이름·다른 bytes에서 newly_extracted=False인 조건도 확인했다.
- 원인: 추출·자동 이동·결과 캐시가 파일 내용 대신 파일명으로 동일성을 판별한다.
- 제안: 업로드 SHA-256을 세션 파일 ID로 두고 변경 시 추출·품목 결과·자동 이동·승인을 함께 무효화한다. 원문 bytes 장기 저장은 하지 않는다. 종료 조건: 같은 이름 내용 교체가 새 추출을 만들고 기존 승인/결과를 재사용하지 않는다.
- 예상 효과와 비용: 잘못된 견적 재사용 차단. M(2~3일). 변경 시 품목 입력이 초기화됨을 안내해야 한다.
- 확인 여부: 확인함(코드·로컬 브라우저). 운영 업로드 미실행.

### [B-01] 미완료 실시간 보강을 성공 또는 정상 0건으로 반환한다
- 심각도: 높음
- 영역: B(DB)
- 증상: 최근 거래 일부만 읽었는데 화면에서는 그 날짜까지 확인한 자료로 제시할 수 있다.
- 근거: `services/track_b_live_gap_fill.py:193-251`은 len(items)<999면 종료하고 예산 소진 후 완전성 검사 없이 상태를 만든다. 합성 totalCount=10000/빈 page1/budget=1은 success_0. page1 999행/같은 budget/코드 2개는 첫 코드만 호출했는데 success·999후보·truncated_window=False였다.
- 원인: 페이지 계약과 미완료 페이지·코드 수를 결과 상태에 전달하지 않는다.
- 제안: collector의 totalCount/pageNo/빈 페이지 검증을 재사용하고 미완료는 partial로 전달한다. 실시간 확인 종료일도 완전 조회일 때만 표시한다. 종료 조건: 예산·코드 경계·페이지 수축·pageNo 불일치 반례에서 부분조회와 0건을 구분한다.
- 예상 효과와 비용: 실패·부분조회·정상 0건 구분 복구. M. 부분행 보존 여부와 docs/metrics/price.md의 변경차수·기간 계약을 함께 결정해야 한다.
- 확인 여부: 확인함(실제 함수·가짜 client, 외부 호출 없음).

### [C-01] 뉴스 포함 리포트의 보관 시계가 기사보다 늦게 시작한다
- 심각도: 높음
- 영역: C(운영)
- 증상: 기사 캐시를 지워도 과거 보고서·실행 요약에 오래된 제목·링크가 남는 경로가 있다.
- 근거: `services/hospital_report.py:165-190`은 최근 7일 기사를 포함한다. `scripts/generate_hospital_report.py:30,86-113`은 리포트 날짜로 21일 보관하며 `:169-175`는 Markdown을 Actions step summary에 쓴다. `.github/workflows/hospital-weekly-report.yml`은 --with-news·artifact 21일 보관. 7일 된 기사로 만든 보고서는 20일 뒤에도 보관 대상이지만 기사는 27일 됐다.
- 원인: 파생물의 만료가 원본 기사 만료와 분리되고 실행 요약의 제목 수명도 제어하지 않는다.
- 제안: 장기 경영 보고서에서 뉴스 원문 필드를 분리하고 기사별 절대 expires_at을 적용한다. Actions 요약은 원문 제목 대신 건수와 만료 관리되는 화면 링크만 남길 수 있다. 종료 조건: 기사 기준 21일 전후 모든 산출물의 경계 테스트.
- 예상 효과와 비용: docs/metrics/news.md의 21일 계약에 맞춘다. M. 실제 만료 객체·버킷 수명주기는 미검증. 법률 판단이 아닌 내부 데이터 계약 위반 경로 지적이다. 기존 데이터 삭제는 하지 않았다.
- 확인 여부: 확인함(소스 경로·날짜 반례). 운영 초과보관 객체의 실제 존재는 미검증.

### [D-01] 거래 0건 뒤 참고거래가 행당 SQL을 4번 추가한다
- 심각도: 높음
- 영역: D(속도)
- 증상: 찾는 모델에 거래가 없을 때 참고 자료의 조건 읽기 때문에 더 오래 기다린다.
- 근거: `services/track_b_db_quote_comparison.py:648-665,690-693`은 undefer 없이 객체를 읽고 `_row_conditions(:433)`가 지연 컬럼 4개를 접근한다. 새 합성 Session에서 참고 1/5/25행→SELECT 9/25/105회, 그중 추가 단건 조회 4/20/100회였다. 직접 거래 경로 :762-768에는 eager 옵션이 있다.
- 원인: 과거 지연 로딩 제거가 직접 거래 분기에만 적용됐다.
- 제안: 참고 조회에도 존재하는 조건 컬럼만 undefer하거나 필요한 칼럼을 한 번에 projection한다. v1/v2/v3 호환을 유지한다. 종료 조건: 25참고행의 추가 조건 조회 100회→0회, 결과·정렬·원문키 동일.
- 예상 효과와 비용: 합성 전체 0.0874초 중 조건 읽기 누적 0.061초가 제거 후보. 나머지 불변이면 약 0.026초라는 산술 추정이며 수정 후 실측 아님. 운영 NT960의 7.31/9.442초 전체를 이 효과로 주장하지 않는다. S~M. 옛 인덱스 호환 위험.
- 확인 여부: 확인함(SQL event 카운트·실제 comparator cProfile).

### [D-02] 핵심 카드가 같은 품목의 다른 모델 집계까지 기다린다
- 심각도: 높음
- 영역: D(속도)
- 증상: 같은 모델 거래만 보려는 사용자도 다른 모델 표를 만들 때까지 기다린다.
- 근거: `pages/1_대시보드.py:2224-2267`은 crosslinks·제품군을 동기 계산 후 state를 반환한다. 직접 HeartOn 첫 wall 16.006초 중 같은 품목 집계 4.559·제품군 1.240초. 당일 CI wall 14.368초 중 4.487·1.162초다. 반복 때 해당 구간은 약 1.3초로 줄어 중앙값만 보면 부담이 가려진다.
- 원인: 동일 모델 결과와 선택형 제품군 표의 계산 수명을 하나로 묶었다.
- 제안: 핵심 state를 먼저 만들고 다른 모델·제품군은 명시적 열기/별도 fragment로 계산한다. 사전 계산 키는 index hash·모델/단위·기간·별칭 버전을 포함한다. 종료 조건: 같은 데이터의 핵심 수치 동일·세션 첫 카드 시간 감소·보류/실패 상태 유지.
- 예상 효과와 비용: 직접 첫 표본의 5.799초를 카드 뒤로 옮기면 16.006→약 10.207초, CI는 14.368→약 8.719초라는 산술상 추정. 렌더·통신 불변 가정으로 보장치 아님. M. docs/metrics/price.md의 제품군 결론 표시 조건을 약화하면 안 된다.
- 확인 여부: 확인함(호출 순서·운영/CI 마커), 단축 시간은 (추정).

### [B-02] 인덱스 게시가 원본·gzip 전체를 동시에 메모리에 올린다
- 심각도: 높음
- 영역: B(DB)
- 증상: 데이터가 늘수록 새 인덱스를 게시하는 작업부터 메모리 부족 위험이 커진다.
- 근거: `storage/r2_serving_index.py:80-86`, `storage/r2_mfds_identity_index.py:84-90`은 read_bytes 뒤 gzip.compress를 한다. 합성 SQLite 16.03/32.05MiB의 실제 게시 함수에서 Python 할당 피크 61.40/109.44MiB. 다운로드 streaming_gzip과 비대칭이다.
- 원인: 게시 경로가 원본 bytes와 압축 bytes를 동시에 보유한다.
- 제안: 스트림 hash·gzip 임시파일→크기/쿼터 검증→파일 스트림 업로드로 변경한다. 동일 hash·mtime=0 유지. 종료 조건: 1×/2×/10× 합성 인덱스의 RSS·임시디스크·출력 바이트 동일성 검증.
- 예상 효과와 비용: 할당량을 파일 크기 비례에서 버퍼 중심으로 제한. 시간은 합성 32MiB의 1.111초를 수정 후 비교해야 하며 운영 단축 초는 미검증. M. 압축 수준·multipart·중단 정리 위험.
- 확인 여부: 확인함(소스·합성 크기 증가). 실제 운영 RSS 한도는 미검증.

### [C-02] 주간 운영 OCR 스모크가 숨긴 메뉴에서 멈춘다
- 심각도: 높음
- 영역: C(운영)
- 증상: OCR 감시가 업로드·OCR까지 도달하지 못한다.
- 근거: [실패 run 40250682168](https://github.com/dekt-oss/price-check-assistant/actions/runs/40250682168), 10-26 09:42 KST. artifact에서 3회 모두 견적추출 UAT 링크 visible 대기 60초 timeout, 총 234.75초. `scripts/production_scan_ocr_smoke.py:139-143`은 메뉴 진입, `Home.py:154-158`은 ADMIN_MODE일 때만 링크 노출. 이번에 운영 업로드를 실행한 것이 아니라 기존 결과를 읽었다.
- 원인: 메뉴 숨김 이후 스모크 진입 계약을 갱신하지 않았다.
- 제안: 등록된 /quote-extraction-uat 직접 진입 또는 현재 사용자 과업 진입으로 바꾸고 로컬 회귀부터 확인한다. ADMIN_MODE 공개 노출로 우회하지 않는다. 종료 조건: 실제 합성 OCR까지 도달하는 보고서와 진입 실패/OCR 실패 분리.
- 예상 효과와 비용: 주간 감시 복구, 메뉴 대기 약 180초 제거 가능. S. 운영 재실행은 이번에 하지 않았다.
- 확인 여부: 확인함(현재 코드·당일 CI artifact).

### [A-02] 견적 기준 설명은 낮은 견적의 확인 규칙을 빠뜨린다
- 심각도: 중간
- 영역: A(UI/UX)
- 증상: 설명상 범위 안인 입력에 왜 확인 표시가 붙는지 이해하기 어렵다.
- 근거: `ui/quote_review_layout.py:76-80`은 +20% 초과만 확인이고 나머지는 범위 안이라고 설명한다. quote_verdict(quote_unit_price=10, median_price=100, comparable_count=3)는 −90% 확인 필요를 반환했다. `services/price_metrics.py:408-420`과 docs/metrics/price.md 4장에는 하한도 있다.
- 원인: 하한 규칙을 계산·계약에 반영했지만 화면 설명은 갱신하지 않았다.
- 제안: 설명도 ±20%와 단위·구성 확인을 함께 말하도록 계약에서 생성한다. 종료 조건: 상·하 경계 입력과 설명 일치, 조건 미확인 꼬리말 유지.
- 예상 효과와 비용: 판정 해석 혼란 감소. S. 수치 계약 변경 불필요.
- 확인 여부: 확인함(실제 함수·설명 문자열).

### [B-03] 검증된 로컬 사본이 있어도 포인터 오류가 가격 전체를 끊는다
- 심각도: 중간
- 영역: B(DB)
- 증상: 디스크에 최근 사본이 있어도 순간 원격 오류로 가격 연결 불가가 된다.
- 근거: `services/track_b_r2_quote_index.py:64-82`는 잠금을 다른 스레드가 쥘 때만 last_good을 쓴다. :87-88은 매번 원격 pointer 조회, :239-248은 오류를 unavailable로 바꾼다. 임시 last_good 존재 상태에서 locked 함수에 OSError를 주입하면 예외가 전파됐다. MFDS와 달리 Track B pointer TTL도 없다.
- 원인: 갱신 중 사용과 갱신 실패 시 사용 정책이 다르고 매 검색이 원격에 의존한다.
- 제안: endpoint/bucket별 검증 snapshot을 보유하고 통신 실패에 기준일·갱신 실패를 명시해 사용한다. hash/schema 오류는 임의 우회하지 않는다. TTL은 신선도 상한과 결정한다. 종료 조건: 장애 주입 시 과거 값을 새 수집분처럼 표시하지 않는다.
- 예상 효과와 비용: 일시 장애 범위 축소. M. 실제 R2 지연·빈도는 미검증, TTL 동안 반영 지연 비용.
- 확인 여부: 확인함(로컬 예외 주입), 운영 장애 미유발.

### [B-04] 근거 FK의 삭제 정책과 NOT NULL이 여전히 충돌한다
- 심각도: 중간
- 영역: B(DB)
- 증상: 근거 정리 DB 작업이 일부 관측값 때문에 실패할 수 있다.
- 근거: `models.py:92-94`는 evidence_id NOT NULL/ON DELETE SET NULL, 0002 migration도 NOT NULL. FK를 켠 합성 SQLite에 제품·근거·관측을 만든 뒤 원본을 Core DELETE하면 NOT NULL constraint failed: price_observations.evidence_id. 09-10 로컬 리뷰 P0-6 지적이 남았다.
- 원인: 원본 삭제 후 보존과 삭제 금지 정책을 같은 FK에 지정했다.
- 제안: 불변 provenance 목적이면 RESTRICT/NO ACTION 및 보존 정책으로 migration한다. NULL 허용은 원본 없는 관측 허용이라 기존 계약과 충돌한다. 종료 조건: PostgreSQL migration·삭제 거부·rollback 검증.
- 예상 효과와 비용: 삭제 의미 명확화. S~M. Track B 주 serving은 R2/SQLite여서 이 문제가 현재 가격 검색 장애라고 주장하지 않는다.
- 확인 여부: 확인함(모델·합성 FK). 실제 PostgreSQL 미검증.

### [C-03] 수집·게시가 하나의 대기 슬롯을 놓고 경쟁한다
- 심각도: 중간
- 영역: C(운영)
- 증상: 늦은 실행이 뒤로 밀리는 대신 새 대기로 교체되어 수집·게시가 빠질 수 있다.
- 근거: daily/history/supplemental/serving-index workflow가 track-b-r2-pipeline, cancel-in-progress=false를 공유한다. 최근 35 run에서 10-26 07:00 KST serving-index cancelled/skipped가 관측됐다. PR #373도 보충 수집 누락 뒤 catch-up 수정이다. 해당 취소 원인은 개별 로그 전수 조사하지 않아 판단 보류.
- 원인: 상호 배제용 concurrency를 모든 요청이 남는 업무 큐처럼 사용한다.
- 제안: writer 잠금은 유지한다. 먼저 [GitHub concurrency 공식 문서](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)의 queue: max(최대 100대기)를 작은 대안으로 검토하고, R2 ledger의 미완료 기간·미게시 manifest는 다음 실행이 회수하게 한다. 기본 queue: single의 대기 교체와 별도 큐 도입을 구분한다. run 성공 대신 coverage 완료일·publish lag 감시. 종료 조건: history 장기 실행 중 daily/보충/게시 요청이 몰려도 coverage를 회수하는 시뮬레이션.
- 예상 효과와 비용: writer 경합 없이 재개 가능성 보강. M. 현재 live 누락량은 미검증. 스케줄러 대안은 4절.
- 확인 여부: 확인함(정적 그룹·취소 표본), 모든 취소의 원인은 (추정)하지 않고 보류.

### [C-04] 성능 요약이 모델별 병목을 하나의 warm 통계로 섞는다
- 심각도: 중간
- 영역: C(운영)
- 증상: 빠른 모델이 느린 모델을 가려 어떤 검색이 오래 걸리는지 바로 알기 어렵다.
- 근거: `scripts/measure_price_search_timings.py:134-155` summarize는 cold만으로 묶고 query로 나누지 않는다. 당일 artifact에는 8초대와 14초대가 공존한다. :79-116은 없는 단계 값도 0.0으로 만든다.
- 원인: 모델·결과 상태·계측 결측을 요약 키에 포함하지 않았다.
- 제안: query×cold×결과상태×배포/인덱스 버전으로 요약하고 결측은 null/계측 실패로 둔다. n·실패율 병기. 종료 조건: 느린 모델만 지연돼도 요약에서 분리되고 누락 마커를 0초로 처리하지 않는다.
- 예상 효과와 비용: 모델별 p50/p95·계측 구멍 추적. S~M. 옛 표본은 0초와 결측 재분류가 어려움.
- 확인 여부: 확인함(요약 코드·당일 표본).

### [E-01] 운영 Python 가정과 빌드 검증 환경이 다르다
- 심각도: 중간
- 영역: E(코드)
- 증상: 로컬/CI가 통과해도 운영에서만 의존성·OCR 문제가 생길 여지가 남는다.
- 근거: 수신 요청은 운영 Python 3.14라고 명시(서버 직접 버전 미검증). ci.yml은 3.11, streamlit-cloud-build.yml은 python:3.12-bullseye, browser smoke도 3.12다. requirements/pyproject는 범위 지정, uv.lock은 추적되지 않는다. 로컬 Streamlit은 1.63.0이었다.
- 원인: 운영 호환 검증이 다른 Python·배포 조합을 검사한다.
- 제안: 운영 Python/OS/핵심 패키지 버전을 비밀값 없이 기록하고 해당 조합 install/import/OCR 검증을 둔다. 3.11 개발 게이트 유지. 종료 조건: 실제 운영 조합에서 설치와 주요 과업 확인.
- 예상 효과와 비용: 환경 차이 탐지. M. 3.14에서 실제 결함이 있다고 단정하지 않으며 확인 전 광범위 업그레이드를 하지 않는다.
- 확인 여부: 확인함(CI 설정 차이), 실제 운영 버전은 미검증.

### [E-02] 현재 운영 설명의 저장소·매핑·시간 한도가 서로 다르다
- 심각도: 중간
- 영역: E(코드)
- 증상: 새 작업자가 DB·검색 범위·실행 예산을 잘못 가정해 같은 논의를 반복한다.
- 근거: README.md:45는 verified 5개, CSV는 21행 중 10개. README의 경영 회계자료 미적재와 달리 운영은 2024 브리핑 표시. R2_RAW_EVIDENCE_STORAGE_V1은 R2를 Postgres 대체로 쓰지 않는다고 하고 TRACK_B_DAILY_PIPELINE은 Track B에 Postgres 불필요라고 한다. 후자 :23의 history 320분과 실제 workflow timeout 175분/max-minutes 140분도 다르다.
- 원인: 과거 결정문과 현재 운영 설명에 대체 링크·유효 범위가 없다.
- 제안: 현재 정본·트리거·시간 한도를 단일 운영 표에 두고 역사 문서는 기준 SHA·대체 링크를 붙인다. 매핑 수/기본값은 코드와 대조한다. 종료 조건: 신규 작업자가 하나의 표로 실제 경로·한도를 재현한다.
- 예상 효과와 비용: 인수인계 오인 감소. S~M. 문서 전량 삭제는 불필요. 기존 문서는 이번에 수정하지 않았다.
- 확인 여부: 확인함(CSV 집계·소스·화면).

### [E-03] 매칭 benchmark 100%는 직접 일치 양성 한 모델에 기반한다
- 심각도: 중간
- 영역: E(코드)
- 증상: 회귀 표본 점수가 실제 다양한 모델·제조사 충돌의 정확도로 읽힐 수 있다.
- 근거: evaluate_match_benchmark --fail-on-mismatch 실행: 11행, exact/direct precision/recall 100%, reviewed_models=3/registry_models=20, 직접 양성=1행·1모델. 매핑 verified 10개와 benchmark 분모는 다르다.
- 원인: 소표본 회귀 점수만으로 정확도를 요약할 수 있는 구조다.
- 제안: 검토 모델/양성/제조사 충돌/별칭/취소·수출 표본 수를 함께 게이트에 병기하고 독립 홀드아웃을 확대한다. MFDS 보강 미수집과 오매칭도 분리. 종료 조건: 위험 종류별 양성·음성 표본과 오류율 보고. 자동 verified 승격 금지.
- 예상 효과와 비용: 점수 과대 해석 차단. M. 전수 정답이 없어 새 정확도 %는 제시하지 않는다.
- 확인 여부: 확인함(benchmark 실제 실행·분모).

### [B-05] 실시간 추가 가격은 당시 원본 응답으로 되짚기 어렵다
- 심각도: 중간
- 영역: B(DB)
- 증상: live 거래를 근거로 남겨도 당시 응답 그대로 사후 검토하기 어렵다.
- 근거: `services/track_b_live_gap_fill.py:211-215`는 live:<code>:<begin>:<end>:<page> 가상 raw key로 정규화한다. 후보에 이 key만 전달되며 fetch_live_gap 안에 응답을 불변 raw로 보관하는 경로는 없다. 수집행의 raw_object_key/raw_payload_sha256/api_params_json 경로와 다르다.
- 원인: live 응답은 세션 관측인데 보관 원본과 같은 raw key 필드를 쓴다.
- 제안: 앱 writer를 추가하지 말고 비보관 상태·조회시각·요청범위·fingerprint를 구분해 내보낸다. 영속 근거가 필요한 거래는 collector 수집·게시 후 보관 근거와 연결한다. 종료 조건: UI·Excel에서 보관 여부와 재현 가능성을 혼동하지 않는다.
- 예상 효과와 비용: 사후 근거 한계 명시. M. 공개 앱에 R2 write 권한 확대는 하지 않는다.
- 확인 여부: 확인함(코드 추적). 실제 특정 live 거래의 후속 수집 여부는 미검증.

### 3.1 영역별 구조·범위 검토

**A — 메뉴와 과업.** pages는 16개지만 기본 사이드바는 홈·가격·견적·의료기기 허가/안전·뉴스·경영 6개다. 구매에 직접 연결되는 것은 가격·견적·의료기기 3개, 홈은 진입, 뉴스·경영은 별도 업무다. UAT/legacy는 기본 메뉴에 보이지 않으므로 16개가 사용자 메뉴에 섞였다는 전제는 현재와 다르다. 숨김 URL은 접근통제가 아니므로 민감한 관리자 기능을 넣어서는 안 된다.

운영 PNB는 같은 제품 70건/45기관/중앙값 11880000원, SJ는 0건과 다른 모델 참고 시세를 분리했고 NT960의 비슷한 품목 25건은 직접 비교에서 뺐다. 확인한 카드에서 시스템의 구매 판단·대체 가능성·안전성 확정 문장은 찾지 못했다. 확인된 회수 없음은 공식 자료 범위 결과이며 제품 안전 보증으로 확대하지 않는다. OBSERVED_ONLY의 숫자 차이와 조건 비교 승인 완료는 구분해야 한다. ±20% 상태 변경 제안은 docs/metrics/price.md 4장과 충돌 검토가 필요하다.

가격·뉴스·경영은 각각 부분/빈 결과, 캐시·세션 상태, 자료 없음·비교군 보류의 다른 상태 객체를 쓴다. 경고를 일괄 줄이면 실패가 0건처럼 될 수 있다. 설명 단축보다 상태 계약을 우선하고 표·빈 상태·loading도 그 계약으로 통일해야 한다. 이번 표 정렬·링크·원문 팝업의 운영 재검증 범위는 6절과 같다.

Streamlit 안에서 가능한 것은 fragment/명시적 보조 계산, 폼 제출 경계, 내용 hash 캐시, URL 상태, 수치형 표다. 연결 단절 뒤의 영속 승인·다중 사용자 감사·백그라운드 영속 큐는 별도 저장/백엔드가 필요하다. wall−total을 전부 Streamlit 재실행 탓으로 돌릴 근거는 없다.

**B — 정본·스키마·확장성.** Track B 원본 정본은 R2 raw/v1의 canonical JSON/SHA-256, cursor/pending manifest/coverage/게시 pointer는 state/v1이다. derived/v1 SQLite는 재생성 가능한 serving 파생물, 앱 임시 SQLite는 검증된 사본이다. PostgreSQL은 레거시 제품/관측/관리 모델 및 개발 fallback에 남지만 Track B 운영 주 serving이라고 단정할 수 없다. data/의 매핑·별칭·병원 master·공시·키워드는 검토·버전 관리 자산이다. CSV 품목 연결과 MFDS 공식 identity 근거는 같은 종류가 아니다.

source+payload_hash, evidence/product/derivation/type, Track B 요청번호·변경차수·품목순번 유일성이 있다. 변경 전 원본 보존·수치 change order 최신 투영·동일 identity 충돌 검역 구조다. 검색키 B-tree와 부분문자열 FTS가 있으며 B-tree가 %문자열%를 가속한다고 보면 안 된다. `track_b_search_index.candidate_ids:286-316`은 전체 후보 ID를 목록화하므로 광범위 품목의 10배 규모에서는 정렬·메모리도 측정해야 한다.

마이그레이션 0001~0006은 선형 체인, serving은 v3와 v1/v2 읽기 호환이다. reader 먼저/writer 나중 규칙을 유지해야 한다. timezone=True 필드·UTC 정규화는 있지만 거래일 Date는 거래일 의미다. 실제 DB timezone·role·실행계획은 미검증. 수집행의 provenance, B-05의 비보관 live행, 0002의 synthetic migration backfill(원본 부재 명시)은 구분해야 한다.

10배 수집량에서 확인할 순서는 게시 메모리(B-02), 교체 시 임시디스크(old+new+temp), cold 다운로드/페이지 캐시, 광범위 FTS/제품군 6000행 상한이다. 실제 먼저 붕괴할 지점은 운영 RSS·디스크 한도 미측정으로 판단 보류. 단순 상한 조정은 모집단을 바꾼다.

**C — 37개 워크플로.** 파일 기준 전부 분류했다. 정기 UAT와 수동 UAT를 구분하며 오래됐다는 이유로 삭제 대상으로 확정하지 않는다.

| 파일(.yml) | 분류 | 실행 성격 |
| --- | --- | --- |
| ci | 검증 | PR/push/수동 또는 수동 전용 |
| g2b-cross-evidence-live | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-exoatlet-uat | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-ground-truth-capture | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-independent-contract-live | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-live-smoke | 스모크 | PR/push/수동 또는 수동 전용 |
| g2b-market-sources-live | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-reference-services-live | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| g2b-research-live-validation | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| hospital-weekly-report | 정기 보고·갱신 확인 | 정기 0 23 * * 0 |
| khidi-monthly-check | 정기 보고·갱신 확인 | 정기 0 0 1 * * |
| mfds-identity-index | 수집 | 정기 23 0 * * *, 23 6 * * *, 23 12 * * *, 23 18 * * * |
| mfds-item-status-index | 수집 | 정기 47 3 * * *, 47 9 * * *, 47 15 * * *, 47 21 * * * |
| mfds-live-validation | 검증 | PR/push/수동 또는 수동 전용 |
| mfds-model-recall-audit | 검증 | PR/push/수동 또는 수동 전용 |
| mfds-product-info-probe | 검증 | PR/push/수동 또는 수동 전용 |
| news-radar-collect | 수집 | 정기 */30 * * * *, 30 23 * * * |
| ocr-readiness | 검증 | PR/push/수동 또는 수동 전용 |
| p0-golden-apc-flow-uat | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| phase0-live-validation | 검증 | PR/push/수동 또는 수동 전용 |
| production-browser-smoke | 스모크 | PR/push/수동 또는 수동 전용 |
| production-scan-ocr-smoke | 스모크 | 정기 40 22 * * 0 |
| production-streamlit-smoke | 스모크 | PR/push/수동 또는 수동 전용 |
| r2-search-recall-uat | UAT·근거 캡처 | 정기 30 20 * * 0 |
| research-quality-5case-uat | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| streamlit-cloud-build | 검증 | PR/push/수동 또는 수동 전용 |
| track-b-daily-backfill | 수집 | 정기 10 18 * * * |
| track-b-db-real-validation | 검증 | PR/push/수동 또는 수동 전용 |
| track-b-history-backfill | 수집 | 정기 40 */3 * * * |
| track-b-postgres-full-validation | 검증 | PR/push/수동 또는 수동 전용 |
| track-b-r2-ground-truth-capture | UAT·근거 캡처 | PR/push/수동 또는 수동 전용 |
| track-b-r2-serving-index | 인덱스 빌드 | 연쇄/push/수동 |
| track-b-search-timings | 성능 관측 | 정기 17 0,4,8 * * * |
| track-b-supplemental | 수집 | 정기 40 19 * * 0 |
| workspace-v3-phase0-b-validation | 검증 | PR/push/수동 또는 수동 전용 |
| workspace-v3-phase1-evidence-validation | 검증 | PR/push/수동 또는 수동 전용 |
| workspace-v3-phase1-shell-validation | 검증 | PR/push/수동 또는 수동 전용 |

분류별 수: 검증 12, UAT·근거 캡처 11, 스모크 4, 정기 보고·갱신 확인 2, 수집 6, 인덱스 빌드 1, 성능 관측 1; 중복 없는 총 37개.

daily/history/supplemental/게시 writer 그룹, 뉴스 collect/digest 그룹이 따로 있다. offline CI와 secret 필요 live 검증은 목적이 다르다. one-off fixture 캡처는 유지 이유·종료 조건을 명시하고, Postgres 검증은 현재 serving 역할에 맞춰 통합 후보로 분류할 수 있다. 실제 사용 빈도 전수조사 전에는 삭제하지 않는다.

G2B는 supplemental MAX_WINDOW_DAYS=365·history 연 단위·live 최대 62일로 범위를 제한하고 collector 요청 예산/KST 일 80000 cap으로 앱 몫을 남긴다. 소스별 키 우선순위 코드가 있다. 다만 B-01의 live 페이지 계약은 collector와 다르다. 1년 조회 3.5분은 이번 외부 API 실측이 아니므로 새 측정값으로 사용하지 않았다.

배포에는 HTTP/health 생존과 마커·화면 업무 검사가 분리되어 있다. 소스 마커 v27과 정확한 운영 Git SHA는 다르다. rollback은 이전 reader와 현재 인덱스 호환도 확인해야 한다. .env/Streamlit Secrets/GitHub Secrets는 별도 저장소다. 값 자체는 읽지 않았으며 R2 hydrate의 환경 우선/read 별칭과 source-specific→shared/legacy 키 우선순위만 확인했다.

pipeline state·pointer·뉴스 마지막 확인·가격 기준일은 있지만 coverage/게시지연/실패/배포/성능/쿼터를 한곳에서 보는 운영판은 확인하지 못했다. 운영판을 만든다면 성공 run 개수보다 coverage와 publish lag를 써야 한다.

**E — 코드/테스트/공개 레포.** 실제 규모: pages 16개/9434줄, services 122개/29882줄, tests 288개 파일. 대시보드 4974줄에 라우팅·외부조회·identity 선택·집계·견적 상태·표 상호작용·내보내기·모듈 reload가 모인다. 파일 크기 자체를 결함으로 세지 않았다. 분리 경계는 `_execute_search(1994)`의 typed SearchState orchestrator, `_apply_search_period(2582)`·표 UI controller, fingerprint 기반 업로드 전환 controller다. 기존 계약을 고정한 뒤 분리하며 전면 rewrite는 근거가 약하다. 두 Snapshot adapter와 runtime marker/reload는 배포 대응 흔적이므로 운영 불필요를 증명하기 전 삭제하면 안 된다.

현재 git 추적 text 파일에서 GitHub/OpenAI/Anthropic/AWS 키 형태 및 private key header 패턴의 노출 위치는 0건이었다. 실제 비밀값·DB 주소는 읽거나 기록하지 않았다. .env/Streamlit secrets ignore를 확인했다. 이 검색은 모든 엔트로피 값·과거 Git 전체·외부 로그·실제 권한을 검사한 감사가 아니다. redaction 회귀 테스트는 전체 suite에 포함됐지만 새 운영 장애를 유발하지 않았다.

## 4. 개선 로드맵

### 이번 주

1. A-01/B-01: 같은 파일명 내용 교체와 totalCount/빈 페이지/예산 경계 재현을 회귀 조건으로 고정한 뒤 차단한다. 지표 게이트를 느슨하게 하지 않는다.
2. D-01/C-02/A-02: 참고 경로 추가 SQL, 스모크 진입, 기준 설명을 좁은 변경으로 다룬다. 같은 index/새 Session/같은 25후보로 검증한다.
3. C-01: 파생 저장물 만료를 결정하고 제목이 장기 산출물로 복사되는 경로를 닫는다. 기존 운영 데이터 삭제는 별도 사용자 결정이다.

### 이번 달

- D-02 핵심 카드/보조 집계 분리: 동일 index hash에서 세션 첫 검색·반복검색 각각 n≥10, 카드/표 완료 분리. 현재 n=3로 목표 달성 선언 금지.
- B-02 스트리밍 게시·RSS/디스크 계측, B-03 명시적 stale 정책, C-03 coverage 회수 ledger 검증.
- C-04 모델별/결측별 성능, E-01 운영 환경 재현, E-02 현재 구성 표, E-03 위험 매칭 홀드아웃 보강. 계약·코드·문서 담당자를 연결한다.

### 구조 결정에 필요한 정보와 선택지

| 결정 | 선택지 | 필요한 근거 / 비용 |
| --- | --- | --- |
| Streamlit | 유지+fragment / 조회 API+Streamlit / UI·backend 분리 | 동시 사용자·과업 p95·세션 단절/승인 보존 요구. 현행은 배포 표면이 작고 backend는 큐/관측이 쉬우나 인증/운영 부담 증가. 이번 n=3로 이전 결론을 내리지 않는다 |
| 저장소 | R2 raw+SQLite 지속 / 원본 R2+원격 SQL serving | cold bytes·RSS/디스크 피크·게시 시간·동시 조회·관리 시간. SQL 이전을 이유로 불변 원본/복구 검증을 없애지 않는다 |
| 스케줄 | Actions cron+회수 ledger / 외부 cron→dispatch / 영속 큐+짧은 worker | 누락 SLA·publish lag·writer 횟수. 외부 cron만 바꾸면 pending 교체는 남아 ledger가 필요 |

공개 저장소 표준 GitHub-hosted runner는 [공식 billing](https://docs.github.com/en/actions/concepts/billing-and-usage)상 무료(2026-10-27 확인). 뉴스 self-chain의 약 하루 runner 점유를 곧바로 현금 절감으로 바꾸지 않는다. 비용은 설정·복구·쿼터·대기 슬롯 관리 시간도 포함한다.

기존 Cloudflare Worker는 10분 dispatch, Actions는 59분 루프/self-chain/30분 cron을 함께 둔다. Worker 배포 활성 여부는 미검증. 하루 144회 dispatch 산술 부하는 [Free 일 100000 요청 한도](https://developers.cloudflare.com/workers/platform/limits/)보다 작지만 실제 CPU·다른 사용량·청구는 미검증. 영속 큐/장기 서비스 월 비용은 처리량·계정 플랜 없이 확정하지 않는다. 구조 변경의 최종 결정은 사용자에게 남긴다.

## 5. 하지 말아야 할 것

- 반복 중앙값이 낮다는 이유로 첫 검색·cold가 끝났다고 선언하거나 wall−total을 모두 프레임워크 비용으로 돌리지 않는다.
- 출처·단위·조건 게이트/모집단을 줄여 속도를 맞추지 않는다. 5000/6000행 상한 변경 전 모집단 영향을 측정한다.
- 정상 프로파일 없이 전체 UI·DB를 교체하거나 4974줄을 한 PR에서 전면 분해하지 않는다.
- 스모크를 위해 UAT 메뉴를 공개하거나 앱에 R2 writer 권한을 추가하지 않는다.
- 오래된 리뷰·워크트리·브랜치를 임의 삭제하지 않는다. 사용/병합/복구 필요성은 별도 인벤토리 대상이다.

## 6. 과거 리뷰 지적 사항 추적표

고쳐짐은 이번 코드·재현·화면으로 확인한 범위이며 전체 데이터 보증이 아니다.

| 과거 지적 | 현재 | 이번 근거 / 남은 검증 |
| --- | --- | --- |
| 09-10 P0-1 분류코드×기간 수집 | 고쳐짐(코드) | 목표 snapshot/detail code daily·history·supplemental. 전체 coverage 미검증 |
| P0-2 stable identity·변경차수 | 고쳐짐(코드/회귀) | 수치 change order/최신 투영/conflict 격리, 전체 suite 해당 테스트 |
| P0-5 Postgres serving 전제 | 일부/선택 변경 | 현재 주 serving R2 SQLite; 원계획 그대로 구현됐다고 할 수 없음 |
| P0-6 evidence FK 모순 | 안 됨 | B-04 실제 합성 FK 재현 |
| 09-14 상태가 artifact에만 있음 | 고쳐짐(코드) | R2 operational state/manifest/pointer. 실 복구 재실행 미검증 |
| 09-14 목록 위치 cursor | 일부 | 5208-code snapshot/hash 고정. 최신 R2 복구 미실행 |
| 09-06 2~5년 API 기간 거부 | 일부 | history 연 창/supplemental 365일/다년 UI 수집본. 모든 API 전수 live 미실행 |
| 10-12 산술평균·희소 추세 | 고쳐짐(계약/테스트) | 중앙값/n·기간 밀도 규칙. 모든 실제 그래프 전수 미검증 |
| UX v1.1 H-01 뉴스 오결합 | 일부 | 불용어·회귀·후속 평가 코드 있음, suite 해당 테스트 실행. 현재 5카드 전체 관련 기사 사건 동일성 재판정 미실행 |
| H-02 재료비 부분 합산 | 고쳐짐(함수) | supply_cost=None 입력 material_ratio=None 재실행, 계약 일치 |
| M-03 낮은 견적 판정 | 일부 | −90% 확인 필요 재현. 설명문은 여전히 상한만(A-02) |
| M-02 분포·피크 메모리 | 일부 | 운영 n=3/CI 대조 추가. 정상 cold/RSS 피크 미검증 |
| M-04 스모크 내용 검증 | 일부 | Q4 정렬·링크·재선택 코드 있지만 Track H는 제목/첫 블록. C-02 진입 퇴행 |
| L-01 HANDOFF 최종 상태 | 일부 | H1/H2 상단 링크 있음. I0/P2b의 과거 runtime/다음 작업은 역사 기록으로 구분 필요 |
| Q1 숫자 정렬/Q2 새 탭/Q3 재선택 | 일부 | 현재 코드·전체 suite 계약 있음. 이번 운영 정렬/팝업 재선택/다운로드 전부 재실행하지 않음 |
| Q0 배포 자동 확인 | 일부 | 최대 25분 마커 대기 코드. 운영 SHA/연속 머지 3회 인수 미검증 |
| P2b 직접 N+1 제거 | 일부 | 직접 eager 있음. 참고 경로 100추가 SELECT가 남음(D-01) |

로컬 전용 REVIEW_2026-09-{05,06,07,10,14}, REVIEW_2026-10-12_ux_work_order_v1 및 UX_WORK_ORDER_2026-10-12_v1.1은 main의 미추적 원본을 읽기만 했고 복사·커밋하지 않았다. 옛 리뷰 당시 운영 결과를 이번 측정으로 옮기지 않았다. docs/design/current-screens의 가격·견적 캡처도 열어 현재 화면과 구분했다.

## 7. 확인하지 못한 것

| 범위 | 상태·이유 | 재개 / 결론 영향 |
| --- | --- | --- |
| 정상 full-index 로컬 top10·RSS/디스크 | 미검증, 전용 환경에 키·인덱스 없음 | 허용된 읽기 사본과 같은 SHA로 4모델 프로파일. D-01 존재는 확정이나 전체 지연 비중/B-02 운영 한도는 바뀔 수 있음 |
| 정상 서버 cold 3회 | 미검증, Reboot/캐시 삭제 없음 | 자연 재시작에 server/index 상태와 wall 수집. 첫 브라우저 방문과 구분 |
| 실제 결재 근거 확보 시간 | 미검증, 공개 견적 없고 운영 업로드 금지 | 허용된 로컬 synthetic 거래 인덱스로 조건/승인/내보내기 과업. 업로드 0.914초는 업무 완료 속도 아님 |
| R2 원본/포인터/저장량/복구 | 미검증, 인증 저장소 작업 미실행 | scope된 읽기 listing·hash·manifest 감사. 현재 실제 손실/용량 단정 불가 |
| Postgres migration/role/timezone/plan | 미검증 | 격리 DB Alembic·FK·read role 검증. 합성 SQLite로 운영 빈도 추정 금지 |
| MFDS/매칭 전수 품질 | 미검증 | 홀드아웃/coverage 분모 필요. 11행 100%를 전체 정확도로 쓰지 않음 |
| 뉴스 5카드 전체 기사·만료 객체 | 미검증 | 제목을 문서에 복사하지 않고 사건 동일성/원본 timestamp/파생 expiry 확인 |
| 운영 Python/Git SHA/secret 권한 | 미검증 | 비밀값 없는 버전·credential-source·readiness 메타데이터 |
| 실기기/보조기술/전체 키보드 | 미검증 | 데스크톱 캡처·코드 검사는 접근성/장치 검증과 다름 |
| 유료 AI/알림/구독·상태 쓰기 | 미실행 | 별도 허용 환경에서만. 이번 메일·메신저·구독자 변경 없음 |
| 과거 Git 이력 전체·외부 로그 | 미검증 | 현재 추적 파일 패턴 0건 범위를 넘는 별도 감사 |

### 7.1 전달 전 Fable Review와 수용 기준

- 모든 발견은 코드 위치·재현·이번 운영·기존 CI 중 하나 이상에 연결했다. 문서의 완료 선언만으로 닫지 않았다.
- 잘못된 선택자의 90초/15초와 외곽 iframe 생성 시간을 버렸다. 정상 0건과 키 없는 연결 불가를 섞지 않았다.
- 예상 단축은 제거 후보 단계 산술 추정이다. 수정 후 측정·p95 보증이 아니다.
- 전체 suite 7실패를 통과로 쓰지 않았다. 코드/설정 변경 0, 기사 제목/요약 인용 0, 비밀값 인용 0. 커밋 허용 파일 2개.
- 수용 기준은 **부분**: A~E·운영 경로·테스트·재현 문서는 있지만 정상 full-index 프로파일/cold가 없으므로 전체 완료 보류. 원문의 미완료 전달 규칙에 따라 상단에 재개 지점을 명시했다.
