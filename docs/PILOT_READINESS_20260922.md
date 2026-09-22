# 관리부 시장가격조사기 파일럿 준비상태 — 2026-09-22

## 결론

현재 Production은 **관리부 내부 파일럿 실사용 가능** 상태다.

- Production: https://bp-price-research.streamlit.app/
- 공개 PoC이므로 병원명, 담당자, 연락처, 비공개 계약조건, 실제 내부 구매단가 등은 업로드하지 않는다.
- 가격 근거는 `DIRECT A/B`와 Research-only 근거를 구분해 사용한다.
- Research-only 근거는 적정가격 판정에 자동 승격하지 않는다.

## 검색 품질 게이트

### Curated UAT

PR #197 기준 30개 curated 검색 케이스를 사용한다.

- DIRECT A/B: 18
- BROAD_REFERENCE: 10
- external-Research ZERO: 1 (ROTAPRO)
- expected negative: 1
- unexpected delivery-index ZERO: 0

### Observed-model regression

Production R2에서 서로 다른 조달 세부품명 위주로 24개 모델을 자동 표본화한다.

- direct A/B recovery: 24/24
- exact sampled source row recovery: 24/24
- curated 30 + observed 24 = 총 54개 검색 UAT

### ROTAPRO

- verified mapping: 혈관강박리카테터장치 / `4220341801`
- Track B 납품요구 serving row: 0
- 따라서 delivery-index ZERO 자체는 matcher 결함으로 보지 않는다.
- live G2B Research UAT에서 사전규격 2건을 확인해 `RESEARCH_RESCUED` 처리한다.
- 입찰/낙찰/사전규격 중 일부 source 실패는 artifact에 별도 경고로 남긴다.
- 외부 Research 결과는 직접 거래단가로 자동 승격하지 않는다.

## 데이터 수집

- historical target snapshot: 5,208 codes
- historical backfill: 5,208/5,208 완료
- fixed historical window: 2025-09-12 ~ 2026-09-11
- rolling refresh: 첫 순환 진행 중
- base rolling schedule: 월/수/금 03:10 KST
- supplemental schedule: 월요일 04:40 KST
- weekly R2 search-quality UAT: 월요일 05:30 KST
- Serving Index는 collection 완료 후 자동 동기화한다.

첫 rolling 순환이 완료되기 전에는 2026-09-12 이후 모든 대상 코드가 동일한 최신성으로 갱신됐다고 간주하지 않는다.

## 실사용 원칙

1. 가능하면 `품명 + 제조사 + 모델명`을 함께 입력한다.
2. DIRECT A/B만 동일제품 직접 비교가격으로 본다.
3. `동일 모델 미확정`, `동일 제조사·동일 세부품명`, `동일 세부품명`, `키워드 참고`는 Research-only다.
4. 가격 범위가 지나치게 넓으면 개별 행의 모델·규격·수량·VAT·설치/옵션 조건을 확인한다.
5. 검색 0건은 바로 데이터 누락으로 단정하지 않고 delivery index / external Research / mapping 상태를 구분한다.

## 아직 사람 검증이 필요한 항목

### 실제 견적서 UAT release gate

다음 5개 전략은 비식별 실제 견적 표본의 담당자 원문 대조가 필요하다.

- pdf_commercial
- pdf_ocr
- pdf_text
- xls
- xlsx

이 항목은 합성 fixture나 자동 테스트만으로 완료 처리하지 않는다.

실사용 중 받은 실제 견적은 병원/업체/담당자/연락처/내부가격 등 민감정보를 제거한 사본으로 UAT에 사용한다.

## 알려진 제한

- MinION Mk1D: G2B exact-looking 거래 5건이 있으나 `(GB)` qualifier 의미가 공식적으로 확인되지 않아 Research-only 유지.
- ROTAPRO: 납품요구 DB에는 거래행이 없고 현재 사전규격/입찰 Research로 보완.
- 일부 세부품명은 동일 모델 거래가 없어서 동일 제조사/동일 세부품명 또는 동일 세부품명 참고만 제공한다.
- 공개 Streamlit PoC는 병원 내부 비공개 데이터 저장소로 사용하지 않는다.

## 실사용 피드백 처리

실사용 중 아래 유형을 발견하면 재현 조건과 함께 별도 수정 대상으로 관리한다.

- 검색했는데 분명한 동일 모델 거래가 누락됨
- 다른 모델이 동일 모델로 오탐됨
- 가격 단위/수량/총액이 이상함
- 제조사 alias가 잘못 매칭됨
- 참고가격 범위가 지나치게 넓거나 무의미함
- 견적 OCR이 품명/모델/가격/VAT/상업조건을 잘못 추출함
- 페이지 오류/느림/휴면/Secrets/R2 runtime 문제

각 이슈는 재현 가능한 케이스를 UAT에 추가한 뒤 수정한다.
