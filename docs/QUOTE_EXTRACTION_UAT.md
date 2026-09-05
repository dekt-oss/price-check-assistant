# 견적 추출 UAT 프로토콜

## 목적

견적서 parser의 완료 여부를 synthetic test만으로 판단하지 않는다. 실제 관리부 견적 파일을 담당자가 원문과 대조한 ground truth와 비교해 **추출 실패율과 필드 오류율을 측정**한다.

기획상 1차 완료 기준은 실제 견적 **5건 이상 처리 + 추출 오류율 확인**이다.

## 보안 원칙

- 실제 견적 PDF/Excel과 ground-truth manifest는 repository에 commit하지 않는다.
- 업체 담당자 이름, 연락처 등 개인정보는 UAT 전에 제거한다.
- 비밀유지 조항이 있는 견적은 승인된 로컬 환경에서만 검증한다.
- UAT output에는 제품명, 업체명, 단가, 총액 등 원문 값을 기록하지 않는다.
- output은 case ID, 추출 전략, 건수, 오류 필드명, 오류율만 기록한다.

## 준비

`data/uat/quote_extraction_uat_template.csv`를 repository 밖의 작업 디렉터리로 복사한다.

한 행은 한 개의 기대 품목을 뜻한다. 한 견적서에 품목이 여러 개면 같은 `case_id`와 `file_path`를 사용하고 `item_index`를 1, 2, 3... 순서로 추가한다.

필수 열:

- `case_id`
- `file_path`
- `item_index`
- `product_name`
- `manufacturer`
- `model_name`
- `specification`
- `quantity`
- `unit_price`
- `total_amount`

빈 expected field는 해당 필드 정확도 계산에서 제외한다. 실제 원문에 존재하는 필드는 가능한 한 ground truth에 채운다.

## 권장 5건 구성

최소 5건을 서로 다른 layout으로 선정한다.

1. 표 선이 있는 텍스트 PDF
2. 표 선이 없고 열 정렬만 있는 텍스트 PDF
3. 제품명/규격이 여러 줄로 접히는 텍스트 PDF
4. 다페이지 PDF — 가격표와 제조사·모델·VAT·보증 조건이 다른 페이지에 있음
5. Excel(.xlsx 또는 .xls)

가능하면 품목 수 1개짜리와 복수 품목 견적을 섞는다.

## 실행

```bash
python -m purchase_price.scripts.run_quote_extraction_uat \
  --manifest /secure/quote_uat_manifest.csv \
  --root /secure/quote_uat_files \
  --output-dir /secure/quote_uat_output \
  --min-cases 5
```

엄격 모드가 필요하면 `--fail-on-errors`를 추가한다. 이 옵션은 추출 실패 또는 scored field 오류가 1건이라도 있으면 non-zero exit를 반환한다. 현재 단계에서는 오류율을 먼저 측정하는 것이 목적이므로 CI release gate로 자동 승격하지 않는다.

## 산출물

- `quote-extraction-uat-results.csv`
- `quote-extraction-uat-summary.json`

case별 결과는 다음만 포함한다.

- PASS / REVIEW_REQUIRED / EXTRACTION_FAILED
- expected / actual 품목 수
- 사용된 parser 전략
- scored field 수
- field error 수
- 오류가 발생한 필드명

실제 제품명·업체명·가격은 output에 쓰지 않는다.

## 핵심 지표

- `extraction_failure_rate`
- `exact_item_count_rate`
- `field_error_rate`
- parser 전략별 처리 건수

`field_error_rate`는 ground truth에 값이 입력된 필드만 분모로 사용한다.

## 판정 원칙

- CI unit test PASS를 실제 UAT PASS로 간주하지 않는다.
- 5건 미만이면 기획상 UAT 완료로 표시하지 않는다.
- 오류율이 확인되기 전에는 OCR/비전을 추가한 효과를 주장하지 않는다.
- OCR/비전 도입 후에도 동일 manifest를 재실행해 전후 오류율을 비교한다.
- 자동 추출 결과는 담당자가 원문과 대조한 뒤 사용한다.
