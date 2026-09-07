# Claude 적대적 리뷰 — G2B 가격근거 계층화 + 규격/예산 기반 추정 v1

- 리뷰 요청: `docs/REVIEW_REQUEST_CLAUDE_G2B_PRICE_EVIDENCE_V1.md` (PR #109 브랜치)
- 검토 대상: `main` `f9999ae`, PR #108 (`a1d9957`), Draft PR #109 (`ef26a46`)
- 리뷰일: 2026-09-07
- 성격: 코드·설계·live 실측 기반 리뷰. **코드 수정 없음.**

---

## 0. 실제로 확인한 것

| 항목 | 결과 |
| --- | --- |
| PR #108 CI | `test` **FAIL** — `test_unmapped_discovery_ranks_exact_model_but_keeps_category_research`: 기대 `'분류 후보'`, 실제 `'동일분류·대체 후보'` (라벨 변경 후 테스트 미갱신). `anesthesia-research`·`synthetic-ocr` pass |
| PR #108 로컬 (worktree, 키 미설정) | 407 passed / 1 failed (동일 테스트), ruff pass |
| PR #109 CI | pass (문서만) |
| **live probe** (`probe_g2b_market_sources --keyword 마취 --lookback-days 30`, 로컬 `.env` 키) | **입찰공고·낙찰·사전규격 3개 source 전부 `HTTP 403 code=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR`**. 요청 3회, 기록 0건 |
| Research → CollectedPrice 변환 경로 | 없음 (`grep CollectedPrice(` in services: shopping/manufacturer collector만) |
| `assess_prices` 입력 | `run.results`(search_all) 또는 승인된 사본만. Research bundle·discovery는 어디서도 입력되지 않음 |
| Production 실행 | **미검증** (Production 키가 로컬 키와 다른지 확인 불가) |

---

## 1. Verdict

### `REDESIGN REQUIRED` — 단, 원칙이 아니라 전제와 경계가 문제다

명세의 골격(Actual / Alternative / Budget / Context 4분리, Budget Estimate를 `CollectedPrice` 밖 projection으로, `assess_prices` 격리)은 옳고 현재 코드가 이미 그 격리를 지키고 있다. 그 부분은 바꿀 필요가 없다.

REDESIGN이 필요한 이유는 세 가지다.

1. **Research API가 이 환경의 키로는 전부 403이다.** 입찰·낙찰·사전규격이 모두 `code=30 등록되지 않은 서비스키`다. 명세 Phase B~D(Budget Estimate, 2-pass 분류 확장, 대체품)는 **전부 이 세 API 위에 서 있다.** #108의 key routing은 "다른 키가 있다"는 가정이고, 그 키가 실제로 세 서비스에 활용신청되어 있는지는 코드로 해결되지 않는다. Phase A의 완료조건은 "CI green"이 아니라 **"live probe 3/3 success"** 여야 한다.
2. **요청 예산이 설계돼 있지 않다.** #108 기준 품목 1건 = 최대 약 122 요청(§5-2 산식). 개발키 일일 1,000건이면 5품목 견적 하나로 절반이 사라진다. 403 상황에서도 source당 term 수만큼 실패 요청을 반복한다.
3. **"동일분류·대체 후보" 판정이 문자열 겹침이다.** #108의 `_terms_semantically_overlap`은 substring/토큰 교집합으로 대체품을 만든다. `냉장고`로 검색하면 `시신보관냉장고`가 "동일분류·대체 후보"가 되고, 그 가격이 대체품 band 중앙값에 들어가며, 그 분류명이 다시 검색 큐에 올라간다. P2-2(#30)에서 matcher 층에서 금지한 substring 판정이 Research 라벨링에 되살아났다.

셋 다 명세 문서를 고쳐서 해결되는 것이 아니라 **전제(키), 예산(호출), 판정 기준(코드 vs 문자열)** 을 다시 정하는 일이다.

---

## 2. Findings

### F1 — BLOCKER — Research API 3종이 현재 키로 403이며, 이 사실이 운영 진단에 보이지 않는다

- **문제**: `BidPublicInfoService`, `ScsbidInfoService`, `HrcspSsstndrdInfoService` 모두 `code=30`. `runtime_readiness`·운영진단 페이지에는 shopping 키 smoke만 있고 research 키 smoke가 없다 (#108도 추가하지 않음). 운영자는 견적을 올려 "조회 실패" 경고를 볼 때까지 모른다.
- **왜 위험한가**: 명세 §12 Phase A가 "CI green"을 완료조건으로 두면, 실 API가 한 건도 안 나오는 상태로 Budget Estimate·대체품 UI가 머지된다. UI는 "0건"이 아니라 "조회 실패"로 표시되긴 하지만, 시스템의 핵심 가치(입찰 자료로 마취기 가격 찾기)는 0이다.
- **재현**: `python -m purchase_price.scripts.probe_g2b_market_sources --keyword 마취 --lookback-days 30` → 3 sources failure, code=30.
- **권장 수정**:
  1. data.go.kr 마이페이지에서 키별 활용신청 서비스 목록을 확인하고, **세 서비스 각각에 승인된 키를 확정** (제품 소유자 작업).
  2. `runtime_readiness`에 `g2b_research_credential` 항목 + 운영진단 페이지에 research live smoke 버튼(입찰공고 1건, 30일, `numOfRows=1`).
  3. `_run_source`에 **인증 오류 circuit breaker**: `code=30`/`HTTP 403`이면 그 source는 첫 term에서 중단하고 `NOT_AUTHORIZED` 상태로 반환 (현재는 `FAILURE`로 뭉개지고 term마다 재시도).
  4. Phase A 완료조건에 "probe 3/3 success, key_source 명시" 추가.
- **관련**: `services/market_research.py:_run_source`, `services/runtime_readiness.py`, `pages/14_운영환경_진단.py`, `config.py`

### F2 — HIGH — 품목당 요청 예산 미설계, 5품목 견적이 일일 quota 절반을 소모

- **문제**: `research_g2b_market`에 총 예산이 없다. #108 기준 상한:
  - bid/award/prespec: `max_terms=10` × 3 source × `ceil(90/30)=3` 창 × 1 페이지 = **90**
  - bid item ≤ 4, contract ≤ 4, shopping discovery `request_budget=24`
  - **품목당 ≤ 122 요청**, 각 요청 retry 최대 ×3 (`max_retries` 2)
- **왜 위험한가**: `docs/F1`에 개발계정 1,000건/일 명시. 5품목 = 610. 403 상태에서는 성공 없이 30 요청/품목을 태운다. 양적 폭증 외에도 dynamic classification 큐(#108)가 term을 최대 4개 더 만든다.
- **재현**: 10 term × 3 source 경로는 `research_g2b_market` 코드 그대로. 창 분할은 `g2b_market_sources._windows` (30일).
- **권장 수정**:
  1. `MarketResearchBudget(total=…, per_source=…)` 하나를 `run_market_research` 최상단에서 만들어 모든 클라이언트에 전달. 초과 시 `PARTIAL`과 사유 표시 (adaptive search의 `G2BRequestBudgetExceeded` 패턴 재사용).
  2. term 우선순위 실행: Tier E → N → G → A 순으로 실행하고 **동일모델 hit이 N건 이상이면 하위 tier 중단** (recall 확장은 필요할 때만).
  3. 90일을 30일 창 3개로 쪼개지 말고, API가 허용하는 최대 창을 live로 확인해 1창으로 (미확인이면 30일 유지하되 term 수를 줄인다).
- **관련**: `services/market_research.py:research_g2b_market`, `ui/market_research.py:run_market_research`, `ui/quote_market_research.py:_ensure_market_research`

### F3 — HIGH — "동일분류·대체 후보"가 문자열 겹침으로 만들어지고, 그 가격이 대체품 band와 검색 큐에 들어간다

- **문제** (#108 `g2b_unmapped_discovery.py`):
  ```python
  classification_related = _terms_semantically_overlap(classification_name, search_term)
  ...
  elif classification_exact or classification_related:
      relevance = "동일분류·대체 후보"
  ```
  `_terms_semantically_overlap`은 substring 또는 2글자 이상 한글 토큰 교집합. 이전 세션 실측: 쇼핑몰 API `dtilPrdctClsfcNoNm`는 서버측 substring 매칭이라 `냉장고` 검색이 `김치냉장고·대형냉장고·실험실용일반냉장고·시신보관냉장고`를 반환한다. 이들 전부가 "동일분류·대체 후보"가 된다.
- **왜 위험한가**:
  1. `summarize_g2b_research_bands`가 이 라벨로 **대체품 가격 band(하단/중앙/상단)** 를 만들어 UI에 금액으로 보여준다.
  2. dynamic queue가 `can_expand`에 이 라벨을 포함해 `시신보관냉장고`를 다시 검색한다 (`max_dynamic_classification_terms=4`).
  3. 명세 §9의 `OFFICIAL_CLASS_EXACT`(코드 동일)와 `TEXT_RELATED_UNVERIFIED`(문자열만) 구분이 코드에서 무너진다 — 둘 다 같은 라벨.
- **재현**: 쿼리 `약품냉장고` → term `냉장고`(discovery fallback) → 시신보관냉장고 레코드 → `classification_related=True` → 대체 band에 포함.
- **권장 수정**:
  1. 라벨을 셋으로 분리: `동일분류(코드 일치)` — `dtilPrdctClsfcNo` == 검증된 mapping 코드 또는 bid item에서 발견한 코드; `분류명 정확일치(코드 미확인)`; `문자열 관련(참고)`. **band와 dynamic queue는 첫 번째만.**
  2. `_terms_semantically_overlap` 삭제. 접미사 공유는 관련성 근거가 아니다(P2-2 계약).
  3. dynamic queue enqueue 조건에서 "동일분류·대체 후보" 제거, "모델/제조사 표기 후보"의 분류만 허용 + 그 분류의 **코드**를 함께 큐에 넣어 재검색 결과를 코드로 필터.
- **관련**: `services/g2b_unmapped_discovery.py:_candidate_from_record`, `_terms_semantically_overlap`, `services/market_price_research.py:summarize_g2b_research_bands`, `ui/market_research.py:render_market_reference_summary`

### F4 — HIGH — Budget Estimate의 "명시 예정단가" 필드가 live로 확인된 적이 없다

- **문제**: `g2b_bid_items.parse_bid_purchase_item`은 `presmptUnitPrce / estmUnitPrc / prdctUnitPrc / unitPrce / unitPrc` 중 첫 값을 `ESTIMATED_UNIT_PRICE`로 잡는다. 이 필드명은 추정이며(`docs/F1`: 다른 operation은 "이름만 식별"), 실응답 fixture가 없다(403이라 못 받음). 명세 §7.1 HIGH 조건은 "field semantics로 확인됨"인데 확인 수단이 없다.
- **왜 위험한가**: 어떤 필드가 잡히느냐에 따라 총액이 단가로 들어올 수 있다. 예: 응답에 `prdctUnitPrc`가 없고 `unitPrce`가 품목 합계라면 즉시 오류 단가가 HIGH로 표시된다.
- **권장 수정**: F1 해결 후 **실응답 fixture를 캡처해 `tests/fixtures/g2b_bid_items/*.json`로 고정**하기 전까지 `ESTIMATED_UNIT_PRICE` 경로는 Budget Estimate 입력에서 `BLOCKED`. 필드 후보 목록은 fixture 기반으로 1개로 줄인다.
- **관련**: `services/g2b_bid_items.py:parse_bid_purchase_item`

### F5 — HIGH — single-item 판정 규칙에 빠진 케이스

명세 §7.2/7.3을 코드 경로로 옮기면 다음이 뚫린다.

| 케이스 | 현재 명세 | 뚫리는 이유 | 추가 규칙 |
| --- | --- | --- | --- |
| 품목상세 목록이 잘림 | 언급 없음 | `max_pages_per_bid=1`, `numOfRows=100`. 101번째 품목이 있으면 single로 오판 | `total_count == fetched`일 때만 판정. 아니면 BLOCKED |
| `1 식 / SET / 세트 / 일식` | "package ambiguity" 원칙만 | 단위 문자열 검사 없음 | 단위 stoplist → BLOCKED |
| 품목명 `가스마취기 외 3종` | 없음 | 행은 1개, 실제는 4종 | 제목/품목명에 `외 \d+종`·`외` → BLOCKED |
| 재공고 (`bidNtceOrd` 001, 002…) | BUD-10 dedupe는 source id 기준 | source id에 order가 포함되어 **같은 공고가 order마다 별도 estimate** | 공고번호 기준 최신 order 1건만 |
| 수량 0·소수·음수 | `quantity > 0`만 | `0.5` 통과 | 정수 ≥ 1 |
| 사전규격 `asignBdgtAmt` | BUDGET_AMOUNT를 파생 input 후보로 | 사전규격은 사업 단위. 품목상세와 연결되지 않으면 다품목인지 알 수 없음 | prespec 예산은 **연결된 bid item 목록이 1건임을 확인한 경우만** |
| 입찰공고 `presmptPrce` | ESTIMATED_PRICE → 파생 input 후보 | 공고 단위 추정가격 = 전체 품목 합 | 위와 동일 |
| VAT | "임의 추정 금지" | 추정가격·기초금액·낙찰금액은 **법령상 VAT 포함/제외가 정의된 금액**이다. unknown으로 두면 quote delta가 영원히 금지 | amount_type별 VAT basis를 **법령 근거 URL과 함께 registry로 고정**(§6 질문). 근거 확보 전엔 unknown 유지 |
| 옵션·설치·교육 포함 총액 | 금지 조건에 있음 | 판정 수단 없음 | 품목상세에 `설치`·`교육`·`유지보수` 행이 있으면 BLOCKED; 없으면 MEDIUM에 "부대비용 포함 가능" 플래그 |

- **관련**: 명세 §7, `services/g2b_bid_item_enrichment.py`(max_pages_per_bid), `g2b_research_linking.py`

### F6 — MEDIUM — `AWARD_TOTAL / CONTRACT_TOTAL` 일괄 금지는 가장 좋은 신호를 버린다

- **문제**: 명세는 낙찰총액·계약총액을 Level 4 Context로 고정한다. 그러나 **단일품목 입찰의 낙찰금액은 실제 거래된 금액**이고, 예산(Level 3)보다 증거력이 높다. "예산 ÷ 수량은 MEDIUM인데 낙찰금액 ÷ 수량은 금지"는 증거 위계가 뒤집힌 것이다.
- **권장**: F5의 single-item 게이트를 그대로 통과한 경우에 한해 `SINGLE_ITEM_AWARD_DIV_QUANTITY` basis를 추가하고 Level 3 안에서 예산 파생보다 **위**에 둔다. 여전히 `CollectedPrice`가 아니며 identity 없이는 판정에 못 들어간다. 다품목·귀속불명은 명세대로 금지. 이건 제품 소유자 결정(§6).
- **관련**: 명세 §6, §7.3, `services/g2b_market_sources.py:parse_award`

### F7 — MEDIUM — VAT 미확인 상태에서 quote delta가 계산·표시된다

- **문제**: `quote_delta_from_market_median`은 VAT를 보지 않는다. `render_market_reference_summary`는 "동일모델 표기 후보" band에 대해 delta%를 표시한다. 쇼핑몰 응답에는 VAT 필드가 없다(이전 세션 실측). 명세 §7.4 "VAT 불명이면 직접 비교 문구 금지"와 충돌.
- **권장**: delta는 `quote.vat_status`와 band의 VAT basis가 모두 확정되고 같을 때만. band 단위로 VAT basis를 들고 다니게 `MarketReferenceBand`에 `vat_basis` 추가.
- **관련**: `services/market_price_research.py:quote_delta_from_market_median`, `ui/market_research.py`

### F8 — MEDIUM — 파일명 힌트가 일반명사 꼬리를 검색어로 만든다

- **문제**: `build_quote_filename_research_hints`는 접미 phrase를 넓이 4→1로 전부 만든다. `재활의학과 로봇보조 정형용 운동장치 견적2.pdf` → `운동장치`까지 포함. `내과 진료실 모니터 견적.pdf` → `모니터` → 쇼핑몰 전산용 모니터 483건이 "동일분류·대체 후보"(F3)로 유입. 부서 접미사 stoplist(`과·부·팀…`)는 첫 토큰만 검사한다.
- **권장**: (1) 1토큰 힌트 금지 또는 generic stoplist(`장치·시스템·모니터·기기·장비·세트`); (2) 힌트는 **입찰공고(Tier N)** 검색에만 쓰고 쇼핑몰 discovery term으로는 넣지 않는다(쇼핑몰은 substring 매칭이라 폭증); (3) 힌트를 만든 근거(파일명)를 UI에 이미 표시하고 있음 — 유지.
- **관련**: `services/quote_research_hints.py`, `ui/quote_market_research.py:_query_for_item`

### F9 — MEDIUM — `research_g2b_mapping_terms`가 **미검증 mapping 행**을 substring으로 끌어온다

- **문제**: #108이 `resolve_verified_g2b_mapping`과 별도로 `research_g2b_mapping_terms`를 추가해 `mapping_status`와 무관하게 `detail_product_name`이 있는 행을 `row_key in product_key or product_key in row_key`로 선택한다. 현재 registry에 detail name이 있는 행은 verified 5개뿐이라 당장은 안전하지만, 조사요청 상태 행에 후보 분류명이 들어가는 순간(예: Flow-C → `마취기(42182001)` 후보) 그 후보가 Research term이 된다. Research-only라 판정에는 안 들어가지만 F3와 결합하면 "동일분류" 라벨의 근거가 된다.
- **권장**: 이 함수는 `mapping_status in {verified, research_alias}`만 읽고, substring 대신 정확일치 + registry의 명시 alias만 사용.
- **관련**: `services/g2b_product_mapping.py:research_g2b_mapping_terms`

### F10 — MEDIUM — `EvidenceType.BID_BASE_AMOUNT / BUDGET_AMOUNT`는 죽은 값이며 유혹이다

- **문제**: `domain.EvidenceType`에 두 값이 있으나 생성하는 코드가 없다. `ResearchAmountType`에 같은 의미가 별도로 있다. 미래에 누군가 `CollectedPrice(evidence_type=BUDGET_AMOUNT)`를 만들면 `DIRECT_PRICE_EVIDENCE_TYPES`엔 없어 판정엔 안 들어가지만 `render_evidence_table`·`observation` 경로에 흘러들 수 있다.
- **권장**: 두 값을 deprecated 주석 + `test_domain_contract`로 "생성 금지" 고정, 또는 삭제. Budget Estimate는 명세대로 `ResearchAmountType`/별도 projection만 쓴다. **명세 질문 A3 답: 의미 충돌은 EvidenceType 쪽에 있다.**
- **관련**: `domain.py`, `tests/test_evidence.py`

### F11 — MEDIUM — #108 CI 실패의 올바른 수정은 assertion 갱신이 아니다

- **문제**: 실패 테스트는 `dtilPrdctClsfcNoNm="마취기"`인 X-100 레코드(제조사 Other)가 `'분류 후보'`이길 기대한다. #108은 이를 `'동일분류·대체 후보'`로 바꿨다. 검색 term `마취기`와 분류명 `마취기`가 **정확일치**이므로 "동일분류"는 맞지만, F3 때문에 같은 라벨이 `시신보관냉장고`에도 붙는다.
- **권장**: F3의 라벨 분리를 먼저 하고, 이 테스트는 `'동일분류(코드 미확인)'` 같은 새 라벨을 기대하도록 갱신. 지금 assertion만 바꿔 green을 만들면 F3가 그대로 머지된다.
- **관련**: `tests/test_g2b_unmapped_discovery.py:113`

### F12 — LOW — `ProductQuery.research_hints`가 identity 객체에 실린다

- **문제**: frozen dataclass 필드 추가로 `ProductQuery` 동등성이 힌트에 좌우된다. `grade_product_identity`는 힌트를 무시하므로 판정 영향은 없다. 그러나 `QuoteReviewState` 무효화·캐시 키에 `ProductQuery`를 쓰는 곳이 생기면 힌트 변화가 재검색을 유발한다.
- **권장**: 힌트를 `ResearchQuery(identity: ProductQuery, hints: …)`로 분리하거나, 최소한 `ProductQuery.identity_key()`를 두고 캐시는 그것만 쓴다.

### F13 — LOW — 30일 창 분할이 "documented/observed"로만 적혀 있다

- `g2b_market_sources.G2B_RESEARCH_MAX_WINDOW_DAYS = 30`의 근거가 코드 주석뿐. 403이 풀리면 1회 probe로 실제 한계(30/90/365)를 확인해 창 수를 줄인다(F2와 직결).

---

## 3. 격리 검증 (명세 §D) — 통과

| 검사 | 결과 |
| --- | --- |
| Budget Estimate가 `DIRECT_PRICE_EVIDENCE_TYPES`에 들어갈 가능성 | 현재 코드에 Budget Estimate 생성 없음. `ResearchAmountType`은 `EvidenceType`과 다른 enum이라 집합에 들어갈 수 없음 |
| `assess_prices()`에 Research 유입 | 호출 6곳 전부 `run.results` 또는 승인 사본. `market_bundles`·`discoveries`는 `quote_review_s5_s6.py`에서 표시용으로만 읽힘 |
| C/D가 direct range에 | `pricing._is_observed_direct`가 A/B만. 변경 없음 |
| 동일 세부품명으로 C/D 과승격 | discovery는 `MatchGrade`를 만들지 않음. `G2BDiscoveryCandidate`엔 grade 필드 없음 |
| query expansion이 MatchGrade 근거로 | `grade_product_identity` 입력은 product/manufacturer/model/spec만 |
| comparability gate 우회 | `evaluate_quote_comparability_candidate` 단일 경로, 변경 없음 |

**격리는 지켜지고 있다.** 위험은 "판정에 섞이는 것"이 아니라 "Research 화면의 숫자가 잘못된 라벨을 달고 보이는 것"(F3·F7·F8)이다.

---

## 4. Scope recommendation

### v1에 반드시 포함
- F1: 키 확정 + research readiness/smoke + 403 circuit breaker
- F2: 품목당 총 요청 예산 + tier 순차 실행/조기 중단
- F3: 분류 라벨 3분리, `_terms_semantically_overlap` 제거, band/queue는 코드 일치만
- F4: bid item 실응답 fixture 확보 전 `ESTIMATED_UNIT_PRICE` BLOCKED
- F5: single-item 게이트 보강(완전성·단위 stoplist·`외 N종`·재공고·정수 수량)
- F7: VAT basis 없는 delta 금지
- UI 4구역 분리 (명세 §10) — 단 "대체품 band 중앙값"은 코드 일치 후보만

### 후속으로 미뤄도 됨
- dynamic classification 2-pass 큐 (F3 해결 + fixture 확보 후)
- 파일명 힌트의 쇼핑몰 적용 (F8) — 입찰공고에만 먼저
- 낙찰 단일품목 파생(F6) — 제품 소유자 결정 후
- 범용 Category Resolver — **v1 제외** (명세 §11.2 iPhone 시나리오는 registry 없이 하지 않는다)
- 성능 비교

### 삭제/단순화 권고
- `_terms_semantically_overlap` (F3)
- `EvidenceType.BID_BASE_AMOUNT / BUDGET_AMOUNT` deprecate (F10)
- `research_g2b_mapping_terms`의 substring 선택 (F9)
- `parse_bid_purchase_item`의 5개 필드 후보 → fixture 확인 후 1개 (F4)

---

## 5. Proposed implementation order

| PR | 내용 | 완료조건 |
| --- | --- | --- |
| **P0-a** `#108 분할 1: key routing + research readiness` | #108에서 `config.py` 키 분리·`registry.py`·probe 스크립트만 추출. `runtime_readiness`에 `g2b_research_credential`, 운영진단에 research smoke. `_run_source` 403 circuit breaker | **Production 운영진단에서 research smoke success** + probe 3/3 success. 이게 안 되면 다음 PR을 시작하지 않는다 |
| **P0-b** `research request budget` | `MarketResearchBudget`, tier 순차 실행, 동일모델 hit 시 하위 tier 중단, 30일 창 실측 후 조정 | 품목 1건 상한 ≤ 40 요청(실측), 5품목 ≤ 200 |
| **P1** `#108 분할 2: expansion (narrowed)` | 파일명 힌트(입찰공고만), `research_g2b_mapping_terms` 정확일치, 분류 라벨 3분리, `_terms_semantically_overlap` 삭제, 실패 테스트를 새 라벨로 갱신, band는 코드 일치만 | `냉장고` 쿼리에서 `시신보관냉장고`가 대체 band에 없음(테스트) |
| **P2** `budget_estimate service` | bid item 실응답 fixture 캡처 → 필드 1개 확정 → `budget_estimate.py` + F5 게이트 + provenance + BUD-01~10 | 명세 §13.1 + F5 추가 케이스 전부 green, fixture 기반 |
| **P3** `UI 4구역` | Actual / Alternative(코드 일치) / Budget / Context, VAT basis 있는 delta만, 첫 화면 3줄 요약 | UI contract test + Production UAT-01~04 |
| P4 (후속) | dynamic classification 큐(코드 기반), 낙찰 파생, 힌트 쇼핑몰 적용 | — |

---

## 6. Missing tests

명세 §13에 없는 것:

1. **403/code=30 circuit breaker** — source가 첫 term에서 `NOT_AUTHORIZED`로 끝나고 나머지 term을 호출하지 않음
2. **품목당 총 요청 예산** — stub client로 호출 수를 세어 상한 초과 시 `PARTIAL` + 사유
3. **single-item 완전성** — `total_count=150, fetched=100` → BLOCKED
4. **단위 stoplist** — `1 식`, `1 SET`, `1 세트` → BLOCKED; `1 대` → 통과
5. **`외 N종`** — 품목명/공고명에 포함 시 BLOCKED
6. **재공고 dedupe** — 같은 `bidNtceNo`, order 001/002 → estimate 1건, 최신 order
7. **분류 라벨** — `dtilPrdctClsfcNo` 일치만 band/queue에 포함; 이름 substring 일치는 `문자열 관련(참고)`로 band 제외 (`냉장고`→`시신보관냉장고` 실측 fixture 사용)
8. **파일명 힌트 stoplist** — `내과 진료실 모니터 견적.pdf`에서 `모니터` 단독 힌트가 나오지 않음
9. **VAT basis 없는 delta 금지** — 쇼핑몰 band(VAT unknown) + quote VAT 포함 → delta None
10. **미검증 mapping 행 미사용** — `mapping_status=조사요청` 행의 detail name이 research term에 나오지 않음
11. **bid item 실응답 fixture** — 필드명 고정 (F4). 캡처 전에는 이 테스트를 `xfail(strict)`로 두어 잊지 않게
12. **`EvidenceType.BUDGET_AMOUNT` 생성 금지** — 생성 시 `test_domain_contract` 실패

---

## 7. Questions requiring product-owner decision

1. **키**: 현재 Production Secrets의 어떤 키가 `BidPublicInfoService / ScsbidInfoService / HrcspSsstndrdInfoService`에 활용신청·승인되어 있는가? 로컬 키는 셋 다 미등록이다. 승인 전에는 명세 Phase B 이후를 시작할 수 없다.
2. **VAT 법적 정의**: 추정가격(부가세 제외)·기초금액/예정가격(부가세 포함)·낙찰금액(포함)의 basis를 법령 근거와 함께 registry로 고정할 것인가, 아니면 v1은 전부 `unknown`으로 두고 delta를 포기할 것인가? (F5·F7)
3. **낙찰 단일품목 파생**(F6): 단일품목 게이트를 통과한 낙찰금액 ÷ 수량을 Level 3 상단에 둘 것인가, 명세대로 Context로만 둘 것인가?
4. **대체품 band 노출**: 코드 일치 후보만으로 줄이면 대체품 band가 비는 경우가 많다. 그때 "대체품 후보 표만 보여주고 band(중앙값)는 숨김"으로 갈 것인가?
5. **요청 예산의 값**: 품목당 40? 견적당 200? 일일 1,000 기준으로 정해야 한다.
6. **#108 처리**: 아래 §8.5 권고대로 분할 머지에 동의하는가?

---

## 8. 최종 질문에 대한 답

1. **이 명세대로 구현을 시작해도 되는가?** — 아니다. F1(키 403)이 해결되고 bid item 실응답 fixture가 1건 있기 전까지는 명세 §7.1의 "field semantics 확인"이 불가능해 HIGH 등급을 만들 수 없다. Phase A를 "probe 3/3 success"로 다시 정의한 뒤 시작하라.
2. **Budget Estimate를 Research-only projection으로 두는 것이 최선인가?** — 그렇다. 현재 격리(§3)가 지켜지는 이유가 정확히 "Research는 다른 타입"이기 때문이다. `EvidenceType` 확장은 F10의 죽은 값이 보여주듯 유혹만 늘린다. 단, projection에 `bid_notice_order`, `item_list_complete`, `vat_basis_source`, `relevance_tier`를 추가하라.
3. **single-item total/quantity 허용조건을 더 좁혀야 하는가?** — 그렇다. F5의 9개 케이스 중 최소 5개(목록 완전성, 단위 stoplist, `외 N종`, 재공고, 정수 수량)는 없으면 오배분이 실제로 발생한다.
4. **v1에 범용 Category Resolver를 포함해야 하는가?** — 아니다. 검증된 registry + bid item 공식 품명 2-pass만. 그 2-pass도 F1이 풀려야 살아난다.
5. **#108은 선행 merge인가 흡수인가?** — **분할**. key routing·probe·readiness는 지금 머지 가치가 있다(단 research smoke를 붙여서). query expansion(라벨 변경, `_terms_semantically_overlap`, 파일명 힌트, mapping substring)은 F3·F8·F9 때문에 그대로 머지하면 안 되고 P1에서 좁혀서 흡수한다. 현재 실패 테스트는 라벨 정책이 정해진 뒤 갱신한다.

---

## 부록 — 요청 예산 산식 (#108 기준)

```
research_g2b_market:
  terms ≤ 10 (max_terms)
  sources = 3 (bid, award, prespec)
  windows = ceil(min(lookback, 90) / 30) = 3
  pages = 1
  → 10 × 3 × 3 × 1 = 90 (성공 시). 403이면 term당 1회 실패 = 30

enrich_market_bundle_with_bid_items: ≤ 4 (procurement_detail_limit)
enrich_market_bundle_with_contracts: ≤ 4
discover_unmapped_g2b_candidates: request_budget = 24

품목당 ≤ 122, 물리 HTTP ≤ 122 × (1 + max_retries=2) = 366
5품목 견적: ≤ 610 논리 요청 / 일일 quota 1,000
```

## 부록 — live probe 원문 (키 마스킹)

```
keyword=마취 lookback=30 key_source=(DATA_GO_KR_SERVICE_KEY)
bid_notice : failure  HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30
award      : failure  HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30
prespec    : failure  HTTP 403 SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30
research_record_count=0
```
