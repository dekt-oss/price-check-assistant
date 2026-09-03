# F5 — 제조사 공식 공개가격 source v0

## 목적

나라장터 외에도 제조사가 공식 웹페이지에서 직접 공개한 판매·견적가격을 근거로 사용할 수 있게 한다.

F5 v0는 범용 웹 크롤러가 아니다. **공식 제조사 페이지에서 사람이 검증한 가격 snapshot을 URL·검증일과 함께 등록**하고, 기존 F3 제품 동일성 계약으로 A/B/C/X를 판정하는 보수적 adapter다.

## 검증된 제조사 공개가격 snapshot

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

### ApeosPrint C5570 GK

- 제조사: FUJIFILM Business Innovation
- 제품: 컬러 레이저프린터
- 모델: `ApeosPrint C5570 GK`
- 규격: `A3, 55ppm`
- 공식몰: `https://store-fbkr.fujifilm.com/commerce/foffice/product/product.lime?r_prcode=APC5570PGK-W`
- 공개 표시가격: `5,500,000 KRW`
- 단위/최소구매단위: `1EA EA`
- 검증일: `2026-09-04`

FUJIFILM 공식 MSDS 목록도 `ApeosPrint C5570 GK` 모델명을 명시한다. VAT·설치 조건은 현재 공개 근거만으로 확정하지 않는다.

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

현재 collector는 KRW만 허용하고, NaN/Infinity/0 이하 가격을 거부한다. catalog는 lazy-load되어 잘못된 로컬 snapshot이 다른 collector 전체를 중단시키지 않는다.

`ManufacturerPublicCatalogCollector`는 각 row를 `PUBLIC_SALE_PRICE` + `MANUFACTURER` evidence로 변환한다.

제품 동일성은 별도 규칙을 만들지 않고 F3 `grade_product_identity()`를 재사용한다.

- exact model + manufacturer + informative spec compatible → A
- exact model이나 일부 조건 부족 → B
- 제품군 참고만 가능 → C
- 모델/제조사 충돌 → X, 검색 결과에서 제외

## 제품 identity 정규화

공식 공개 근거와 live G2B 진단을 반영해 Phase 0 benchmark의 다음 값을 정규화했다.

- `GMSR-182`: 제조사 `SGM` → `GMS`
- 초기 `C5570` 표기 → exact model `ApeosPrint C5570 GK`, 제조사 `FUJIFILM Business Innovation`

C5570 계열은 FUJIFILM 공식몰·MSDS에서 exact model을 확인했고, 조달 세부품명 `레이저프린터 / 4321210501`을 사용한 live G2B 진단에서 동일 모델 거래 3건을 확인했다. 다중출처 상세 계약은 `docs/F7_C5570_MULTISOURCE.md`를 따른다.

현재 G2B verified mapping은 4/20이며, 제조사 snapshot은 2개 benchmark에 존재한다. Aggregate Mapping Readiness는 source 중 하나라도 verified인 unique benchmark 기준으로 계산한다.

## 제한사항

1. v0는 실시간 웹 크롤링이 아니라 검증된 snapshot registry다.
2. 가격 변경 여부는 아직 자동 갱신하지 않는다.
3. 제조사 페이지에 없는 VAT·배송·설치·보증 조건은 추정하지 않는다.
4. 제조사 공식가격이 있다는 이유만으로 적정가격 또는 최저가격으로 판단하지 않는다.
5. 제조사와 조달가격이 같은 모델이라도 계약·배송·설치·옵션 조건 차이는 별도로 해석한다.

## 현재 후속 과제

1. 공개가격 snapshot freshness 정책 정의
2. 제조사 source를 추가 품목으로 확대
3. 동일 benchmark에서 G2B + Manufacturer 근거가 동시에 존재하는 사례 확장
4. VAT·설치·배송·옵션·보증 조건의 구조화 필드 확대
