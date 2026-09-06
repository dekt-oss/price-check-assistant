# 작업 지시서 — 견적 검토 단일 화면으로 Streamlit 재편

- 저장소: `dekt-oss/price-check-assistant` (기준 `main` `9c95e07`, PR #88까지 반영)
- 설계 캔버스: https://claude.ai/code/artifact/547203fb-2e00-4f65-9001-b98f8c1dd66c (페이지 "견적 검토 6단계")
- 작성: 2026-09-06
- 범위: **UI 층만** 재편한다. `services/`·`collectors/`의 계약(A/B/C/D/X, EvidenceType, ComparisonScope, quote_comparable 승인)은 건드리지 않는다.

---

## 0. 원칙 (이걸 어기면 재편이 아니라 퇴보다)

1. **엔진은 그대로.** 화면은 기존 서비스 함수를 호출만 한다. 새 판정 로직을 페이지 파일에 쓰지 않는다.
2. **한 견적 = 한 상태 객체.** 6단계가 공유하는 `QuoteReviewState` 하나를 `st.session_state`에 두고, 페이지 이동 대신 단계 인덱스를 바꾼다.
3. **단계는 게이트다.** 다음 단계 버튼은 이전 단계의 완료 조건이 참일 때만 활성화. 조건은 상태 객체의 순수 함수로 계산한다(테스트 가능).
4. **미검증 후보는 다른 자료형이다.** `G2BDiscoveryCandidate`는 `CollectedPrice`와 같은 표에 절대 넣지 않는다 (지금도 그렇다 — 유지).
5. **숫자보다 상태가 먼저.** 출처 실패·불완전이 있으면 관측 요약 카드 위에 배지가 먼저 그려진다.
6. **오래 걸리는 검색은 `st.status`로 진행을 보여준다.** 백그라운드 실행은 이번 범위 밖(백엔드 분리 시).

---

## 1. 파일 구조 변경

### 새로 만드는 것

```
pages/
  1_대시보드.py                 ← 신규 (S0)
  2_견적_검토.py                ← 신규: 6단계 단일 화면
  3_빠른_검색.py                ← 통합검색 이름 변경 + 결과 레이아웃을 S4와 동일하게
  4_의료기기_조회.py            ← 시장조사 + 안전공급사 + UDI를 st.tabs로 통합
  9_관리.py                     ← 운영진단 + UAT + Phase0 + 수집상태 + 근거 레지스트리를 st.tabs로
src/purchase_price/ui/
  __init__.py
  quote_review_state.py         ← QuoteReviewState + 단계 게이트 함수 (순수, 테스트 대상)
  quote_review_steps.py         ← 단계별 render 함수 6개 (Streamlit 호출만)
  quote_review_export.py        ← 검토 기록 JSON/보고서 생성
  widgets.py                    ← 출처상태 표, 근거 표, 후보 표, 관측요약 카드, 판정 카드 (재사용 위젯)
```

### 없어지는 것 (기능은 2_견적_검토.py로 흡수)

| 삭제 | 흡수 위치 |
| --- | --- |
| `pages/2_견적서_분석.py` | S1·S2·S4 |
| `pages/9_견적조건_확인.py` | S2 |
| `pages/10_견적_외부조건_대조.py` | S5 |
| `pages/11_견적_비교가능성_게이트.py` | S5·S6 |
| `pages/12_가격근거_최신성.py` | S5(기준일 차이) + 대시보드 "근거 최신성" |
| `pages/7_나라장터_계약근거.py` | 빠른 검색 근거표의 출처 하나로 (별도 페이지 삭제) |

### `st.navigation`으로 섹션 구성 (Home.py)

```python
pg = st.navigation({
    "업무": [대시보드, 견적_검토, 빠른_검색, 의료기기_조회],
    "관리": [관리],          # is_admin일 때만 포함
})
```

`is_admin`은 당장은 secrets의 `ADMIN_MODE=true` 같은 단순 플래그로. 역할 관리는 백엔드 분리 시.

---

## 2. 상태 객체 — `ui/quote_review_state.py`

```python
@dataclass
class QuoteReviewState:
    # S1
    file_name: str | None
    file_kind: str | None                      # xlsx / xls / pdf_text / pdf_scan
    extraction: QuoteExtractionResult | None   # 기존 타입 그대로
    diagnostics: QuoteExtractionDiagnostics | None
    # S2
    items: list[QuoteItem]                     # 담당자 수정 반영본
    item_confirmed: dict[int, bool]            # 품목별 "원문 대조 완료"
    item_notes: dict[int, str]                 # 수정 근거 메모 (원문 행 번호 등)
    vat_conflict: bool                         # S1에서 상충 검출됐는지
    # S3
    identity: dict[int, IdentityResult]        # 제조사 alias · G2B mapping 상태 · MFDS identity
    # S4
    search_runs: dict[int, SearchRun]          # 기존 SearchRun (source_statuses 포함)
    discoveries: dict[int, G2BUnmappedDiscoveryResult | None]
    lookback_days: int
    # S5
    comparability_context: dict[int, QuoteComparabilityContext]
    # S6
    approvals: dict[str, QuoteComparableApproval]   # pair_key → approval (기존 타입)
    reviewer: str
    # 메타
    step: int                                  # 1..6
    started_at: datetime
```

### 단계 게이트 (순수 함수, 전부 테스트)

```python
def can_enter(step: int, s: QuoteReviewState) -> tuple[bool, list[str]]:
    # 2: extraction is not None and len(s.items) >= 1
    # 3: all(item_confirmed[i] for i in items)
    # 4: all(identity[i].ready for i in items)          # mapping verified OR "조사요청" 상태로 명시 확인
    # 5: 하나 이상 품목에 search_runs 존재 (0건이어도 실행됐으면 통과)
    # 6: 하나 이상 (item, evidence)가 eligible_candidate
    # 반환값의 reasons가 오른쪽 카드의 "판정으로 가는 길" 목록이 된다
```

`reasons`는 사람이 읽는 문장으로 반환한다 (예: `"품목 1 원문 대조 미완료"`). 오른쪽 카드는 이 목록을 그대로 번호 매겨 보여준다.

---

## 3. 단계별 매핑 — 무엇을 재사용하고 무엇을 새로 쓰는가

### S1 업로드·추출

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 업로드·임시파일 | `pages/2_견적서_분석.py` 94–116행 로직 | — |
| 추출 | `extract_quote_file` | — |
| 추출 경로/헤더 인식/제외 행 | `diagnose_quote_extraction` | **제외 행 목록** — `_extract_sheet_rows`가 summary로 버린 행을 `QuoteExtractionResult.excluded_rows`로 반환하도록 core에 필드 추가 (라벨·행번호·금액) |
| VAT 상충 경고 | (현재 silent) | `_extract_pdf_context` shim이 상충 시 `warnings`에 문장 추가 + `vat_conflict=True` |
| 스캔 PDF 불가 안내 | `runtime_readiness.ocr_runtime_readiness()` | 업로드 전에 readiness를 읽어 스캔본이면 즉시 안내 |

**완료 조건:** 품목 1건 이상 추출. 0건이면 "정답표 직접 입력" 경로(S2에서 빈 행 추가)로.

### S2 품목 확인

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 필드 편집 | `st.data_editor` (page 2의 방식) → 품목별 폼으로 | 수정된 셀 강조: 원본 `extraction.items[i]`와 diff |
| 상업조건 6개 | `pages/9_견적조건_확인.py`의 `build_quote_condition_profile` | 조건별 "원문 근거" 메모 입력 |
| 원문 스니펫 | — | `QuoteItem.source_sheet/source_row`로 원문 행 텍스트를 보여주는 헬퍼 (Excel은 셀 값, PDF는 해당 페이지 텍스트 줄) |
| "원문 대조 완료" | UAT 페이지의 checkbox 패턴 | `item_confirmed[i]` |

**완료 조건:** 모든 품목 `item_confirmed`. 미확인 조건은 그대로 두게 하고 지어내지 못하게 안내.

### S3 제품 식별

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 제조사 alias | `canonical_manufacturer`, `load_manufacturer_aliases` | 표시만 |
| G2B mapping 상태 | `resolve_verified_g2b_mapping` | mapping 없으면 "조사 요청" 버튼 → 관리 탭의 요청 목록에 append (파일 `data/mapping_requests.csv`, 견적값 없이 제조사·모델·제품명만) |
| MFDS identity | `pages/4_의료기기_시장조사.py`의 exact identity 블록 (`model_lookup_succeeded`, `exact_identity.confirmed`, `ambiguous`) | 의료기기 여부 토글 — 아니면 카드 "해당 없음" |
| 식별 요약 | `grade_product_identity`의 입력 요약 | — |

**완료 조건:** 품목별 `identity[i].ready` = (mapping verified) OR (조사요청 등록됨 → S4에서 후보 탐색만) AND (의료기기면 MFDS confirmed).

### S4 근거 수집

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 수집 실행 | `build_collectors`, `search_all` | `st.status("나라장터 수집 중")` 안에서 실행 |
| 요청수 n/120 | `SourceRunStatus.request_count / request_budget` (PR #86에서 이미 노출됨) · 예산은 `Settings.g2b_search_request_budget` | 표시만 |
| 출처별 상태 표 | `run.source_statuses`, 기존 불완전 경고 로직 | `widgets.source_status_table()` — "불완전" 배지: `any(not s.succeeded and not s.skipped)` |
| 직접 비교 근거 표 | `run.results` 중 `_is_observed_direct` | `widgets.evidence_table()` — VAT/배송·설치 열은 `build_price_condition_profile` |
| 미검증 후보 | `discover_unmapped_g2b_candidates` (mapping 없을 때만) | `widgets.candidate_table()` — 점선 카드, 금액 회색, 기본 접힘, 컬럼명 "표기 금액 (미검증)" |
| 관측 요약 | `assess_prices` | **출처·VAT상태별로 분리 표시** — `assess_prices`는 그대로 쓰되 카드는 `(source_name, vat_status)`로 groupby해 각각 min/max. 합친 범위·중앙값은 보고서에서만 "참고" |

**완료 조건:** 검색이 한 번 실행됨. 0건이어도 통과(그 사실이 결과다).

### S5 조건 대조

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 근거 선택 | `pages/11` 171–230행 | 표에서 라디오 선택 |
| 9행 대조표 | `evaluate_quote_comparability_candidate` → `decision.condition_comparison.comparisons` + 수량/단위/통화/기준일 reasons | `widgets.condition_diff_table()` |
| 근거 조건 보완 | — | 근거 쪽 조건을 담당자가 **근거 URL과 함께** 채우는 폼 → `CollectedPrice`를 `replace()`한 사본을 `search_runs`에 반영 (원본 불변). 메모 필수 |
| 견적 조건 수정 | S2로 돌아가기 링크 | — |

**완료 조건:** `eligible_candidate` 1건 이상. 없으면 6단계 버튼 비활성 + 이유 목록.

### S6 승인·판정

| 화면 요소 | 재사용 | 신규 |
| --- | --- | --- |
| 승인 | `create_quote_comparable_approval`, `apply_quote_comparable_approval`, `quote_evidence_pair_key` | 승인 메모 **필수** (빈 문자열 거부) |
| 판정 카드 | `assess_prices(applied_items, quote)` → `quote_position`, `difference_rate` | 문구 규칙: 근거 1건·출처 1개면 "적정" 단어 금지, "승인 근거 대비 위치"로 |
| 검토 기록 | — | `quote_review_export.build_record(state)` → JSON (견적 원문·파일명 제외, 값은 포함 — 이건 내부 기록이므로 다운로드만, 저장소에 넣지 않음) |
| 보고서 | — | 이번 범위에선 JSON + 화면 캡처. PDF는 백엔드 분리 후 |

**완료 조건:** 없음(마지막). 승인 취소는 `approvals.pop(pair_key)`.

---

## 4. 재사용 위젯 — `ui/widgets.py`

빠른 검색(3)과 견적 검토 S4가 같은 표를 쓴다. 위젯 함수 시그니처:

```python
def source_status_table(statuses: list[SourceRunStatus]) -> None
def evidence_table(items: list[CollectedPrice]) -> None          # A/B 직접근거만
def candidate_table(discovery: G2BUnmappedDiscoveryResult | None) -> None
def observation_cards(items: list[CollectedPrice]) -> None        # (출처, VAT상태)별 분리
def verdict_card(state: QuoteReviewState, item_index: int) -> None   # 오른쪽 고정 카드
def search_progress(label: str) -> ContextManager                 # st.status 래퍼
```

`observation_cards`가 합친 범위를 그리지 않는 것이 이 재편의 안전 포인트 중 하나다.

---

## 5. PR 순서 (각각 CI 통과 + Production 클릭 확인)

| PR | 내용 | 완료조건 |
| --- | --- | --- |
| R1 | `ui/quote_review_state.py` + 게이트 함수 + 테스트 | 게이트 6개 각각 통과/차단 테스트 |
| R2 | `ui/widgets.py` + 빠른 검색 페이지를 위젯으로 교체 (기능 동일) | Production 빠른 검색이 기존과 같은 결과 + 관측 카드가 출처별 분리 |
| R3 | `2_견적_검토.py` S1–S3 (S4 이후는 "준비 중") + `excluded_rows` + VAT 상충 warning | xlsx 1건 업로드 → S3까지 도달 |
| R4 | S4 + `st.status` 진행 (요청수는 기존 `SourceRunStatus` 필드 표시) | Production 1년 검색 진행표시·요청수 표시 확인 |
| R5 | S5·S6 + 검토 기록 JSON | 승인 → 판정 → JSON 다운로드 |
| R6 | 대시보드(세션 내 검토 목록) + `st.navigation` 섹션 + 구 페이지 삭제 + 관리 탭 통합 | 담당자 메뉴에 4개만 보임 |

R1·R2는 기존 화면을 깨지 않으므로 UAT 진행 중에도 머지 가능. R3부터는 구 페이지와 병행하다가 R6에서 삭제.

---

## 6. 테스트 (UI 층에도 계약 테스트를 둔다)

- `test_quote_review_state.py`: 게이트 함수 — 각 단계 진입 조건 true/false와 reasons 문장
- `test_widgets_contract.py`: `evidence_table`에 X등급/discovery 후보를 넣으면 예외; `observation_cards`가 VAT 상태가 다른 근거를 한 카드로 합치지 않음
- `test_streamlit_startup_smoke.py`: 새 페이지 5개 import 통과 (기존 방식)
- `test_quote_review_export.py`: JSON에 파일명·원문 텍스트가 없고, 승인 pair_key와 메모가 있음

---

## 7. 이번 범위에서 하지 않는 것 (백엔드 분리 시)

- 화면을 떠나도 계속되는 검색 (작업 큐)
- 견적 검토 레코드의 영구 저장·조회·감사 (DB)
- 역할·인증 (관리자 플래그로 임시)
- PDF 보고서
- 대시보드의 "내 견적 목록"은 세션 내 목록으로만
