# F3 — 제품 정규화 및 A/B/C/D/X 매칭 엔진

## 목적

공개 가격 Evidence가 검색대상 제품과 얼마나 동일한지 보수적으로 판정한다.

`MatchGrade`는 가격의 성격(`EvidenceType`)과 별개다. 예를 들어 실제 납품단가라도 제품 동일성이 X이면 직접 참고가격대에 포함하지 않는다.

## 판정 원칙

| 등급 | 자동판정 기준 | 가격분석 사용 |
| --- | --- | --- |
| A | 정규화된 모델 exact + 제조사 일치/검증 alias + **실제 요구 규격 증거 충족** | 직접가격 |
| B | 모델 exact이나 제조사/규격 증거가 일부 부족하거나 규격·옵션 차이가 있음 | 조건 검토 후 직접가격 |
| C | 동일 제품군이지만 exact 모델 증거 없음 | 참고만 |
| D | 기능적 대체관계를 사람이 명시한 경우만 | 참고만 |
| X | 모델/제조사 충돌, 식별 불충분, 판정근거 부족 | 제외 |

### Fail-closed 규칙

- 모델이 명시적으로 다르면 X.
- 같은 모델 문자열이어도 제조사가 명시적으로 다르면 X.
- 제조사가 비어 있으면 같은 모델이라도 A가 아니라 B.
- **검색 규격이 비어 있으면 제조사+모델이 같아도 B다.**
- `specification` 값이 모델명을 그대로 반복한 것뿐이면 실제 규격근거로 인정하지 않고 B다.
- 검색 규격이 존재하지만 후보에서 모두 확인되지 않으면 B.
- A는 제조사·모델뿐 아니라 실제 규격 토큰까지 확인된 경우에만 허용한다.
- 모델 유사도나 편집거리만으로 A/B를 만들지 않는다.
- D는 자동 유사제품 추천 결과가 아니라 curated functional-alternative 관계가 있을 때만 허용한다.
- 판단근거는 `match_note`에 `model`, `manufacturer`, `specification`, `product_class` 상태로 남긴다.
- **제품군 자동 호환성은 정규화 후 exact equality만 인정한다.** 단순 substring/부분문자열 포함관계는
  동일 제품군 근거로 인정하지 않는다. 상하위 제품군·동의어 관계가 필요하면 문자열 포함이 아니라
  별도의 검증된 alias/ontology registry를 사용한다.
  - `query_key == candidate_key` → `product_class=compatible`. C 후보가 될 수 있다.
  - 한쪽이 다른 쪽을 포함하기만 하면 → `product_class=related_unverified`. C 요건을 충족하지 않으며,
    사람이 near miss를 확인할 수 있도록 상태값만 남긴다.
  - 그 외 → `product_class=different`.
  - 근거: `모니터`⊂`심전도모니터`, `프린터`⊂`레이저프린터`처럼 접미사만 공유하는 라벨은 더 좁거나
    아예 다른 제품군인 경우가 많다. 실제 live G2B 표본에서도 `인공호흡기` 검색에 대해
    `융복합인공호흡기` 후보가 관찰됐다. 모델을 지정하지 않은 검색에서 이런 후보가 참고용 C로
    승격되면 구매담당자에게 잘못된 비교대상이 제시된다.
  - `product_class`는 C 분기에서만 사용하므로 이 규칙은 A/B 판정에 영향을 주지 않는다. 예를 들어
    `컬러 레이저프린터` 검색과 `레이저프린터` 후보는 exact model 경로로 계속 A가 된다.
- 실제 G2B 제목의 선행 괄호 한정어(`(VN)NT960XHA-KG71G`, `(주문자상표부착)삼성전자`)는 토큰과 분리해
  `model_qualifier` / `manufacturer_qualifier`로 보존한다. 의미를 추정하지 않는다.
  - 한정어를 제거해야 모델이 일치하면 `model=exact_with_unverified_qualifier`로 표시하고 **X**로 둔다.
    conflict가 아니라 사람 검토 대상이라는 뜻이다. 공개 근거로 한정어 의미(예: 원산지)가 확인되기 전에는
    A/B로 승격하지 않는다.
  - 한정어를 제거해야 제조사가 일치하면 `manufacturer=alias_with_unverified_qualifier`로 표시하고
    제조사 근거 부족과 같게 취급해 최대 **B**까지만 허용한다.

이 기준은 A를 넓게 만드는 것보다 **잘못된 직접 비교가격이 가격범위에 들어오는 것을 막는 것**을 우선한다.

## 제조사 alias

`data/manufacturer_aliases.csv`는 검증 가능한 표기 차이만 등록한다.

예:

- `삼성전자` / `Samsung` / `Samsung Electronics`
- `Stephan` / `Fritz Stephan`
- `Draeger` / `Dräger` / `드레거`

새 alias를 추가할 때는 서로 다른 제조사를 한 canonical name으로 합치지 않는다.

## G2B title parsing

F1 live 응답에서 관찰된 다음 구조만 보수적으로 파싱한다. 2026-07-14~08-13 live 표본의 삼성 노트북
7건은 모두 `(VN)`/`(CN)` 모델 한정어를 갖고 있었고, 2건은 제조사에 `(주문자상표부착)` 한정어가 있었다.
한정어를 토큰에 포함한 채 비교하면 검색대상 모델 자체가 `model=conflict`로 판정되어 실제 A/B 양성이
구조적으로 나올 수 없으므로, 한정어는 분리해서 보존한다.

```text
제품군, 제조사, 모델, 사양...
```

예:

```text
인공호흡기, 조선기기, CSI-2000, 운반형
```

파싱 결과:

- 제품군: `인공호흡기`
- 제조사: `조선기기`
- 모델: `CSI-2000`
- 사양: `운반형`

쉼표 구성요소가 3개 미만이면 제조사/모델을 추정하지 않는다.

## G2B candidate search 연결

F1에서 검증된 세부품명 매핑으로 나라장터 이력을 가져온 후:

1. 모델/제조사 토큰으로 후보를 좁힌다.
2. 가격 `EvidenceType`을 F1 parser로 확정한다.
3. G2B title에서 제품 identity를 파싱한다.
4. F3 matcher가 A/B/C/D/X를 부여한다.
5. A/B이면서 직접가격 `EvidenceType`인 경우에만 가격범위 계산 대상이 된다.

즉 `가격이 실제 납품단가인가?`와 `우리 제품과 같은가?` 두 조건을 독립적으로 통과해야 한다.

## Benchmark 평가

`data/phase0_match_ground_truth.csv`에 사람이 검토한 공개 원문 후보를 기록한다.

필드:

- `benchmark_model`
- `source_name`
- `source_record_id`
- `candidate_title`
- `expected_grade`
- `review_note`
- `evidence_url`

실행:

```bash
python -m purchase_price.scripts.evaluate_match_benchmark --fail-on-mismatch --output artifacts/match-benchmark-predictions.csv
```

Ground truth가 비어 있으면 성능값을 추정하지 않고 `rows=0`, precision/recall을 `N/A`로 출력한다.
A/B 양성 행이 없으면 `direct_positive_rows=0`과 함께 precision/recall을 `N/A`로 둔다.

- `--fail-on-mismatch`: 사람 판정과 다른 등급이 하나라도 있으면 exit 1. CI는 이 옵션으로 실행하므로
  matcher 규칙 변경이 기존 사람 판정을 깨면 PR이 실패한다.
- `--output`: 행별 `expected_grade`/`predicted_grade`/`match_note`를 CSV로 남겨 판정 근거를 재현 가능하게
  보관한다. CI는 이를 artifact로 업로드한다.

평가에서는 두 지표군을 분리한다.

### 1. Exact grade accuracy

A/B/C/D/X 등급 자체가 사람 판정과 정확히 일치하는 비율.

### 2. Direct-match precision / recall

A/B를 `직접가격 후보`라는 하나의 양성 클래스처럼 본다.

- Precision: 시스템이 A/B라고 한 것 중 실제 A/B 비율
- Recall: 실제 A/B 중 시스템이 A/B로 찾은 비율

구매가격 검토에서는 잘못된 가격을 직접 비교군에 넣는 것이 특히 위험하므로 **precision을 우선 보호**한다.

## 실제 G2B exact-model 탐색 (F3.1)

단일 거대 기간 호출 대신 날짜 창(window) 단위로 나누어 verified 분류 전체를 페이지 끝까지 조회한다.

```bash
python -m purchase_price.scripts.scan_g2b_exact_model_candidates \
  --begin-date 20260101 --end-date 20260831 --chunk-days 31 --max-pages-per-chunk 20 \
  --summary-output artifacts/g2b-exact-model-scan-summary.csv \
  --candidates-output artifacts/g2b-exact-model-candidates.csv
```

- 창마다 `status=complete|incomplete`, `pages_fetched`, `records_seen`, `reported_total_count`,
  후보 수와 등급 분포를 요약 CSV에 남긴다. 안전상한이나 API 오류로 끝까지 읽지 못한 창은
  `incomplete`로 기록하고 스캔은 계속하되, 마지막에 exit 1로 끝난다. 부분 결과를 완전 스캔으로
  오인하지 않기 위해서다.
- 후보 CSV는 **거래가 아니라 identity(정규화된 제목) 단위**로 1행이다. `transaction_count`,
  첫/마지막 거래일, 최소/최대 단가, `source_record_ids`를 같이 남겨 반복 납품이 표본을 지배하지
  않도록 한다.
- 후보는 검색 모델 토큰이 제목에 포함된 레코드만이며, 등급은 F3 matcher 결과 그대로다.
  `exact_with_unverified_qualifier`(X)인 행이 실제 A/B 양성 후보의 1차 검토 대상이다.
- GitHub Actions `G2B Ground Truth Capture` workflow를 `mode=scan`으로 수동 실행하면 같은 결과를
  artifact로 받는다. 이 workflow는 push로 자동 실행되지 않는다.

## 현재 미검증/후속

- 20개 benchmark 전체의 사람이 검토한 candidate ground truth는 아직 구축 중이다.
- 실제 benchmark precision/recall은 아직 산출하지 않았다. 데이터가 없으므로 숫자를 만들지 않는다.
- G2B 외 제조사/유통/계약 Source는 source별 title/field parser가 추가로 필요하다.
- 규격 비교는 현재 token presence 기반의 보수적 1차 규칙이며, 용량/전압/패키지/옵션처럼 의미 단위의 충돌 판정은 후속 확장 대상이다.
- `Sophie` 등 특정 benchmark에 대한 실제 나라장터 동일모델 A/B 레코드 존재 여부는 별도 live 조사로 검증해야 한다. synthetic test fixture를 실제 근거로 간주하지 않는다.
- 2026-07-14~08-13 구간 전체 스캔(run 33765916042)에서 Sophie(9건), NT960XJG-K72AG(1,021건) 모두 exact 모델 토큰 후보 0건이었다. 현재 Ground Truth 10건은 전부 X이므로 direct precision/recall은 N/A다.
- `(VN)`/`(CN)` 같은 모델 한정어의 업무적 의미는 공개 문서로 확인하지 않았다. 확인되면 `exact_with_unverified_qualifier`를 B로 승격하는 규칙을 별도 PR에서 검토한다.
- 더 넓은 기간의 window 스캔은 `DATA_GO_KR_SERVICE_KEY`가 있는 환경에서 workflow 수동 실행이 필요하며, 이 저장소 작업환경에서는 아직 실행하지 않았다.
