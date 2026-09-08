# P0-07 Raw Procurement Provenance Contract

P0-07은 조달 Research 원자료를 P1 제품/구성 fingerprint의 입력으로 보존하기 위한 단계다. **필드가 채워졌다는 사실만으로 제품 identity, 규격 동등성, 가격 Evidence 자격을 승격하지 않는다.**

## 보존 필드

`G2BResearchRecord`에서 가능한 source는 다음 원자료를 보존한다.

- `institution`
- `supplier`
- `product_id`
- `detail_product_code`
- `item_sequence`
- `original_specification`
- `quantity`
- `unit`
- `amount` + `amount_type`
- `original_amount_text`
- `delivery_condition`
- `record_change_order`
- `source_url`

Shopping Research 후보도 가능한 동일 계열의 기관·공급업체·수량·단위·라인·원문규격·납품조건·변경차수를 유지한다.

## Identity / dedupe

- 같은 공고나 계약 안의 서로 다른 품목은 `item_sequence`와 `product_id`를 가능한 한 source record identity에 포함해 서로 덮어쓰지 않는다.
- 8자리 `prdctClsfcNo`는 10자리 `dtilPrdctClsfcNo`와 다른 의미이므로 세부품명번호로 대체 저장하지 않는다.
- 값이 없는 경우 추정해서 채우지 않는다.

## Amount semantics

- 공고 구매대상 품목의 예정단가는 `ESTIMATED_UNIT_PRICE`다.
- 계약총액은 `CONTRACT_TOTAL`이다.
- 계약총액을 수량으로 나누어 단가를 파생하지 않는다.
- Raw provenance는 `CollectedPrice` 또는 `assess_prices()`로 자동 승격되지 않는다.

## 후속 P1에서의 사용

P1 fingerprint는 위 provenance와 별도 공식 규격/첨부 근거를 결합해 제조사·모델·구성·옵션·납품조건 관계를 판단한다. P0-07 자체는 APC-30D나 FLOW-C의 구성 동등성을 판정하지 않는다.
