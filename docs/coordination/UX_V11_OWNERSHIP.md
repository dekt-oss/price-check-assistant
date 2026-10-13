# UX v1.1 작업 — 파일 소유권 허용목록

작업지시서: `docs/coordination/UX_V11_WORK_ORDER_v1.2.md`. 이 표에 없는 경로를 고쳐야 하면 수정하지 말고 `HANDOFF`의 "공통 파일 변경 요청"에 적는다.
새 파일은 자기 트랙 영역 안에서만 만든다. 새 테스트 파일 이름: Track P는 `tests/test_price_*.py` 또는 기존 가격 테스트 파일, Track H는 `tests/test_news_*.py` / `tests/test_hospital_*.py`. 새 fixture: `tests/fixtures/price/`, `tests/fixtures/news/`, `tests/fixtures/hospital/`.

## Track P (Claude) — 수정 가능

| 영역 | 경로 |
| --- | --- |
| 페이지 | `pages/1_대시보드.py`, `pages/2_견적_검토.py`, `pages/3_빠른_검색.py`, `pages/3_Phase0_검증.py`, `pages/4_의료기기_조회.py`, `pages/4_의료기기_시장조사.py`, `pages/5_의료기기_안전_공급사.py`, `pages/6_의료기기_UDI.py`, `pages/8_공개가격_수집상태.py`, `pages/9_관리.py`, `pages/13_견적추출_UAT.py`, `pages/14_운영환경_진단.py`, `pages/15_전체구매검토_UAT.py` |
| UI 모듈 | `src/purchase_price/ui/*` **중** `theme.py`, `widgets.py`, `runtime_secrets.py`, `benchmark_charts.py`를 **제외한 전부** (`result_summary.py`, `result_layout.py`, `category_market.py`, `quote_*.py`, `purchase_workspace*.py`, `track_b_transactions.py`, `device_page.py`, `product_identity.py`, `market_research.py`, `memory_diagnostic.py`, `production_runtime_compat.py` 등) |
| 서비스 | `src/purchase_price/services/*` 중 `g2b_*`, `track_b_*`, `mfds_*`, `category_market.py`, `market_*.py`, `matching.py`, `product_matching.py`, `price_*.py`, `pricing.py`, `quote_*.py`, `purchase_*.py`, `search.py`, `search_routing.py`, `unified_search_intent.py`, `index_prefetch.py`, `evidence_freshness.py`, `company_identity.py`, `configuration_fingerprint.py`, `device_research_handoff.py`, `medical_lookup_handoff.py`, `image_ocr.py`, `pdf_*.py`, `tesseract_*.py`, `phase0_validation.py`, `public_provenance.py`, `real_quote_uat_entry.py`, `research_*.py`, `safety_support.py`, `structured_query_identity.py`, `match_*.py` 및 새 `price_metrics.py` |
| 수집·클라이언트·저장소 | `src/purchase_price/collectors/*`, `src/purchase_price/clients/data_go_kr.py`, `src/purchase_price/storage/*` (`streaming_gzip.py` 제외) |
| 스크립트 | `src/purchase_price/scripts/*` 중 Track H 목록과 공통 목록에 없는 전부 |
| 워크플로 | `.github/workflows/track-b-*.yml`, `mfds-*.yml`, `g2b-*.yml`, `r2-*.yml`, `p0-*.yml`, `phase0-*.yml`, `research-*.yml`, `ocr-readiness.yml`, `workspace-v3-*.yml` |
| 데이터 | `data/g2b_*`, `data/model_aliases.csv`, `data/manufacturer_aliases.csv`, `data/mfds_importer_relations.csv`, `data/mapping_requests.csv`, `data/phase0_*`, `data/public_*`, `data/research_quality_uat_cases.csv`, `data/evidence/`, `data/uat/` |
| 테스트 | `tests/*` 중 Track H 목록과 공통 목록에 없는 전부, `tests/fixtures/g2b_shopping/`, `tests/fixtures/price/`(신규) |
| 문서 | `docs/metrics/price.md`, `docs/performance/*`, `docs/handoffs/HANDOFF_P*.md`, 기존 가격·Track B·MFDS·견적 문서 |

## Track H (Codex) — 수정 가능

| 영역 | 경로 |
| --- | --- |
| 페이지 | `pages/20_병원_News_Radar.py`, `pages/21_병원_경영_Benchmark.py` |
| UI 모듈 | `src/purchase_price/ui/benchmark_charts.py`, 새 `src/purchase_price/ui/news_*.py` / `hospital_*.py` |
| 서비스 | `src/purchase_price/services/news_radar.py`, `news_radar_index.py`, `news_radar_budget.py`, `news_alerts.py`, `news_subscriptions.py`, `hospital_master.py`, `hospital_metrics.py`, `hospital_benchmark.py`, `hospital_report.py`, `hospital_ai_explanation.py`, `khidi_financials.py`, `alio_disclosure.py`, `hira_hospital_info.py` |
| 클라이언트 | `src/purchase_price/clients/naver_news.py` |
| 스크립트 | `src/purchase_price/scripts/collect_news_radar.py`, `evaluate_news_issue_clusters.py`, `next_news_radar_run.py`, `kakao_refresh_token.py`, `generate_hospital_report.py`, `import_hospital_financials.py`, `import_alio_disclosure.py`, `sync_hira_hospital_info.py`, `discover_size_peers.py`, `check_khidi_new_year.py` |
| 워크플로·외부 | `.github/workflows/news-radar-collect.yml`, `hospital-weekly-report.yml`, `khidi-monthly-check.yml`, `cloudflare/news-radar-cron/*` |
| 데이터 | `data/news_keywords.json`, `data/news_sources.json`, `data/hospital_master.json`, `data/hospital_financial.csv`, `data/alio_disclosure.csv`, `data/alio_raw/`, `data/khidi_raw/` |
| 테스트 | `tests/test_collect_news_radar.py`, `test_naver_news_client.py`, `test_news_radar.py`, `test_news_radar_index.py`, `test_news_radar_page.py`, `test_news_radar_workflow_contract.py`, `test_news_relevance_and_alerts.py`, `test_news_subscriptions.py`, `test_next_news_radar_run.py`, `test_alio_disclosure.py`, `test_hira_hospital_info.py`, `test_hospital_benchmark.py`, `test_hospital_intelligence_phase1_contract.py`(루트 주소·AI 미사용 단언은 유지), `test_hospital_master.py`, `test_hospital_metrics.py`, `test_hospital_phase4.py`, `test_khidi_financials.py`, `tests/fixtures/alio/`, `tests/fixtures/khidi/`, `tests/fixtures/news/`(신규), `tests/fixtures/hospital/`(신규) |
| 문서 | `docs/metrics/news.md`, `docs/metrics/hospital_management.md`, `docs/handoffs/HANDOFF_H*.md`, `docs/HOSPITAL_*.md`, `docs/NEWS_*.md`(평가·알림 문서 포함) |

주의: `tests/test_match_benchmark.py`, `tests/test_evaluate_match_benchmark_cli.py`는 이름에 benchmark가 있어도 **가격 매칭** 테스트다(Track P).

## 공통 — Integration 담당만 수정

| 영역 | 경로 |
| --- | --- |
| 진입·홈 | `Home.py`, `pages/0_홈.py` |
| 공통 UI | `src/purchase_price/ui/theme.py`, `widgets.py`, `runtime_secrets.py`, `src/purchase_price/ui/__init__.py` |
| 공통 코드 | `src/purchase_price/__init__.py`, `config.py`, `db.py`, `domain.py`, `evidence.py`, `evidence_domain.py`, `models.py`, `schemas.py`, `src/purchase_price/storage/streaming_gzip.py`, `services/live_smoke.py`, `services/runtime_readiness.py`, `alembic/*` |
| 빌드·배포 | `pyproject.toml`, `requirements.txt`(특히 `# Revision` 줄), `packages.txt`, `.gitignore`, `.github/workflows/ci.yml`, `production-*.yml`, `streamlit-cloud-build.yml` |
| 전역 테스트 | `tests/conftest.py`, `tests/test_streamlit_startup_smoke.py`, `tests/test_navigation_contract.py`, `tests/test_home_runtime_secrets_contract.py`, `tests/test_production_*.py`, `tests/test_streamlit_cloud_wake_smoke.py`, `tests/test_live_smoke.py` |
| 전역 문서 | `README.md`, `CLAUDE.md`, `docs/coordination/*`, `docs/README*` |

## 교차 참조 (읽기는 허용, 수정은 소유자만)

- Track H 코드가 읽는 공통 모듈: `config.get_settings`, `ui.runtime_secrets`, `ui.theme`, `storage.streaming_gzip`.
- Track P 코드는 Track H 모듈을 import하지 않는다. Track H 코드는 Track P 모듈을 import하지 않는다(현재 0건, 유지).
- `pages/0_홈.py`는 두 트랙 서비스를 모두 읽는다. 트랙이 서비스 함수 시그니처를 바꾸면 HANDOFF에 적고 I0에서 홈을 맞춘다. 시그니처를 바꾸기보다 새 함수를 추가하는 쪽을 택한다.
