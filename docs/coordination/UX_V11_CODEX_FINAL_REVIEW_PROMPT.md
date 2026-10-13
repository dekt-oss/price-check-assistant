# Codex 최종 리뷰 프롬프트 — UX v1.1 완성본

아래를 그대로 Codex에게 붙여 넣는다.

---

당신은 병원 구매팀 도구를 15년 다룬 시니어 기획자이자 리뷰어입니다. 「병원 구매정보 도우미 UX 개선 v1.1」이 완성본으로 main에 머지됐습니다. 코드를 고치지 말고 **리뷰만** 하세요. 결과는 `docs/coordination/history/UX_V11_FINAL_REVIEW_codex.md`에 적어 PR로 올리세요(문서 1개만).

## 읽을 것(이 순서로)
1. `docs/coordination/UX_V11_FINAL_REVIEW.md` — 완성본 요약과 인수 조건 대조. 여기 적힌 "됨"을 믿지 말고 직접 확인하세요.
2. `docs/coordination/UX_V11_WORK_ORDER_v1.2.md` — 원래 요구(5·6·7장 인수 조건, 10장 우선순위).
3. `docs/handoffs/HANDOFF_*.md` 전부, `docs/metrics/*.md` 3종, `docs/NEWS_ISSUE_CLUSTER_EVAL_2026-10-13.md`, `docs/HOSPITAL_MANAGEMENT_BRIEFING_EXAMPLES_2026-10-13.md`, `docs/performance/UX_V11_PRICE_BASELINE.md`, `docs/uat/UX_V11_INTEGRATION_UAT.md`.
4. 코드 차이: `git diff ecb888b..origin/main --stat` 로 범위를 잡고, 아래 "꼭 볼 파일"은 전체를 읽으세요.

꼭 볼 파일: `src/purchase_price/services/price_metrics.py`, `src/purchase_price/ui/result_layout.py`, `src/purchase_price/ui/price_trend.py`, `src/purchase_price/services/news_radar.py`(군집 부분), `src/purchase_price/services/news_radar_index.py`(v2·호환), `src/purchase_price/services/hospital_metrics.py`(브리핑), `pages/0_홈.py`, `pages/1_대시보드.py`의 `_apply_search_period`·`_UI_RUNTIME_MARKERS`, `scripts/production_unified_search_smoke.py`, `tests/test_ux_v11_integration.py`.

## 직접 돌릴 것
```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
ruff check .
pytest -q tests/test_price_metrics.py tests/test_result_comparison_card.py tests/test_price_trend.py tests/test_price_period_url.py tests/test_news_radar.py tests/test_news_radar_index.py tests/test_news_radar_page.py tests/test_hospital_metrics.py tests/test_hospital_benchmark.py tests/test_hospital_phase4.py tests/test_ux_v11_integration.py tests/test_streamlit_startup_smoke.py
pytest -q
```
Windows에서 OCR 실환경 4건과 견적 업로드·cp949 관련 기존 실패는 알려진 것입니다. 그 밖의 실패는 모두 적으세요.

운영 화면(https://bp-price-research.streamlit.app)은 읽기만 하세요: `/?q=PNB-704&period=5y`(최근 5년으로 열리는지), `/?q=SJ-DFM100`(거래 0건 상태), `/news-radar`(최근 3일 주요 이슈가 서로 다른 사건을 섞지 않는지 5개 모두 확인), `/hospital-benchmark`(브리핑 첫 줄·비교 보류), `/home`(세 카드).

## 리뷰 형식(8개 절, 각 절은 표나 번호 목록)
1. 총평 — 완성본이라 부를 수 있는지 한 문단, 근거 포함.
2. Critical/High — 사용자가 잘못 판단하게 만들거나 운영이 깨지는 것. 재현 방법과 증거(파일:줄, 화면, 명령 출력) 필수.
3. Medium/Low.
4. 인수 조건 대조 — 작업지시서 5·6·7장의 인수 조건마다 `됨 / 부분 / 안 됨 / 확인 불가`와 근거. `UX_V11_FINAL_REVIEW.md` 2장과 다른 판정이 있으면 그 줄을 명시.
5. 지표·문구 검증 — 가격 상태 4종, 근거 수준, 브리핑 첫 줄·보류 문구, 뉴스 이슈 제목이 금지어·단정 표현을 쓰지 않는지. 금지어: 적정, 권장, 싸다·비싸다, 절감액, 대체 가능, 안전한 제품, 원인 확정, 개선 필요·우수·부진, 인기·대표·추천.
6. 문서 일관성 — 계약 문서·HANDOFF·UAT·FINAL_REVIEW가 서로 다른 숫자나 상태를 말하는 곳.
7. 다음 단계 권고 — 우선순위 3개 이내, 각각 누가·무엇을·어떻게.
8. 판단 보류 목록 — 자료가 부족해 판단하지 못한 항목과 필요한 자료.

## 제약
- 코드를 수정하거나 구현하지 마세요. 운영 설정·Reboot·워크플로 실행도 하지 마세요.
- 근거 없는 칭찬은 쓰지 마세요. 재현하거나 설명할 수 없는 문제는 만들지 마세요.
- 자료가 부족하면 "판단 보류"로 두고 8절에 적으세요.
- 구매 적정성·제품 대체 가능성·안전성·경영 원인을 시스템이 단정하는 곳이 있으면 Critical로 올리세요.
- 문서끼리 충돌하면 충돌 지점을 적고 하나의 권고안으로 정리하세요.
- 원문 기사 제목을 리뷰 문서에 복사하지 마세요(21일 보관 경계).
- 작업 한도에 닿으면 완료라고 쓰지 말고 현재 상태와 재개 지점을 남기세요.
