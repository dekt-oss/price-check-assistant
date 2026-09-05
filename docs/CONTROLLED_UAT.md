# Controlled UAT 프로토콜

기준일: 2026-09-05

## 1. 목적

이 UAT의 목적은 기능이 존재하는지 다시 확인하는 것이 아니다.

다음 두 질문을 실제 구매검토 관점에서 검증한다.

1. **잘못된 제품/가격을 직접 비교하는 false positive를 충분히 막는가?**
2. **그 보수성 때문에 실제 비교 가능한 근거를 지나치게 버리는 false negative가 어느 정도인가?**

추가로 수작업 시장조사 대비 시간이 실제로 줄어드는지 측정한다.

## 2. 데이터 경계

Public PoC UAT에 허용:

- 시스템용으로 직접 만든 샘플 견적
- 비식별 견적
- 외부 공개 또는 사용승인이 명확한 테스트 문서
- 공개 제품명/모델/규격

금지:

- 본원 실제 구매단가
- 실제 거래업체별 계약단가
- 내부 결재문서
- 개인정보
- 병원 내부 계약서/견적 원본
- API secret

업로드 원본은 영구 저장하지 않는다. 저장소에는 UAT 결과의 비식별 요약만 남긴다.

## 3. 최소 UAT 케이스

| Case | 유형 | 핵심 검증 |
|---|---|---|
| UAT-01 | 일반 전산제품 / 정확 모델 | exact identity, G2B/공식가격 Evidence |
| UAT-02 | 일반 전산제품 / 부정확 제품명 | 모델증거가 없을 때 과승격하지 않는지 |
| UAT-03 | 병원 일반 비품 | 의료기기 외 일반 구매품 흐름 |
| UAT-04 | 의료장비 / exact MFDS identity | 식약처 identity + 경쟁장비 + 공급사 |
| UAT-05 | 다품목 Excel | 여러 행 추출, 행별 identity/가격검색 |
| UAT-06 | text PDF | PDF 추출 정확도와 fail-closed |
| UAT-07 | 상업조건 상세 견적 | VAT/배송/설치/옵션/보증/유지보수 추출 |
| UAT-08 | 상업조건 거의 없음 | unknown을 조건 없음으로 오인하지 않는지 |
| UAT-09 | exact 모델 + 외부가격 부족 | 근거부족/산정불가 처리 |
| UAT-10 | 명백한 규격 충돌 | X 처리 및 직접가격 제외 |
| UAT-11 | 동일 모델 + 거래수량 차이 | 현재 quantity equality의 false negative 여부 |
| UAT-12 | API 정상 0건 | 실패와 구분되는지 |
| UAT-13 | API 실패 | 0건으로 덮지 않는지 |
| UAT-14 | MFDS ambiguous permit | 자동 identity 연결 금지 |
| UAT-15 | 취소/취하/수출전용 의료기기 | 국내 신규구매 후보 자동승격 금지 |

## 4. 케이스별 기록값

`data/uat/controlled_uat_template.csv`에 다음을 기록한다.

### 입력/표본

- `case_id`
- `sample_class`
- `input_format`
- `sample_name`
- `approved_public_sample`

### 추출

- `extraction_status`
- `human_product_name`
- `system_product_name`
- `human_manufacturer`
- `system_manufacturer`
- `human_model`
- `system_model`
- `human_spec`
- `system_spec`

### Identity

- `human_match_grade`
- `system_match_grade`
- `identity_agreement`
- `false_positive_identity`
- `false_negative_identity`

### 공개가격

- `direct_evidence_found`
- `direct_evidence_count`
- `independent_source_count`
- `observed_low_krw`
- `observed_high_krw`
- `quote_position`

### 조건/비교가능성

- `condition_human_judgment`
- `condition_system_judgment`
- `condition_agreement`
- `candidate_gate_result`
- `candidate_gate_reasons`
- `false_positive_comparison`
- `false_negative_comparison`

### API / provenance

- `collector_status`
- `zero_vs_failure_correct`
- `source_record_traceable`
- `source_url_traceable`
- `fingerprint_traceable`

### 업무효과

- `manual_minutes`
- `system_minutes`
- `time_saved_minutes`
- `reuse_value_1_to_5`
- `reviewer_notes`

## 5. 사람 Ground Truth 판정 순서

시스템 결과를 보기 전에 가능한 범위에서 사람이 먼저 다음을 판정한다.

1. 견적/제품의 제조사·모델·규격
2. 기대 MatchGrade
3. 외부 Evidence가 동일제품 직접가격인지
4. VAT·수량/단위·배송·설치·옵션·보증·유지보수의 실제 관계
5. 이 quote/evidence pair가 직접 고저비교 가능한지

이후 시스템 결과와 대조한다.

시스템 결과를 먼저 본 뒤 사람이 그대로 따라 적으면 UAT가 아니라 자기확인 테스트가 된다.

## 6. False positive / false negative 정의

### Identity false positive

사람 판정이 C/D/X 또는 식별불충분인데 시스템이 A/B로 판정하여 직접가격 후보로 사용할 수 있게 한 경우.

**Blocker 후보**다.

### Identity false negative

사람 판정은 A/B인데 시스템이 C/X로 보류한 경우.

업무불편이지만 false positive보다 우선순위는 낮다.

### Comparison false positive

견적과 외부근거의 중요한 거래조건이 다르거나 미확인인데 직접 고저비교가 허용된 경우.

**Blocker 후보**다.

### Comparison false negative

사람이 원문을 확인했을 때 직접 단가비교가 가능하지만 candidate gate가 보류한 경우.

수량 equality 등 규칙완화 검토의 근거가 된다.

## 7. 후보 게이트 완화 조건

현재 규칙을 UAT 전에 완화하지 않는다.

특히 수량 equality는 아래가 확인될 때만 별도 설계한다.

- 동일 모델·동일 단위
- 단가 자체가 명시됨
- 가격이 총액 나눗셈으로 생성된 값이 아님
- 수량 차이 외 핵심 상업조건이 일치 또는 담당자 확인됨
- 여러 UAT 케이스에서 같은 사유로 false negative가 반복됨

그 경우에도 자동승격이 아니라 **담당자 승인형 pair-level workflow**를 우선한다.

## 8. 합격 기준

초기 Controlled UAT의 목표값은 시장 성능을 과장하지 않도록 다음처럼 둔다.

### 안전성

- Identity false positive: **0건 목표**
- Comparison false positive: **0건 목표**
- API failure를 0건으로 표시: **0건**
- X/C/D가 직접가격 범위에 혼입: **0건**
- 계약총액이 제품단가로 혼입: **0건**

하나라도 발생하면 해당 경로는 release blocker 후보로 분류한다.

### 기능성

고정 합격률을 미리 만들지 않는다. source coverage는 품목군에 따라 구조적으로 다르므로 다음을 실측 보고한다.

- 추출 성공률
- A/B 사람판정 일치율
- 직접가격 Evidence 확보율
- candidate gate 통과율
- false negative 사유 분포
- provenance 재검증률
- 중앙값 시간절감
- 재사용 가치 평균

## 9. 결과 보고

UAT 종료 시 최소 다음을 보고한다.

```text
표본 수
추출 성공률
identity agreement
identity FP / FN
직접가격 Evidence 확보율
comparison FP / FN
candidate 보류 사유 Top N
API failure/zero 구분 오류
provenance 재검증 가능률
수동 조사 중앙시간
시스템 중앙시간
중앙 시간절감
재사용 가치 평균
```

표본이 적으면 비율만 단독으로 강조하지 않고 반드시 분자/분모를 같이 표시한다.

## 10. deterministic offline pre-UAT

`purchase_price.scripts.run_controlled_uat`는 실제 업무 UAT 전에 안전계약의 주요 경로를 반복 검증하는 **deterministic pre-UAT**다.

CI에서는 다음처럼 실행한다.

```bash
python -m purchase_price.scripts.run_controlled_uat \
  --fail-on-blocker \
  --output-dir artifacts/controlled-uat-offline
```

현재 자동화 범위는 15개 프로토콜 케이스 중 12개다.

자동 실행:

- UAT-01~03
- UAT-05~13

실제 MFDS 공식 API/Production live 표본이 필요한 다음 3개는 offline runner가 성공으로 꾸미지 않고 `NOT_RUN_LIVE_REQUIRED`로 남긴다.

- UAT-04 exact MFDS identity
- UAT-14 ambiguous permit
- UAT-15 취소/취하/수출전용 상태

CI artifact:

- `controlled-uat-results.csv`
- `controlled-uat-summary.json`

### 이 결과를 실제 UAT와 혼동하지 않는다

offline runner의 사람판정은 시스템 계약을 검증하기 위해 사전에 고정한 synthetic ground truth다. 따라서 다음을 증명하지 않는다.

- 실제 병원/공급사 견적 양식의 추출 성공률
- 실제 시장에서의 source coverage
- 실제 업무시간 절감
- 실제 담당자 재사용 가치
- 실제 MFDS/G2B live availability

특히 UAT-11은 `동일 모델 + 동일 단위 + 명시 단가 + 수량만 차이`인 synthetic pair를 의도적으로 만들어 현재 quantity equality가 **comparison false negative 1건**을 만드는지 감시한다. 이는 보수성 신호이지, 규칙을 즉시 완화하라는 근거가 아니다.

## 11. 현재 상태

2026-09-05 기준:

- 프로토콜/기록양식: 구축
- deterministic offline pre-UAT: 구현 진행
- 실제 승인된 샘플/비식별 문서를 이용한 업무 UAT: **미검증**
- Production G2B/MFDS/UDI live smoke: **별도 검증 필요**

실제 샘플을 실행하지 않은 항목은 계속 `미검증`으로 유지한다.
