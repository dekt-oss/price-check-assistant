# Phase 0 최종 검증 보고서

작성일: 2026-09-04

## 1. 결론

Phase 0는 **종료**한다.

최종 판정은 **Adjust → Phase 1 진행**이다.

공개정보만으로 모든 병원 구매품목의 적정가격을 자동 산정하는 구조는 성립하지 않았다. 그러나 다음 핵심 가능성은 실제 데이터로 확인됐다.

- 조달청 G2B에서 세부품명 매핑과 exact model 식별이 되는 경우 실제 납품요구 단가를 직접가격 근거로 수집할 수 있다.
- 제조사 공식 공개가격을 독립 source로 연결할 수 있다.
- 동일 모델에서 G2B + 제조사 두 source를 동시에 확보하는 multi-source 사례가 실제로 재현됐다.
- 예산·기초금액과 실제 단가를 분리하고, A/B/C/D/X 제품 동일성 등급과 Evidence Type을 분리하는 fail-closed 계약이 동작한다.
- 공개 근거가 부족한 품목은 가격을 추정하지 않고 `근거부족`으로 종료할 수 있다.

따라서 Phase 1은 **범용 자동 가격판정**이 아니라, 공개 근거가 강한 표준화 모델 품목부터 지원범위를 확대하는 방향으로 진행한다.

---

## 2. 검증 기준선

### 코드 기준선

- Phase 0 finalization merge: `cfe46d0365c157588dea870cde9f0b8f66c73e89`
- main CI run: `33820371597`
- 결과: success
- Ruff: pass
- pytest: **107 passed**
- strict Match Ground Truth: pass
- Phase 0 offline integration: pass

### Match Ground Truth

CI 실측:

- rows: **11**
- exact grade accuracy: **100.0%**
- direct precision: **100.0%**
- direct recall: **100.0%**
- A/B direct positive rows: **1**

주의: direct positive가 1건뿐이므로 이 100%는 통계적 일반화 성능이 아니라 **현재 회귀테스트 계약이 정답셋과 일치한다는 의미**다.

### Live 검증

- workflow run: `33820748853`
- 기준기간: **2026-07-14 ~ 2026-08-13**
- API secret: GitHub Actions Secret 사용, 저장소/로그에 저장하지 않음
- live command: `run_phase0_validation`
- 결과: success

---

## 3. Live Phase 0 최종 지표

| 지표 | 결과 | 해석 |
|---|---:|---|
| Benchmark | 20 | Phase 0 기준셋 전체 |
| Mapping Readiness | **5/20 = 25.0%** | G2B 또는 제조사 공식가격 source에서 검증된 mapping/snapshot 보유 |
| Evaluation Coverage | **5/20 = 25.0%** | 최소 1개 source를 실제 성공 평가한 품목 |
| Source Hit | **5/6 = 83.3%** | 성공적으로 시도한 source-product 6쌍 중 5쌍에서 원천 record 존재 |
| Direct Evidence Product Rate | **2/5 = 40.0%** | 자동평가된 5개 품목 중 2개가 A/B + direct EvidenceType 확보 |
| Multi-source Product Rate | **1/5 = 20.0%** | C5570 1개가 독립 source 2개에서 usable evidence 확보 |
| Evidence Records | **5** | live validator가 유지한 정규화 evidence |
| Traceability | **5/5 = 100%** | 현재 v2 traceability 계약 충족 |
| Condition Completeness | **0/5 = 0%** | VAT·수량·단위·거래일·조건을 모두 구조화한 direct evidence 없음 |
| Collector Error Rate | **0/6 = 0%** | 고정기간 최종 live 실행에서는 collector error 없음 |
| Not Evaluated | **15/20** | 아직 source mapping/snapshot이 검증되지 않은 품목 |

### Source별 실측

#### 조달청 나라장터쇼핑몰 품목정보 서비스

- mapping ready: **4/20 = 20%**
- attempted/successful: **4/4**
- source hit: **3/4 = 75%**
- direct evidence product: **1/4 = 25%**
- evidence records: **3**
- traceability: **100%**
- condition completeness: **0%**
- errors: **0**

#### Manufacturer Public Catalog

- mapping ready: **2/20 = 10%**
- attempted/successful: **2/2**
- source hit: **2/2 = 100%**
- direct evidence product: **2/2 = 100%**
- evidence records: **2**
- traceability: **100%**
- condition completeness: **0%**
- errors: **0**

Manufacturer 지표는 현재 사람이 공식 페이지에서 검증한 snapshot 2건에 대한 값이다. 전체 제조사 웹 가격수집 성능으로 해석하면 안 된다.

---

## 4. 대표 실증 결과

### B18 — FUJIFILM ApeosPrint C5570 GK

Phase 0의 첫 자동 multi-source positive다.

**G2B**

- 세부품명: 레이저프린터 / `4321210501`
- exact model title 거래: 3건
- 납품요구 단가: **2,981,000원**
- source record IDs:
  - `R26TB02131898`
  - `R26TB02210520`
  - `R26TB02216148`
- MatchGrade: A
- EvidenceType: delivery order unit price

**제조사 공식몰**

- exact model: `ApeosPrint C5570 GK`
- 공개 판매가: **5,500,000원**
- MatchGrade: A
- EvidenceType: public sale price

따라서 관측 direct range는 **2,981,000 ~ 5,500,000원**이다.

이 범위는 적정가격·최저가격 판정이 아니다. 두 source의 거래/판매 조건이 동일하다고 증명되지 않았고 VAT·설치·배송·옵션·보증 조건이 완전히 구조화되지 않았으므로 **공개 관측범위**로만 사용한다.

### B13 — GMS GMSR-182

- 제조사 공식 공개 표시가격: **5,000,000원**
- exact model A direct evidence 확보
- G2B 세부품명 mapping은 미검증
- VAT·설치·배송 조건 미확인

### B17 — 삼성전자 NT960XJG-K72AG

수작업 Ground Truth에서는 국내 공개판매가 2개를 확보했다.

- 3,655,000원
- 3,699,000원

반면 고정기간 G2B live에서는 노트북컴퓨터 source record 1,021건이 있었지만 exact model candidate는 유지되지 않았다.

즉 **제품이 공개시장에는 있어도 특정 공공조달 기간에 exact model 거래가 없을 수 있다**는 점이 확인됐다.

### Sophie / ThinkStation

- Sophie: G2B 분류 record 9건 source hit, exact-model 직접가격은 없음
- ThinkStation P2 Tower: mapping은 verified이나 고정기간 G2B source hit 0건

이를 가격 0원이나 시장가격 부재로 해석하지 않는다. 단지 해당 검증 source/window에서 직접근거가 없었다는 의미다.

---

## 5. 20개 benchmark 종료 판정

상세는 `data/phase0_case_outcomes.csv`를 Source of Truth로 한다.

요약:

- **직접가격 근거 확보:** 3개
  - GMSR-182
  - NT960XJG-K72AG
  - ApeosPrint C5570 GK
- **제품 식별·참고·source hit은 가능하나 직접가격 부족:** 9개
- **현재 검증된 공개 source로 근거부족:** 8개

여기서 `근거부족`은 가격이 존재하지 않는다는 판정이 아니다. **Phase 0에서 검증한 공개 source/mapping만으로 신뢰 가능한 direct evidence를 만들지 못했다**는 판정이다.

---

## 6. 무엇이 되는가 / 어려운가

### 공개정보 기반 자동화에 상대적으로 적합

- 모델번호가 명확한 IT·사무기기
- 조달 세부품명과 모델 identity가 연결되는 표준화 제품
- 제조사가 숫자 판매가를 공식 공개하는 장비·비품
- 동일 모델을 여러 source에서 식별할 수 있는 품목

### 공개정보만으로 직접가격 자동화가 어려움

- 옵션·구성에 따라 가격이 크게 달라지는 고가 의료장비
- 제조사가 문의견적 방식만 제공하는 장비
- 모델보다 사업/패키지/서비스 계약 단위로 거래되는 품목
- G2B 표준 세부품명은 알 수 있으나 exact model 거래가 드문 품목
- 제조사/모델 식별 자체가 불완전한 수술기구

진료재료·진료소모품은 기존 결정대로 Phase 0 범위에서 제외했다.

---

## 7. Phase 1 우선순위

### 1순위 — G2B Shopping / 납품요구

현재 실제 live 데이터와 direct price positive를 확보했다. 세부품명 mapping registry를 확대하고, exact model search·pagination·retry·raw evidence 보존을 강화한다.

### 2순위 — 제조사 공식 공개가격

현재 snapshot adapter를 production-like source로 발전시킨다.

필수 후속:
- freshness/재검증 정책
- 가격 변경 감지
- VAT·배송·설치·옵션·보증 조건 구조화
- 공식 URL provenance 유지

### 3순위 — G2B 계약정보서비스

다음 신규 collector로 구현한다.

목적:
- 쇼핑몰/납품요구에 없는 실제 계약정보 보강
- 계약총액·수량·단가 관계 확인
- 공고/계약번호 기반 provenance 연결

일반 유통 공개가격은 보조 source 후보로 유지하되 사이트별 이용조건·가격조건·안정성을 검토한 뒤 확대한다.

---

## 8. Phase 0 종료 시 남기는 제한

1. **Coverage 25%**이므로 공개정보만으로 전 품목 자동가격검토가 된다고 결론내리지 않는다.
2. Condition Completeness가 **0%**이므로 VAT/설치/배송/옵션/보증을 반영한 최종 적정가격 판정은 아직 금지한다.
3. Match Ground Truth positive가 1건뿐이므로 100% precision/recall을 일반 성능지표로 사용하지 않는다.
4. 제조사 source는 현재 검증 snapshot 방식이며 범용 크롤러가 아니다.
5. G2B mapping 미검증 품목은 source miss로 계산하지 않는다.
6. 내부 본원 단가·실제 견적서·계약자료는 Public PoC에 포함하지 않는다.
7. 근거가 부족하면 계속 `비교근거 부족`을 반환하며 시장가격을 생성하지 않는다.

---

## 9. 최종 의사결정

**Phase 0: 완료**  
**판정: Adjust → Phase 1 진행**

Phase 1의 목표는 20개 benchmark 점수를 인위적으로 높이는 것이 아니라, 이번에 실제로 성립한 수집·동일성·Evidence Type·traceability 계약을 유지한 채 **공개 직접가격을 안정적으로 확보할 수 있는 품목군과 source를 확장**하는 것이다.
