# F7 — ApeosPrint C5570 GK 다중출처 직접가격 검증

## 목적

Phase 0에서 처음으로 동일한 exact model에 대해 서로 독립적인 두 공개 source가 A/B 직접가격 근거를 제공하는 사례를 만든다.

대상은 **FUJIFILM Business Innovation `ApeosPrint C5570 GK`**다.

## 공개 근거

### 1. 제조사 공식 공개판매가

FUJIFILM Business Innovation Korea 공식몰:

- 모델: `ApeosPrint C5570 GK`
- 표시 판매가: **5,500,000 KRW**
- 단위/최소구매단위: `1EA EA`
- URL: `https://store-fbkr.fujifilm.com/commerce/foffice/product/product.lime?r_prcode=APC5570PGK-W`
- 확인일: 2026-09-04

FUJIFILM 공식 MSDS 목록도 `ApeosPrint C5570`과 `ApeosPrint C5570 GK`를 별도 모델명으로 명시한다.

- `https://www.fujifilm.com/fbkr/ko/products/msds-search`
- `https://www.fujifilm.com/fb/en/support/sds-and-ais/printers/color/apeosprint-c5570-c4570`

### 2. G2B 실제 납품요구 단가

Phase 0 G2B diagnostics run:

- Actions run: `https://github.com/dekt-oss/price-check-assistant/actions/runs/33817222249`
- 검색기간: 2026-07-14 ~ 2026-08-13
- 세부품명: 레이저프린터 / `4321210501`
- 전체 record: 750건
- exact-title transaction: 3건
- title: `레이저프린터, Fujifilm, (CN)ApeosPrint C5570 GK, A3, 55ppm/55ppm`
- 납품요구 단가: **2,981,000 KRW**
- 확인된 source record IDs:
  - `R26TB02131898`
  - `R26TB02210520`
  - `R26TB02216148`

세 거래의 관측 단가는 동일했지만, 이를 일반 시장 최저가나 상시 조달가격으로 해석하지 않는다.

## `(CN)` / `(VN)` 처리 계약

기존 matcher는 모델 앞의 모든 괄호 qualifier를 의미 미검증 상태로 두고 A/B 승격을 차단했다. 이는 안전한 기본값이지만 실제 G2B 품목명에서는 `(CN)` / `(VN)`이 모델명이 아니라 **상품원산지국가명**을 품목명 앞에 병기하는 형식임을 공식 G2B 상세화면에서 확인했다.

공식 G2B 예시:

- 중국(CN) 원산지 필드와 `(CN)` 모델 전치 표기:
  `https://goods.g2b.go.kr/search/productSearchView.do?goodsClsfcNo=4010180802&goodsIdntfcNo=26420508`
- 베트남(VN) 원산지 필드와 `(VN)` 전치 표기:
  `https://goods.g2b.go.kr/search/productSearchView.do?goodsClsfcNo=4213150401&goodsIdntfcNo=25658430`

따라서 F7은 **오직 `CN`, `VN` 두 값만** 검증된 origin metadata whitelist로 취급한다.

- exact model + `(CN)`/`(VN)` → 모델 동일성은 유지
- 다른 qualifier → 기존처럼 `exact_with_unverified_qualifier`, X 유지
- qualifier 뒤 모델 자체가 다르면 → `conflict`, X 유지
- `(주문자상표부착)` 같은 manufacturer qualifier는 별도 의미이므로 기존 보수적 B cap을 유지

즉 qualifier를 일반적으로 제거하는 규칙이 아니다.

## 예상 직접가격 범위

동일 모델의 현재 확보 근거:

| source | evidence | observed price | identity grade |
|---|---|---:|---|
| G2B 납품요구 | delivery order unit price | 2,981,000 KRW | A |
| FUJIFILM 공식몰 | public sale price | 5,500,000 KRW | A |

따라서 두 source가 모두 검증되는 실행에서는 direct reference range가 **2,981,000 ~ 5,500,000 KRW**가 된다.

이 범위는 두 공개 근거의 관측 범위일 뿐 적정가격 판정 자체가 아니다. 조달 납품조건과 제조사 온라인 판매조건은 동일하지 않을 수 있다.

## 확인되지 않은 조건

다음은 자동으로 채우지 않는다.

- VAT 포함 여부
- 설치 포함 여부
- 현장 인도 조건
- 옵션/소모품 포함 여부
- 보증·유지보수 범위

제조사 공식몰은 배송 안내와 최소구매단위를 공개하지만, 해당 가격의 VAT/설치 조건을 현재 근거만으로 확정하지 않는다.

## 검증 Gate

F7 merge 전 다음을 모두 확인한다.

1. Ruff 통과
2. 전체 pytest 통과
3. Ground Truth의 신규 C5570 row가 A로 정확히 재현
4. Ground Truth direct precision/recall이 실제 positive row를 포함해 계산됨
5. Phase 0 offline validation에서 제조사 snapshot 2건이 정상 평가됨
6. merge 후 live Phase 0에서 C5570 G2B A evidence가 실제 재현됨
7. G2B + 제조사 두 source가 같은 C5570 benchmark에서 usable direct evidence를 만들어 Multi-source가 활성화됨

6~7이 확인되지 않으면 코드/CI 성공만으로 실제 multi-source 완성으로 간주하지 않는다.
