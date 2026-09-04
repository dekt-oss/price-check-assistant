# 견적서 파일 분석 MVP

## 목적

사용자가 견적서 파일을 업로드하면 품목 식별정보와 견적단가를 구조적으로 추출하고,
담당자가 추출값을 확인·수정한 뒤 기존 공개가격 검색/매칭/가격평가 엔진에 연결한다.

흐름은 다음과 같다.

```text
견적서 업로드
→ 파일 구조 파싱
→ 품목/제조사/모델/규격/수량/단가 추출
→ 담당자 확인·수정
→ ProductQuery 생성
→ Manufacturer/G2B collector 검색
→ A/B/C/D/X 동일성 판정
→ observed price range 계산
→ 품목별 비교표 + 원문 근거 표시
```

## 이번 MVP 범위

### XLSX

`.xlsx` 파일은 `openpyxl`로 직접 읽는다.

첫 30행에서 다음 헤더 alias를 찾는다.

- 품목: 품명 / 제품명 / 상품명 / 물품명 / 품목명 / 내역
- 제조사: 제조사 / 제조업체 / 메이커 / Maker / 브랜드 / Brand
- 모델: 모델 / 모델명 / Model / Model No 등
- 규격: 규격 / 사양 / Spec / Specification
- 수량: 수량 / Qty / Quantity
- 단가: 단가 / 견적단가 / 공급단가 / 판매단가 / Unit Price / Price
- 금액: 금액 / 합계금액 / 공급가액 / 총액 / Amount / Total

품목 식별 열이 하나 이상 있고 단가 또는 금액 열이 있는 행을 header 후보로 인정한다.

합계/총계/소계/VAT 행은 품목으로 자동 추출하지 않는다.
가격이 전혀 없는 행도 자동 품목으로 확정하지 않는다.

## 사람 확인 게이트

파일 파싱 결과를 곧바로 외부가격 검색에 사용하지 않는다.

Streamlit `data_editor`에서 담당자가 다음을 확인·수정한 뒤 검색한다.

- 제품명
- 제조사
- 모델명
- 규격
- 수량
- 견적단가
- 총액

이 단계는 문서 레이아웃 차이 또는 셀 병합 때문에 잘못 읽힌 값을 사람이 교정하기 위한 안전 게이트다.

## 기존 가격엔진과의 연결

수정된 한 행은 기존 `ProductQuery`로 변환한다.

별도의 느슨한 견적서 전용 matcher를 만들지 않는다.

- 기존 Manufacturer public catalog 사용
- 환경키가 있으면 verified G2B search 사용
- 기존 A/B/C/D/X 제품동일성 계약 재사용
- 기존 EvidenceType/ComparisonScope 사용
- 기존 `assess_prices()` 사용

따라서 파일에서 모델명이 추출됐다는 사실 자체는 제품 동일성 증거가 아니다.
외부 Evidence와 F3 matcher가 다시 검증한다.

## 가격 안전계약

견적서에 단가가 있어도 외부 근거가 `observed_only`이면 견적의 높고 낮음을 판정하지 않는다.

VAT·배송·설치·옵션·보증 등 조건이 `quote_comparable`로 검증되어야만
현재 견적의 범위 내/상단 초과/하단 미만 판정을 허용한다.

## 파일 보안

업로드된 원본 견적서는 임시파일로만 처리하고 영구 저장하지 않는다.

공개 PoC에서는 실제 본원 내부 견적서를 저장소/DB에 적재하지 않는다.
실제 내부자료 사용은 별도 승인 및 내부환경 이식 이후다.

## 아직 지원하지 않는 것

### PDF

PDF 업로드 UI는 유지하지만 자동 추출은 아직 하지 않는다.
다음 단계에서 text-based PDF extraction을 추가한다.

스캔 이미지 PDF는 OCR을 자동 기본경로로 사용하지 않는다.
OCR은 정확도/보안/비용 검토 후 최후 수단으로 둔다.

### XLS

구형 `.xls` 자동 추출은 현재 지원하지 않는다.

### AI 자동추출

AI가 원문에서 임의로 모델명/가격을 추정하는 기능은 이번 MVP에 포함하지 않는다.
결정적 구조 파싱 → 사람 확인을 먼저 검증한 뒤 보조수단으로 검토한다.

## 다음 검증

1. 실제와 유사한 비식별 XLSX 견적서 fixture 3~5종으로 header alias coverage 확인
2. Streamlit 실제 렌더에서 편집 → 다품목 검색 → 근거표 흐름 smoke test
3. text PDF parser 추가
4. column mapping을 사용자가 직접 지정하는 fallback UI 추가
5. 실제 업무용 템플릿이 정해지면 template-specific parser를 generic parser보다 우선 적용
