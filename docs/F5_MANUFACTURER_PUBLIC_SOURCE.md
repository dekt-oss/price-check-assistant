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

## 2026-09-04 제조사 공개가격 coverage 조사

Phase 1-C에서 G2B만으로 `evaluation_coverage`를 크게 높이기 어렵다는 것이 확인되어, 공개가격 가능성이 높은 benchmark부터 제조사 공식 source를 다시 조사했다.

이번 조사의 등록 기준은 기존 F5 계약보다 느슨하지 않다.

- benchmark와 exact model이 일치해야 한다.
- 가격은 제조사 공식 페이지에 직접 표시되어야 한다.
- 현재 catalog 계약상 `KRW` 가격만 등록한다.
- 가격이 `문의`, `Request a demo`, `Contact us`인 경우 등록하지 않는다.
- 시리즈/세대/CTO 모델이 benchmark와 다르면 같은 제품군으로 추정해 등록하지 않는다.

### 조사 결과

| benchmark | 공식 source 확인 결과 | registry | 이유 |
| --- | --- | --- | --- |
| Samsung `NT960XJG-K72AG` | 삼성전자서비스 공식 페이지에서 exact model 존재 확인 | 미등록 | 본체 공식 판매가격을 확인하지 못함. 서비스 소모품 가격을 본체 가격으로 사용할 수 없음 |
| Lenovo `ThinkStation P2 Tower` | Lenovo KR 공식몰에서 `ThinkStation P2 Tower Gen 2` CTO 가격과 VAT 포함 표시 확인 | 미등록 | benchmark는 `ThinkStation P2 Tower`; 공식 판매 row는 `Gen 2`로 exact model 문자열이 다름. benchmark identity를 별도 근거 없이 수정하지 않음 |
| Oxford Nanopore `MinION Mk1D` | 공식 Nanopore store에서 `MinION Mk1D` 단품 `US$3,150`, SKU/구성 공개 | 미등록 | exact model과 공식 가격은 확인했으나 현재 F5 catalog는 KRW 외 통화를 fail-closed 거부함 |
| Align Technology `iTero Lumina pro` | iTero 공식 사이트에서 `iTero Lumina Pro imaging system` 확인 | 미등록 | 공개 가격 없이 `Request demo`/문의 방식 |
| Thermo Fisher Scientific `Veriti Pro Dx` | 한국 공식 catalog에서 `VeritiPro Dx Thermal Cycler` 및 한국 대체 catalog 문의 안내 확인 | 미등록 | 한국 페이지에 KRW 판매가격 없음. 해외 공식몰 EUR 가격은 현재 KRW-only 계약 때문에 사용하지 않음 |
| Dräger `TN500` | 한국 공식 제품 페이지에서 `Babyleo TN500` exact 제품 및 `견적 요청` 확인 | 미등록 | 공개 판매가격 없음 |
| WIDE `CX30N` | 제조사 공식 제품 페이지에서 exact model/spec 확인 | 미등록 | 공개 판매가격 없음 |
| SNJ `N-Pulse Pro` | 국내 제품 페이지에서 exact model 확인 | 미등록 | 공개 판매가격 없음 |

### 확인한 공식 URL

- Samsung exact-model service identity: `https://www.samsungsvc.co.kr/download/view?code=NT960XJG-K72AG&prd1DepNm=PC%2F%EB%AA%A8%EB%8B%88%ED%84%B0&prd2DepNm=%EB%85%B8%ED%8A%B8%EB%B6%81%2F%EC%9C%88%EB%8F%84%EC%9A%B0+%ED%83%9C%EB%B8%94%EB%A6%BF`
- Lenovo KR official listing: `https://www.lenovo.com/buy/kr/ko/womens-day-deals-on-work-tower-desktops-with-windows-11-0acz00a`
- Oxford Nanopore official store: `https://store.nanoporetech.com/minion.html`
- Oxford Nanopore official price list: `https://store.nanoporetech.com/us/priceList.html`
- iTero official product site: `https://itero.com/`
- Thermo Fisher Korea catalog: `https://www.thermofisher.com/order/catalog/product/kr/ko/A57751`
- Dräger Korea TN500: `https://www.draeger.com/ko_kr/Products/Draeger-Babyleo-TN500`
- WIDE CX30N: `https://widecorp.homepage.whois.co.kr/?GC=GD0900&GS=126&act=shop.goods_view`
- N-Pulse Pro product page: `https://www.chungancorp.com/n-pulse`

### 결론

이번 조사에서 `data/public_manufacturer_prices.csv`에 안전하게 추가할 수 있는 신규 row는 **0건**이었다.

이는 실패가 아니라 F5의 false-positive 방지 계약이 정상적으로 작동한 결과다. 특히 아래 두 후보를 억지로 등록하지 않는 것이 중요하다.

1. **MinION Mk1D** — exact model + 공식가격까지 확인됐지만 `USD`다. 현재 KRW-only catalog 계약을 이 작업에서 완화하지 않는다.
2. **ThinkStation P2 Tower Gen 2** — KRW + VAT 포함 공식 가격이 있지만 benchmark의 exact model은 `ThinkStation P2 Tower`다. `Gen 2`를 substring/시리즈 동일성으로 자동 승격하지 않는다.

따라서 이 조사만으로 `mapping_readiness`나 `evaluation_coverage`가 오르지 않는 것이 기대 결과다.

## 제한사항

1. v0는 실시간 웹 크롤링이 아니라 검증된 snapshot registry다.
2. 가격 변경 여부는 아직 자동 갱신하지 않는다.
3. 제조사 페이지에 없는 VAT·배송·설치·보증 조건은 추정하지 않는다.
4. 제조사 공식가격이 있다는 이유만으로 적정가격 또는 최저가격으로 판단하지 않는다.
5. 제조사와 조달가격이 같은 모델이라도 계약·배송·설치·옵션 조건 차이는 별도로 해석한다.
6. 공식 해외 가격이 존재하더라도 현재 catalog는 KRW-only이므로 registry에 넣지 않는다.

## 현재 후속 과제

1. 공개가격 snapshot freshness 정책 정의
2. **비-KRW 공식 제조사 가격을 reference-only evidence로 보존할 별도 계약이 필요한지 설계 검토**
3. Lenovo `ThinkStation P2 Tower` benchmark가 실제 `Gen 2 / Ultra 7 265K` 구성인지 원 출처로 identity 재검증
4. 동일 benchmark에서 G2B + Manufacturer 근거가 동시에 존재하는 사례 확장
5. VAT·설치·배송·옵션·보증 조건의 구조화 필드 확대
