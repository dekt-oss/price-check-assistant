# HANDOFF — 관리부 시장가격조사기 / Streamlit UI 재편 (견적 검토 단일 화면)

저장소: `dekt-oss/price-check-assistant`
Production: `https://bp-price-research.streamlit.app/`

이 세션은 이전 대화를 모른다고 가정한다.
**GitHub 최신 `main`을 Source of Truth로 복구한 뒤 시작한다.** 작성 시점 `main`은 `9c95e07`(PR #88까지 반영)이지만 고정 사실로 가정하지 말고 `git fetch origin` 후 재확인한다.

필독 자료 세 가지:

- `docs/RESTRUCTURE_QUOTE_REVIEW.md` — **구조** (파일 배치, 상태 객체, 함수 시그니처, 단계별 재사용 함수)
- `docs/wireframes/README.md` — **시각 명세** (3열 레이아웃, 색 의미, 근거/후보 구분 규칙, 판정 문구 규칙)
- `docs/wireframes/*.html` — 화면별 와이어프레임. 독립 실행 HTML이니 **브라우저로 직접 열어 보고** 만든다. S1~S6은 같은 견적이 흐르는 하나의 시나리오다.

구조 문서와 시각 명세가 다르면 구조 문서의 계약이 우선이고, 화면 모양은 wireframes가 기준이다.

---

## 0. 프로젝트 목적과 절대 규칙

병원 관리부 구매담당자가 견적서를 올리면 공개 가격근거를 모아 **동일 제품·동일 조건인지 확인한 뒤에만** 견적의 시장 위치를 판정하는 보조 시스템이다.

이 작업은 **UI 층 재편**이다. 다음은 절대 건드리지 않는다:

- `src/purchase_price/services/` 의 판정 계약: MatchGrade A/B/C/D/X, EvidenceType, ComparisonScope, `evaluate_quote_comparability_candidate`, `create_quote_comparable_approval`, `assess_prices`
- `collectors/` 의 검색 계약 (verified mapping 없으면 직접검색 안 함, discovery 후보는 `CollectedPrice`가 아님)
- 안전 게이트를 "UI에서 편하게" 만들려고 완화하는 모든 변경

화면은 기존 서비스 함수를 **호출만** 한다. 페이지 파일에 새 판정 로직을 쓰지 않는다.

가장 심각한 실패는 **틀린 가격을 그럴듯한 시장가격으로 보여주는 것**이다. 검색 결과를 못 보여주는 쪽이 낫다.

---

## 1. 지금 무엇이 문제인가

현재 `pages/`에 15개 메뉴가 기능 단위로 나열돼 있다. 견적 하나를 검토하는 흐름이 4개 페이지(견적조건 확인 → 외부조건 대조 → 비교가능성 게이트 → 최신성)에 흩어져 `st.session_state`로 이어붙여져 있고, 개발·운영 도구가 담당자 메뉴에 섞여 있다.

목표 정보구조 (역할 기준 5영역):

| # | 영역 | 흡수하는 현재 페이지 | 대상 |
|---|---|---|---|
| 1 | 대시보드 | Home | 담당자 |
| 2 | **견적 검토 — 한 화면 6단계** | 견적서 분석 + 견적조건 확인 + 견적 외부조건 대조 + 견적 비교가능성 게이트 + 가격근거 최신성 | 담당자 |
| 3 | 빠른 검색 | 통합검색 (+ 나라장터 계약근거는 근거표의 출처 하나로) | 담당자 |
| 4 | 의료기기 조회 | 의료기기 시장조사 + 안전 공급사 + UDI → `st.tabs` | 담당자 |
| 5 | 관리 | 운영환경 진단 + 견적추출 UAT + Phase0 검증 + 공개가격 수집상태 (+ 근거 레지스트리 신규) → `st.tabs`, **관리자만 표시** | 관리자 |

---

## 2. 견적 검토 6단계 — 화면 계약

한 견적이 S1→S6로 흐른다. 레이아웃은 3열 고정: **왼쪽 품목 목록 / 가운데 현재 단계 / 오른쪽 상태·판정 카드**. 상단에 6단계 스텝퍼.

| 단계 | 가운데 내용 | 오른쪽 카드 | 다음 단계 진입 조건 |
|---|---|---|---|
| S1 업로드·추출 | 업로드, 추출 경로·헤더 인식, **품목에서 제외한 요약행 목록**(공급가액·세액·합계 등), 경고(VAT 상충·단가 없음), 스캔 PDF 불가 안내 | 할 일 체크 | 품목 1건 이상 (0건이면 S2에서 직접 입력) |
| S2 품목 확인 | 품목 필드 편집(수정값 강조), 상업조건 6개(VAT·배송·설치·옵션·보증·유지보수), **원문 스니펫**, "원문 대조 완료" 체크 | 확인 상태 | 모든 품목 대조 완료 |
| S3 제품 식별 | 제조사 alias, 나라장터 mapping 검증 상태(없으면 "조사 요청"), 식약처 identity(의료기기일 때만) | 식별 상태 | mapping 검증됨 OR 조사요청 등록됨; 의료기기면 MFDS confirmed |
| S4 근거 수집 | 출처별 상태 표(**불완전 배지**, 요청수 n/120), 직접 비교 근거 표(A/B만), 미검증 후보 표(점선·회색·접힘·"표기 금액 (미검증)") | **출처·VAT상태별로 분리한 관측가** | 검색 1회 실행됨 (0건이어도 통과) |
| S5 조건 대조 | 근거 선택 → 9행 대조표(수량·단위, 통화, VAT, 배송, 설치, 옵션, 보증, 유지보수, 기준일) 일치/충돌/미확인, 근거 조건 보완(근거 URL 필수), 견적 조건 수정 | 비교가능 후보 수, "왜 후보가 아닌가" | `eligible_candidate` 1건 이상 |
| S6 승인·판정 | 후보별 승인 체크 + **승인 메모 필수** + 승인 기록(승인자·시각·pair_key 앞 6자), 판정 카드 | 6단계 검토 기록 | — |

판정 카드 문구 규칙: 승인 근거가 1건·출처 1개면 "적정"이라는 단어를 쓰지 않는다. "승인 근거 대비 위치(상단 초과/범위 내/하단 미만, ±x%)"로만 쓴다. 조건 미확인 근거(대표적으로 나라장터 — VAT 필드 없음)는 판정에서 제외되고 참고로만 남는다는 문장을 항상 표시한다.

색은 상태에만: 초록=완료/검증, 노랑=사람이 지금 할 일, 빨강=실패/차단, 회색=근거 없어 멈춘 보류·참고용 후보.

---

## 3. 구현 구조 (RESTRUCTURE_QUOTE_REVIEW.md 요약)

### 새 파일

```
pages/1_대시보드.py
pages/2_견적_검토.py            ← 6단계 단일 화면
pages/3_빠른_검색.py            ← 통합검색 이름 변경, 결과 레이아웃은 S4와 동일
pages/4_의료기기_조회.py        ← 3페이지를 st.tabs로
pages/9_관리.py                 ← 운영도구 4개 + 근거 레지스트리를 st.tabs로
src/purchase_price/ui/__init__.py
src/purchase_price/ui/quote_review_state.py    ← QuoteReviewState + can_enter(step, state) -> (bool, reasons)
src/purchase_price/ui/quote_review_steps.py    ← render_step_1..6 (Streamlit 호출만)
src/purchase_price/ui/quote_review_export.py   ← 검토 기록 JSON
src/purchase_price/ui/widgets.py               ← 재사용 위젯 5개
```

### 상태 객체와 게이트

`QuoteReviewState`(dataclass) 하나를 `st.session_state["quote_review"]`에 두고 `step: int`를 바꾼다. 페이지 이동 없음.

`can_enter(step, state) -> tuple[bool, list[str]]`는 **순수 함수**. `reasons`는 사람이 읽는 문장(예: `"품목 1 원문 대조 미완료"`)이며 오른쪽 카드에 번호 목록으로 그대로 출력한다. 전부 테스트한다.

### 재사용 위젯 (`ui/widgets.py`)

```python
def source_status_table(statuses: list[SourceRunStatus]) -> None
def evidence_table(items: list[CollectedPrice]) -> None          # A/B 직접근거만. X등급이나 discovery 후보가 들어오면 ValueError
def candidate_table(discovery: G2BUnmappedDiscoveryResult | None) -> None   # 점선·회색·접힘·컬럼명 "표기 금액 (미검증)"
def observation_cards(items: list[CollectedPrice]) -> None        # (source_name, vat_status)별로 분리. 합친 범위·중앙값을 그리지 않는다
def verdict_card(state: QuoteReviewState, item_index: int) -> None
def search_progress(label: str)                                   # st.status 래퍼
```

빠른 검색과 견적 검토 S4가 같은 위젯을 쓴다.

### 재사용할 기존 함수 (새로 만들지 말 것)

| 단계 | 함수 |
|---|---|
| S1 | `extract_quote_file`, `diagnose_quote_extraction`, `diagnose_quote_extraction_error`, `runtime_readiness.ocr_runtime_readiness` |
| S2 | `build_quote_condition_profile` (`quote_condition_comparison.py`), `parse_quote_decimal` |
| S3 | `canonical_manufacturer`, `resolve_verified_g2b_mapping`, `pages/4_의료기기_시장조사.py`의 exact identity 블록 로직 |
| S4 | `build_collectors`, `search_all`, `discover_unmapped_g2b_candidates`, `assess_prices`, `build_price_condition_profile` |
| S5 | `evaluate_quote_comparability_candidate`, `compare_quote_to_evidence_conditions` |
| S6 | `create_quote_comparable_approval`, `apply_quote_comparable_approval`, `quote_evidence_pair_key`, `assess_prices` |

### 서비스 층에 허용된 최소 변경 (2개뿐)

1. `QuoteExtractionResult`에 `excluded_rows: tuple[ExcludedRow, ...]` 추가 — summary로 버린 행의 라벨·행번호·금액. (`quote_extraction_core._extract_sheet_rows`가 채움)
2. `quote_extraction.py`의 `_extract_pdf_context` shim이 VAT 포함/별도 동시 검출 시 `warnings`에 `"VAT 표기가 상충합니다(포함/별도 동시 검출) — 원문 확인 필요"`를 추가하고 `vat_status=""` 유지

이 둘 외의 서비스 변경이 필요하다고 판단되면 **구현하지 말고 보고서에 적는다.**

**이미 상류에 구현된 것 — 새로 만들지 말고 그대로 쓴다 (PR #84–#88):**

- `SourceRunStatus`가 `request_count` / `request_budget`를 갖는다 → S4 출처 상태 표의 "요청 n/120"은 이 값을 읽어 표시만 하면 된다
- `VerifiedG2BShoppingSearchCollector`가 `window_count` 등 수집 telemetry를 노출한다
- `Settings.g2b_search_request_budget`(기본 120)로 예산이 설정 가능하다
- 불완전 출처 경고, discovery 짧은 모델 토큰 보호, OCR 실행 readiness, build identity fail-closed

---

## 4. 먼저 읽을 것

- `RESTRUCTURE_QUOTE_REVIEW.md` (전체)
- `README.md`, `docs/ARCHITECTURE.md`, `docs/F3_PRODUCT_MATCHING.md`, `docs/PHASE1_PRICING_SAFETY.md`, `docs/SINGLE_SCREEN_PURCHASE_REVIEW.md`
- `pages/2_견적서_분석.py`, `pages/9_*.py`, `pages/10_*.py`, `pages/11_*.py`, `pages/12_*.py` — 흡수 대상. 각 페이지가 호출하는 서비스 함수와 session_state 키를 표로 정리한 뒤 시작한다
- `pages/1_통합검색.py` — S4/빠른 검색 결과 레이아웃의 현재 구현
- `src/purchase_price/services/search.py` — `SearchRun`, `SourceRunStatus`
- `tests/test_streamlit_startup_smoke.py` — 새 페이지도 이 smoke를 통과해야 한다

---

## 5. PR 순서 — 각 PR은 CI 통과 후 보고, **자동 merge 금지**

| PR | 브랜치 | 내용 | 완료조건 |
|---|---|---|---|
| R1 | `ui/quote-review-state` | `ui/quote_review_state.py` + `can_enter` + 테스트 | 6개 게이트 각각 통과/차단 + reasons 문장 테스트 |
| R2 | `ui/shared-widgets` | `ui/widgets.py` + `pages/1_통합검색.py`를 위젯으로 교체 (동작 동일) | `evidence_table`에 X등급 넣으면 예외; `observation_cards`가 VAT 상태 다른 근거를 합치지 않는 테스트; startup smoke 통과 |
| R3 | `ui/quote-review-s1-s3` | `2_견적_검토.py` 3열 레이아웃 + 스텝퍼 + S1–S3 (S4 이후 "준비 중") + 서비스 최소변경 1·2 | synthetic xlsx 업로드 → S3 도달 (테스트는 render 함수를 state로 호출) |
| R4 | `ui/quote-review-s4` | S4 + `st.status` 진행 (요청수는 기존 `SourceRunStatus` 필드를 읽기만) | 요청수가 출처 상태 표에 표시 |
| R5 | `ui/quote-review-s5-s6` | S5·S6 + `quote_review_export` | 승인 → 판정 → JSON 다운로드; JSON에 파일명·원문 텍스트 없음 |
| R6 | `ui/navigation-and-cleanup` | 대시보드, `st.navigation` 섹션(관리자 플래그), 의료기기 조회·관리 탭 통합, 구 페이지 6개 삭제 | 담당자 메뉴 4개, 관리자 메뉴 5개; startup smoke |

R1·R2는 기존 화면을 깨지 않는다. R3부터는 구 페이지와 병행하고 R6에서 삭제한다.

**한 세션의 목표는 R1→R5다.** R3에서 멈추면 3단계에서 끊긴 화면만 남아 아무도 흐름을 평가할 수 없다. 견적 하나가 업로드부터 판정까지 실제로 흐르는 R5까지 가야 이 설계가 검증 가능해진다. R6(대시보드·네비게이션·구 페이지 삭제)은 구조 작업이라 다음 세션으로 미뤄도 된다.

시간이 부족하면 R5를 줄이지 말고 **R6을 버린다.** 각 PR은 독립적으로 리뷰 가능해야 하고, 앞 PR 머지를 기다리지 않고 이어서 만들어도 된다.

---

## 6. 테스트

- `tests/test_quote_review_state.py` — 게이트
- `tests/test_widgets_contract.py` — 위젯 계약 (Streamlit은 `unittest.mock`으로 st를 대체하거나, 위젯을 "데이터 준비 함수 + st 호출"로 나눠 데이터 준비 함수를 테스트)
- `tests/test_quote_review_export.py` — JSON 비식별
- 기존 `tests/test_streamlit_startup_smoke.py`가 새 페이지를 자동으로 포함한다 (pages glob)

기존 테스트를 통과시키려고 서비스 계약을 완화하지 않는다.

---

## 7. 검증 — 전부 실행

```bash
ruff check .
pytest -q
python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch --output artifacts/match-benchmark-predictions.csv
python -m purchase_price.scripts.run_phase0_validation --offline --begin-date 20260714 --end-date 20260813 --output-dir artifacts/phase0-validation-offline
python -m purchase_price.scripts.run_controlled_uat --output-dir artifacts/controlled-uat-offline
```

PR 생성 후 GitHub Actions를 **실제로 확인**한다. 성공을 보지 않고 "통과 예상"이라고 쓰지 않는다.

**Production 반영 확인은 하지 않는다** (자동 배포되지만 이 세션은 Production 검증 권한이 없다). 보고서에 "Production 미검증"으로 적는다.

---

## 8. 작업환경

- **Python 3.11**. 시스템 `python`은 3.14라 CI(3.11)와 다르다. 저장소의 `.venv`(3.11.15)를 쓴다. 없으면 `uv venv --python 3.11 .venv` → `VIRTUAL_ENV="$PWD/.venv" uv pip install -e ".[dev]" -r requirements.txt`. Git Bash에서 `export PATH="$PWD/.venv/Scripts:$PATH"`.
- **git identity 미설정** — 커밋 전 repo-local로 설정.
- **`.env`/API key 출력 금지.** `.env.example`의 키 필드는 비어 있어야 한다. `git status`에 `.env.example` 수정이 보이면 키가 들어간 것이니 먼저 조치.
- 이 작업에 서비스키는 필요 없다. 키가 설정된 환경에선 `tests/test_manufacturer_public_catalog.py::test_registry_can_enable_real_manufacturer_source_without_mock`이 실패하니 `DATA_GO_KR_SERVICE_KEY= DATA_GO_KR_MARKET_SERVICE_KEY= G2B_SERVICE_KEY= MFDS_SERVICE_KEY= pytest -q`로 실행.
- `tests/test_pdf_ocr_real_e2e.py`는 로컬에 tesseract가 없으면 실패한다. 이 실패 1건은 알려진 것이며 CI에서는 통과한다 — 보고서에 그렇게 적는다.
- destructive reset·force push·history 훼손 금지. 실제 병원 견적·가격·업체명을 저장소에 넣지 않는다 (테스트는 synthetic).

### 알려진 미해결 결함 (이 작업 범위 아님 — 건드리지 말고 보고서에 언급만)

`main` `9c95e07` 기준으로 아직 열려 있는 것:

- **2·3·5년 검색 옵션은 실 API가 `code=07`(입력범위값 초과)로 거부한다.** `g2b_verified_search.py`가 `end_date - (lookback_days - 1)`을 한 window로 보내고 365일 초과를 사전 분할하지 않는다. S4 화면에서 기간 선택을 노출할 때 이 사실을 알고 만들 것 — 기본 1년만 정상 동작한다. 수정은 별도 PR.
- **UAT release gate 키(`xlsx/xls/pdf_text/pdf_ocr/pdf_commercial`)와 UI strategy 라벨이 불일치**해 gate가 통과될 수 없다. **R6에서 관리 탭에 UAT를 통합할 때 이 매핑을 함께 고치지 말 것.** 화면만 옮기고 매핑 수정은 별도 PR.
- Production 배포 환경(OCR 미설치, Python 3.14) — 플랫폼 문제이며 코드로 해결되지 않는다.
- `docs/tmp85-never.md`(내용 `x`)는 PR #85에서 딸려 들어간 것으로 보이는 임시 파일이다. 이 작업에서 지우지 말고 보고서에만 적는다.

이전 리뷰에서 지적됐다가 **PR #84–#88로 이미 수정된 것**(다시 고치지 말 것): live smoke `base_url=None` 크래시, discovery 짧은 모델 토큰, 수집 telemetry·불완전 경고, OCR 실행 readiness, build identity.

---

## 9. 커밋·PR

의미 단위 커밋. 예:

```
feat(ui): add QuoteReviewState and step gates
feat(ui): shared evidence/candidate/observation widgets
refactor(ui): render 통합검색 results with shared widgets
```

PR body에는 반드시: 문제 / 변경 파일 / 서비스 층 변경 여부(3개 허용 목록 외 없음을 명시) / 안전계약 영향 없음 근거 / 테스트 / CI run 링크 / Production 미검증.

---

## 10. 최종 보고 형식

1. 기준선 — 시작 main SHA / branch / 최종 HEAD
2. 흡수 대상 페이지의 서비스 호출·session 키 정리표
3. 만든 PR 목록과 각 CI 상태
4. 서비스 층 변경 목록 (허용 3개 중 무엇을 했는지)
5. 검증 결과 (ruff / pytest count / benchmark / offline / controlled UAT)
6. 미검증 (Production, 스캔 PDF 등)
7. 설계 문서와 다르게 구현한 곳과 이유
8. 다음 세션이 이어받을 R번호와 남은 일

---

## 중요

이 작업의 핵심은 화면을 예쁘게 만드는 것이 아니라 **담당자가 "지금 왜 판정이 보류인지, 다음에 무엇을 해야 하는지"를 화면 한 곳에서 읽게 하는 것**이다. 오른쪽 카드의 `reasons` 목록이 그 역할이며, 그 문장은 게이트 함수가 만든다 — 화면에서 지어내지 않는다.

미검증 후보를 근거처럼 보이게 하거나, 조건이 다른 근거를 한 범위로 합쳐 보여주는 화면은 어떤 이유로도 만들지 않는다.
