# price-check-assistant — Claude Code 세션 인수인계 (Codex 전달용)

- 작성: 2026-09-04
- 기준 커밋: `faf8ebe` (main)
- 이 세션에서 main에 반영: PR #12, #13, #21
- 현재 검사 상태: Ruff 통과 / `pytest -q` **108 passed** / `benchmark_status=ok`

> 이 문서는 **완료된 작업의 사실 기록 + 남은 작업 목록**입니다. 지시서가 아니라 인수인계 자료이며,
> 검증하지 않은 것은 전부 "미검증"으로 표시했습니다.

---

## 0. 30초 요약

이 세션은 세 가지를 했습니다.

1. **PR #11(F3.1) 적대적 리뷰** → P0 1건, P1 3건을 찾아 PR #12로 수정.
2. **로컬 개발환경 정비** → Docker 없이도 설치되는 스크립트와 환경점검 `doctor`를 PR #13으로 추가.
3. **main CI red 대응** → PR #22와 중복된 부분을 걷어내고 회귀 방지 테스트만 PR #21로 남김.

가장 중요한 산출물은 **`(CN)`/`(VN)` 한정어 처리**입니다. 이것 때문에 노트북 benchmark의
A/B 양성이 구조적으로 나올 수 없던 상태였고, 이후 F7이 이 지점을 근거 기반으로 승격시켜
프로젝트 최초의 A 양성(`ApeosPrint C5570 GK`)이 나왔습니다. 자세한 내용은 §3.

---

## 1. 이 세션에서 main에 들어간 것

| PR | 커밋 | 내용 |
| --- | --- | --- |
| #12 | `e2ea2df` | F3.1 리뷰 수정: 서비스키 로그 마스킹, 페이지네이션 완료판정 수정, 한정어 인식, 창 단위 exact-model 스캔, CI strict benchmark |
| #13 | `1580a52` | 로컬 개발환경: Docker 선택화, `doctor`, Linux/macOS 스크립트, CI 동일 검사 스크립트 |
| #21 | `faf8ebe` | fail-closed 한정어 커버리지 복원, benchmark 기대값 스냅샷 해제 |

---

## 2. PR #12 — F3.1 적대적 리뷰 결과와 수정

### P0 — 서비스키 로그 노출

**파일**: `src/purchase_price/clients/data_go_kr.py`

httpx는 INFO 레벨에서 `HTTP Request: GET <url>`을 남기며, 그 URL에 `serviceKey=<키>`가 포함됩니다.
`.env.example`의 기본값이 `LOG_LEVEL=INFO`이므로 `logging.basicConfig(level=INFO)` 한 줄이면
`DATA_GO_KR_SERVICE_KEY`가 로그 파일에 기록됩니다.

**재현 확인함**: 수정 전 로컬에서 mock transport로 호출해 로그 라인에 키가 그대로 찍히는 것을 확인.
단, **지금까지의 Actions 로그에는 노출되지 않았습니다.** capture/smoke workflow가 basicConfig를
호출하지 않아 httpx 로거가 기본 WARNING이었고, 두 run 로그를 직접 읽어 `DATA_GO_KR_SERVICE_KEY: ***`
외에 키 문자열이 없음을 확인했습니다. `git log --all -p`와 fixture에서도 `serviceKey=` 값 패턴 없음.

**수정**: `httpx`/`httpcore` 로거에 `serviceKey=` 마스킹 필터를 import 시점에 설치하고,
명시 설정이 없으면 WARNING으로 유지. 테스트 3개.

### P1-1 — 페이지네이션 조기 종료

**파일**: `src/purchase_price/services/g2b_pagination.py`

완료 판정이 `page_no * 요청 num_of_rows >= totalCount`였습니다. 서버가 페이지를 요청보다 작게 잘라
주면 조기 종료되어 **부분 결과가 정상 결과로 반환**됩니다. 또 빈 페이지가 와도 `max_pages`까지 반복.

**수정**: 누적 실제 수신 건수로 판정하고, `totalCount` 미달 상태의 빈 페이지는 즉시 실패.
테스트 3개 (`test_pagination_counts_returned_rows_not_requested_rows_when_server_caps_page_size` 등).

### P1-2 — 한정어 오판정 (가장 중요)

**파일**: `src/purchase_price/services/product_matching.py`

실제 G2B 제목에 `(VN)NT960XHA-KG71G`, `(주문자상표부착)삼성전자` 형태의 선행 괄호 한정어가 있습니다.
2026-07-14~08-13 표본의 삼성 노트북 7건 **전부**가 `(VN)`/`(CN)` 모델 한정어를 갖고 있었습니다.

한정어를 토큰에 포함한 채 비교하면 **검색대상 모델 자체가 `model=conflict`로 판정**됩니다. 즉
노트북 benchmark에서 A/B 양성이 나올 수 없는 구조였고, 판정 사유도 틀렸습니다.

**수정**: 한정어를 `model_qualifier` / `manufacturer_qualifier`로 분리 보존.
- 한정어 제거 후에만 모델 일치 → `exact_with_unverified_qualifier`로 **X 유지** (승격하지 않고 사람 검토 대상 표시)
- 제조사 한정어 → 제조사 근거 부족과 동일하게 최대 B

의도적으로 승격하지 않았습니다. 당시 `(VN)`/`(CN)`의 업무적 의미가 공개 근거로 확인되지 않았기 때문입니다.
문서에 "확인되면 별도 PR에서 승격 규칙 검토"라고 후속을 남겼고, **F7(PR #20)이 실제로 그 후속을 수행**했습니다.

### P1-3 — live workflow 자동 반복 실행

**파일**: `.github/workflows/g2b-ground-truth-capture.yml`

push 트리거로 20분 동안 14회 실행되었고(그중 5회가 실제 API 호출), feature 브랜치에 묶여 있어
merge 후에는 동작하지 않을 상태였습니다.

**수정**: `workflow_dispatch` 전용으로 전환하고 `mode=sample|scan` 입력 추가.

### 추가 구현 (F3.1 후속)

- `src/purchase_price/services/g2b_scan.py` + `scripts/scan_g2b_exact_model_candidates.py`
  기간을 `--chunk-days` 창으로 나눠 창마다 끝까지 페이지네이션. 창별 `status/pages/records/totalCount/등급분포`
  요약 CSV. 안전상한·API 오류 창은 `incomplete`로 기록하고 **exit 1** → 부분 스캔을 "후보 0건"으로 오인 방지.
  후보 CSV는 거래가 아니라 **identity 단위 1행** + `transaction_count`, 가격/일자 범위.
- `scripts/capture_g2b_ground_truth_candidates.py`: `(record_id, title)`이 아닌 정규화 제목 단위 dedupe.
- `scripts/evaluate_match_benchmark.py`: `--fail-on-mismatch`(CI 적용), `--output`(판정근거 CSV), `direct_positive_rows` 출력.

---

## 3. `(CN)`/`(VN)` 한정어 — 두 PR의 연결 관계

Codex 쪽에서 가장 헷갈릴 수 있는 부분이라 별도로 정리합니다.

| 시점 | 규칙 | 근거 |
| --- | --- | --- |
| PR #12 (내 작업) | 한정어 제거 후 일치 → **X 유지** | 한정어 의미 미확인. fail-closed 원칙 |
| PR #20 (F7) | `(CN)`/`(VN)`만 **B 승격 허용** | G2B 공식 품목 상세에서 상품원산지국가명 표기임을 확인 |

**F7의 변경은 타당합니다.** 승격 조건이 문자열 일치가 아니라 **G2B parser가 설정한 플래그**
(`model_qualifier_verified_as_origin`)이고, 그 외 한정어는 그대로 fail-closed입니다.
`VERIFIED_G2B_ORIGIN_QUALIFIERS = frozenset({"CN", "VN"})`로 화이트리스트가 명시돼 있습니다.

다만 F7이 기존 `assert grade_counts == {"X": 2}`를 `{"B": 2}`로 바꾸면서, **그 assert가 유일하게
지키던 "한정어 붙은 후보는 A/B로 가지 않는다"는 보호가 scan 경로에서 사라졌습니다.**
PR #21에서 `test_scan_keeps_unverified_qualifier_candidates_at_x`를 추가해 복원했습니다.
`(재제조)` 같은 미검증 한정어가 scan 끝까지 X로 남는지 확인합니다.

---

## 4. PR #13 — 로컬 개발환경

| 문제 | 수정 |
| --- | --- |
| `setup.ps1`이 Docker 없으면 `throw`로 중단 (테스트·Ruff·benchmark는 DB 없이 동작) | DB 단계만 건너뛰고 진행 |
| Docker 유무로 migration 결정 → README가 권하는 로컬 PostgreSQL이 무시되어 빈 DB가 남음 | `DATABASE_URL`에 실제 연결해 보고 결정 (`doctor.database_error()` 공유) |
| `py -3.11` 고정 (pyproject는 `>=3.11`) | `py --list` 후보 중 3.11+ 탐색 |
| `test.ps1`이 Ruff+pytest만 → CI의 strict benchmark 누락 | CI와 동일한 3종 실행 |
| Linux/macOS 스크립트 부재 | `scripts/setup.sh`, `test.sh`, `run.sh` |
| alembic 실행마다 deprecation 경고 | `alembic.ini`에 `path_separator = os` |

### `doctor` 사용법

```bash
python -m purchase_price.scripts.doctor          # 환경 점검
python -m purchase_price.scripts.doctor --strict # 선택 항목까지 요구
```

- **필수**(실패 시 exit 1): Python 버전, 패키지 import, ruff/pytest, streamlit, 데이터 registry
- **선택**(없으면 SKIP, exit 0): `.env`, DB 연결, migration head, `DATA_GO_KR_SERVICE_KEY`
- 서비스키는 **존재 여부만** 출력하고 값은 절대 출력하지 않음 (회귀 테스트로 고정)

`.env` 부재를 선택으로 둔 이유: CI가 실제로 `.env` 없이 전체 테스트를 돌립니다.
처음에 필수로 뒀다가 CI가 깨져서 고쳤습니다(§6 참고).

### 검증한 것

깨끗한 clone에서 두 경로를 실제로 실행했습니다.

| 상황 | setup.sh | doctor |
| --- | --- | --- |
| Docker 없음 + 로컬 PostgreSQL 있음 | exit 0, migration 적용 | ready |
| Docker 없음 + DB 없음 | exit 0, migration 건너뜀 | ready (DB는 SKIP) |

---

## 5. 현재 Phase 0 상태 (실측치)

```
rows=11
exact_grade_accuracy=100.0%
direct_precision=100.0%
direct_recall=100.0%
direct_positive_rows=1
benchmark_status=ok
```

**해석 주의.** A 양성이 **1건뿐**입니다(`ApeosPrint C5570 GK`, F7이 추가). 이 100%를 매칭
성능 지표로 해석하면 안 됩니다. 나머지 10건은 전부 X입니다.

2026-07-14~08-13 구간 전체 스캔(run `33765916042`)에서 Sophie(9건 전수), NT960XJG-K72AG(1,021건 전수)
모두 exact 모델 토큰 후보 **0건**이었습니다. 이 사실은 PR #11 설명과 Actions 로그를 대조해 확인했습니다.

---

## 6. 이 세션에서 발생한 CI 사고 2건 (재발 방지용 기록)

### 사고 1 — `.env`를 필수로 분류

PR #13 첫 push에서 CI 실패. doctor가 `.env`를 필수 항목으로 두어 `.env` 없이 체크아웃하는 CI에서
`test_real_environment_has_no_blocking_check`가 깨졌습니다.

로컬에서 `.env`를 치워 동일 실패를 재현한 뒤 `.env`를 선택 항목으로 내렸고, 같은 상태에서 통과 확인.

**교훈**: 환경 점검 도구를 만들 때 "개발자 PC 기준"과 "CI 기준"이 다릅니다. CI는 `.env` 없이 돕니다.

### 사고 2 — 중복 작업 충돌

main이 PR #20(F7) 머지 커밋 `ff38193`부터 red였는데(run 113 failure), 그걸 모르고 PR #13을
머지해 같은 실패를 물려받았습니다(run 114). 실패한 두 테스트가 제가 작성한 것이라 수정본을
PR #21로 올렸는데, **같은 시각 PR #22가 동일한 두 테스트를 같은 방향으로 고쳐 머지**되었습니다.

**처리**: PR #21에서 겹치는 수정을 전부 버리고 최신 main 위에서 추가분만 남겼습니다.
기존 줄을 하나도 건드리지 않는 순수 추가(+52/-3)로 재작성 후 머지.

**교훈**: 머지 전에 base가 green인지 확인해야 합니다. 여러 에이전트가 동시에 작업할 때는
같은 실패에 각자 달려들 수 있으므로, 착수 전 열린 PR 목록을 먼저 확인하는 편이 안전합니다.

---

## 7. 남은 작업 — 우선순위순

### 7-A. 최우선: A/B 양성 Ground Truth 확대

현재 양성 1건으로는 precision/recall이 의미가 없습니다.

```bash
# GitHub Actions → "G2B Ground Truth Capture" workflow_dispatch
mode=scan
begin_date=20260101  end_date=20260831
chunk_days=31  max_pages_per_chunk=20
```

- `DATA_GO_KR_SERVICE_KEY`가 있는 환경에서 **수동 실행**해야 합니다.
- 결과 summary CSV의 `status` 열이 **전부 `complete`일 때만** "해당 기간 후보 0건"이라고 말할 수 있습니다.
  하나라도 `incomplete`면 부분 스캔이며 CLI가 exit 1로 끝납니다.
- 후보 CSV에서 `predicted_grade=X`이면서 `match_note`에
  `model=exact_with_unverified_qualifier`인 행이 **사람 검토 1순위**입니다.
- **미검증**: 이 scan 경로는 fixture 테스트만 통과했고 실제 live 실행 기록이 없습니다.

### 7-B. P2 — 미수정 리뷰 지적 (현재 main에 그대로 존재함, 재확인 완료)

| # | 파일/위치 | 문제 | 실패 시나리오 |
| --- | --- | --- | --- |
| P2-1 | `src/purchase_price/models.py:82` | `price_observations`에 `(evidence_id, product_id, parser_version)` 유니크 없음, `evidence_id`가 nullable | parser 재처리 시 동일 근거로 중복 관측 생성. RawEvidence 없는 관측도 생성 가능(`seed_demo`가 실제로 그렇게 함) → 감사 추적 끊김 |
| P2-2 | `product_matching.py::_product_class_state` | 부분문자열 포함으로 `compatible` 판정 | "모니터" ⊂ "심전도모니터"가 compatible이 되어 C 과포함 여지. 현재는 C 한정이라 직접가격에는 영향 없음 |
| P2-3 | `services/pricing.py` | VAT/배송/설치/옵션이 문자열로만 보존되고 가격범위 계산에서 정규화되지 않음 | VAT 포함가와 별도가가 같은 범위에 섞여 비교 왜곡 |
| P2-4 | `collectors/g2b_shopping.py::_record_id` | `source_record_id`가 `cntrctDlvrReqNo`(납품요구 단위)라 품목별 고유가 아님 | 한 납품요구에 여러 품목이 있으면 식별 충돌. RawEvidence dedupe는 payload hash라 안전하나, GT/관측 식별자로는 제목과 함께 써야 함 |
| P2-5 | `data/evidence/g2b/f3_ground_truth_sample_*.csv` | `R26TA02135157` 행의 `unit=182` 의미 미확인 | 원문 그대로 보존 중. 단위 해석 시 주의 |

권장 처리 순서: **P2-1 → P2-3 → P2-4 → P2-2 → P2-5**.
P2-1은 migration이 필요하고(현재 migration은 `0001_phase0_foundation` 하나뿐), 데이터 무결성에
직결되므로 먼저입니다. P2-3은 가격 왜곡이라 그다음입니다.

### 7-C. 미검증 항목

| 항목 | 상태 |
| --- | --- |
| `scripts/setup.ps1`, `test.ps1`, `run.ps1` | **실행 검증 안 됨.** 작업환경에 `pwsh`가 없어 정적 검토만 했습니다. Windows 첫 실행 시 `Get-PythonLauncherArgs`의 `py` 탐색부를 먼저 보십시오 |
| `scan_g2b_exact_model_candidates.py` live 실행 | fixture 테스트만 통과. 실제 API 실행 기록 없음 |
| 나머지 16개 benchmark의 G2B 세부품명 매핑 | 20개 중 verified 4개(Sophie, NT960XJG-K72AG, ApeosPrint C5570 GK, ThinkStation P2 Tower)뿐. 나머지 16개는 fail-closed 상태이며 자동 검색에 쓰이지 않음 |
| `(CN)`/`(VN)` 외 한정어의 의미 | 미확인. 현재 전부 X로 fail-closed |

---

## 8. 반드시 지켜야 할 계약 (변경 시 주의)

이 프로젝트의 안전성은 다음 분리에 의존합니다. 건드릴 때는 근거를 반드시 남기십시오.

1. **제품 동일성(MatchGrade)과 금액 의미(EvidenceType)는 독립축입니다.**
   A등급 제품이어도 `BID_BASE_AMOUNT`/`BUDGET_AMOUNT`/`UNKNOWN`이면 직접가격에 넣지 않습니다.
   `pricing.py::_is_direct_comparable`이 두 조건을 AND로 검사합니다.

2. **확신할 수 없으면 X (fail-closed).**
   모델 충돌 → X, 제조사 충돌 → X, 모델 지정 검색인데 후보가 class label만 → X,
   검증되지 않은 한정어 → X. 승격 규칙을 넓힐 때는 **공개 원문 근거**를 함께 커밋하십시오.

3. **A/B 양성이 없으면 precision/recall을 숫자로 만들지 않습니다.**
   `evaluate_match_benchmark`가 `direct_positive_rows=0`일 때 `N/A`를 출력합니다.
   PR #21에서 이 불변식을 테스트로 고정했습니다(양성 0건일 때만 N/A).

4. **부분 결과를 정상 결과로 반환하지 않습니다.**
   페이지네이션 안전상한 초과 → 실패. 스캔 창 미완료 → `incomplete` + exit 1.

5. **Secret은 코드·로그·fixture·PR 어디에도 남기지 않습니다.**
   `doctor`도 서비스키 존재 여부만 출력합니다.

6. **실제 병원 취득금액·계약가격·견적서는 이 공개 저장소에 절대 넣지 않습니다.**
   (`docs/PUBLIC_REPOSITORY_POLICY.md`)

---

## 9. 참고 링크

- 리뷰/수정 PR: [#12](https://github.com/dekt-oss/price-check-assistant/pull/12)
- 로컬 환경 PR: [#13](https://github.com/dekt-oss/price-check-assistant/pull/13)
- 커버리지 복원 PR: [#21](https://github.com/dekt-oss/price-check-assistant/pull/21)
- 열린 이슈: #1(Phase 0), #3(F1), #4(F2), #5(F3), #6(F4), #7(F5), #10(F3.1)
- 설계 문서: `docs/F1_G2B_SHOPPING.md`, `docs/F3_PRODUCT_MATCHING.md`, `docs/PUBLIC_REPOSITORY_POLICY.md`
- 근거 보존: `data/evidence/g2b/README.md`

---

## 10. 빠른 시작 (Codex가 이어받을 때)

```bash
git clone https://github.com/dekt-oss/price-check-assistant.git
cd price-check-assistant
./scripts/setup.sh          # Windows: .\scripts\setup.ps1
./scripts/test.sh           # CI와 동일한 3종 검사
python -m purchase_price.scripts.doctor
```

기대값: Ruff 통과, `108 passed`, `benchmark_status=ok`.
DB나 API 키가 없어도 위 세 가지는 전부 동작해야 합니다. 동작하지 않으면 그것 자체가 회귀입니다.
