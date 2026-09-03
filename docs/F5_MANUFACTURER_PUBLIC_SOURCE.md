# F5 — 제조사 공식 공개가격 source v0

## 목적

나라장터 외에도 제조사가 공식 웹페이지에서 직접 공개한 판매·견적가격을 근거로 사용할 수 있게 한다.

F5 v0는 범용 웹 크롤러가 아니다. **공식 제조사 페이지에서 사람이 검증한 가격 snapshot을 URL·검증일과 함께 등록**하고, 기존 F3 제품 동일성 계약으로 A/B/C/X를 판정하는 보수적 adapter다.

## 첫 검증 근거

### GMSR-182

- 제조사: GMS / (주)지엠에스
- 제품: Medical Refrigerator / 약품냉장고
- 모델: `GMSR-182`
- 규격: `182L`
- 공식 제품 페이지: `https://www.gsmedical.co.kr/product/gmsr-182/`
- 공식 구매견적문의: `https://www.gsmedical.co.kr/estimate/`
- 공개 표시가격: `5,000,000 KRW`
- 검증일: `2026-09-04`

공식 견적 페이지에서 VAT·배송·설치 포함 여부는 확인되지 않았다. 따라서 normalized evidence에서도 이를 임의로 채우지 않는다.

## 구현 계약

`data/public_manufacturer_prices.csv`가 사람이 검증한 source registry다.

필수 식별·추적 필드:

- manufacturer
- product_name
- model_name
- price
- currency
- source_name
- source_url
- verified_at
- source_record_id

`ManufacturerPublicCatalogCollector`는 각 row를 `PUBLIC_SALE_PRICE` + `MANUFACTURER` evidence로 변환한다.

제품 동일성은 별도 규칙을 만들지 않고 F3 `grade_product_identity()`를 재사용한다.

- exact model + manufacturer + informative spec compatible → A
- exact model이나 일부 조건 부족 → B
- 제품군 참고만 가능 → C
- 모델/제조사 충돌 → X, 검색 결과에서 제외

## 제품 identity 정규화

공식 페이지 확인을 반영해 Phase 0 benchmark의 다음 값을 정규화한다.

- `GMSR-182`: 제조사 `SGM` → `GMS`
- `C5570`: 제조사 미상 → `FUJIFILM Business Innovation`

`C5570`은 제조사 공식 페이지에서 `ApeosPrint C5570`, A3 컬러, 55ppm 프린터임을 확인했고 국가법령정보센터의 조달 세부품명표에서 `레이저프린터 / 4321210501`을 확인했다. 따라서 G2B mapping을 verified로 올리되 live API source-hit은 별도로 미검증 상태로 남긴다.

F5 branch 기준 G2B Mapping Readiness는 `4/20 = 20%`다.

## 제한사항

1. v0는 실시간 웹 크롤링이 아니라 검증된 snapshot registry다.
2. 가격 변경 여부는 아직 자동 갱신하지 않는다.
3. 제조사 페이지에 없는 VAT·배송·설치·보증 조건은 추정하지 않는다.
4. 제조사 공식가격이 있다는 이유만으로 적정가격 또는 최저가격으로 판단하지 않는다.
5. F4 일괄 validation에는 아직 이 source를 독립 source-product 평가로 연결하지 않는다. source별 mapping/readiness 분모 계약을 추가한 뒤 통합한다.

## 다음 단계

1. GMSR-182을 실제 통합검색 UI에서 직접가격 evidence로 노출
2. 공개가격 snapshot의 freshness 정책 정의
3. 추가 제조사 공식 공개가격 확보
4. F4에 source별 readiness를 도입해 G2B + Manufacturer multi-source 평가 활성화
