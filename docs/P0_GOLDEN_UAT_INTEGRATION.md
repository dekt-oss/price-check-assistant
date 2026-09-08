# P0 Golden UAT Integration

이 브랜치는 P0 개별 PR을 `main`에 조기 merge하지 않고 APC-30D / FLOW-C Golden UAT를 실행하기 위한 통합 검증 브랜치다.

## 포함 계약

- P0-02: 후속 조회가 실제로 실행되지 않은 경우 `NOT_RUN`과 정상 0건을 분리한다.
- P0-03: `FLOW-C`를 `FLOW-C20` 또는 accessory/부속품과 동일모델로 취급하지 않는다. 옵션 identity와 보증기간 차이를 보존한다.
- P0-04: 공식 10자리 세부품명 resolver 후보는 Research recall에만 사용하고 verified mapping으로 자동 승격하지 않는다.
- P0-05: 공식 코드 또는 현재 resolver 후보 중 사용자가 명시적으로 선택한 코드만 Shopping 표적 Research에 사용할 수 있다.
- P0-06: 계약 Research는 공고 연결 + 독립 품명검색과 단계적 lookback을 분리하며 총액을 단가로 파생하지 않는다.
- P0-07: 기관·공급사·품목식별번호·라인·원문규격·납품조건 등 raw provenance를 보존하되 Evidence 승격 근거로 사용하지 않는다.

## Golden cases

### APC-30D

- 견적: ASTEC / APC-30D / `CO₂ Incubator(Water Jacket)` / 8,000,000원
- `CO₂`는 `CO2`로 의미보존 정규화하며 `CO`로 손실하지 않는다.
- `Water Jacket`은 분류 identity가 아니라 specification clue로 보존한다.
- `4110449801`은 CO₂ 배양기 관련 공식 세부품명번호의 표적 Research fixture이며 APC-30D 동일제품 mapping으로 자동 승격하지 않는다.
- APC-30D 문자열이 확인되지 않은 관련 배양기 가격은 동일모델 가격 band로 승격하지 않는다.

### FLOW-C

- 견적: Maquet / FLOW-C / 가스 마취기 / 66,000,000원
- FLOW-C20, accessory, 부속품은 FLOW-C 동일모델 후보에서 제외한다.
- vaporizer/옵션 identity와 보증기간이 다르면 `충돌`, 한쪽만 상세값이 있으면 `미확인`이다.
- 관련 Maquet 제품, 경쟁제품, 동일 분류 제품을 동일모델 가격과 분리한다.

## 판정 의미

Live workflow의 `pass`는 현재 조회된 자료에서 P0 identity/amount safety 위반이 없었다는 뜻이다. 제품 구성 동등성의 완전한 입증을 뜻하지 않는다. 외부 API 인증/transport 실패는 `0건`으로 바꾸지 않고 별도 상태로 보고한다.

P1 fingerprint 작업은 Golden UAT 결과를 확인한 뒤 진행한다.
