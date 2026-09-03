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

이 기준은 A를 넓게 만드는 것보다 **잘못된 직접 비교가격이 가격범위에 들어오는 것을 막는 것**을 우선한다.

## 제조사 alias

`data/manufacturer_aliases.csv`는 검증 가능한 표기 차이만 등록한다.

예:

- `삼성전자` / `Samsung` / `Samsung Electronics`
- `Stephan` / `Fritz Stephan`
- `Draeger` / `Dräger` / `드레거`

새 alias를 추가할 때는 서로 다른 제조사를 한 canonical name으로 합치지 않는다.

## G2B title parsing

F1 live 응답에서 관찰된 다음 구조만 보수적으로 파싱한다.

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
python -m purchase_price.scripts.evaluate_match_benchmark
```

Ground truth가 비어 있으면 성능값을 추정하지 않고 `rows=0`, precision/recall을 `N/A`로 출력한다.

평가에서는 두 지표군을 분리한다.

### 1. Exact grade accuracy

A/B/C/D/X 등급 자체가 사람 판정과 정확히 일치하는 비율.

### 2. Direct-match precision / recall

A/B를 `직접가격 후보`라는 하나의 양성 클래스처럼 본다.

- Precision: 시스템이 A/B라고 한 것 중 실제 A/B 비율
- Recall: 실제 A/B 중 시스템이 A/B로 찾은 비율

구매가격 검토에서는 잘못된 가격을 직접 비교군에 넣는 것이 특히 위험하므로 **precision을 우선 보호**한다.

## 현재 미검증/후속

- 20개 benchmark 전체의 사람이 검토한 candidate ground truth는 아직 구축 중이다.
- 실제 benchmark precision/recall은 아직 산출하지 않았다. 데이터가 없으므로 숫자를 만들지 않는다.
- G2B 외 제조사/유통/계약 Source는 source별 title/field parser가 추가로 필요하다.
- 규격 비교는 현재 token presence 기반의 보수적 1차 규칙이며, 용량/전압/패키지/옵션처럼 의미 단위의 충돌 판정은 후속 확장 대상이다.
- `Sophie` 등 특정 benchmark에 대한 실제 나라장터 동일모델 A/B 레코드 존재 여부는 별도 live 조사로 검증해야 한다. synthetic test fixture를 실제 근거로 간주하지 않는다.
