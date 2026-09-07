# UAT — ExoAtlet-II 조달시장 Research fallback v1

- 대상: 병원 구매 시장가격조사기
- UAT 성격: **외부 공공조달 시장근거 탐색**
- 중요 운영 전제: **우리 병원은 나라장터를 이용해 자체 입찰을 수행하지 않는다.**
- 따라서 G2B 데이터는 내부 구매절차/발주 workflow가 아니라 **외부 시장가격·예산·규격·계약 근거를 조사하는 benchmark source**로만 사용한다.
- 실제 견적 PDF, 병원명, 공급사명은 공개 저장소에 커밋하지 않는다.

---

## 1. 제품소유자 확정 결정

### D7. 공식 분류번호가 없는 규격 유사 후보

공식 세부품명번호를 확보하지 못하더라도 규격/용도 유사도가 충분한 제품은 `대체후보` 또는 `규격 유사 후보`로 사용자에게 보여줄 수 있다.

단 다음 안전계약을 강제한다.

```text
공식 분류 code 미확인
+ 규격 유사도 높음
→ 후보 표에는 표시 가능
→ Alternative price band에는 포함 금지
→ Exact price band에는 포함 금지
→ assess_prices() 입력 금지
→ 자동 MatchGrade D 승격 금지
```

가격 숫자가 존재하더라도 후보 제품의 개별 참고가격으로만 표시하며, 집계 range/median을 만들지 않는다.

### D8. G2B의 역할

우리 병원은 나라장터를 자체 입찰 채널로 사용하지 않는다.

따라서 앱에서 G2B lifecycle(`사전규격 → 입찰 → 낙찰 → 계약`)은 다음 의미로만 사용한다.

- 타 기관의 구매사례 발견
- 유사 장비의 규격/수량/예산 확인
- 낙찰·계약 결과 추적
- 동일/유사 제품의 외부 시장 benchmark 생성

금지:

- 우리 병원의 발주/입찰 단계로 표현
- 우리 병원의 조달절차 완료 여부처럼 표시
- 나라장터 사용을 내부 구매 workflow의 전제로 요구

---

## 2. UAT 대상

실제 견적에서 추출되는 제품 식별자:

```text
엑소아틀레트 - II
```

테스트 목적은 exact model이 공공 조달 데이터에 없거나 희박한 현실적인 경우에도 Research가 멈추지 않는지 검증하는 것이다.

기대 경로:

```text
엑소아틀레트 - II
  ↓ exact model Research
없음/부족
  ↓
일반 제품명·용도 후보 생성
  ↓
로봇보조 정형용 운동장치 / 보행재활로봇 / 재활로봇 등
  ↓
물품목록정보 / 입찰 품목상세 / 사전규격에서 공식 품명·code 후보 탐색
  ↓
공식 code 확보?
  ├─ YES: 같은 code의 쇼핑몰·납품·계약·입찰 Research
  └─ NO: 규격 유사 후보 Research only
  ↓
타 기관 입찰 → 낙찰 → 계약 연결 가능한 건 추적
  ↓
Actual / Alternative / Budget / Context 분리 표시
```

---

## 3. Resolver source 우선순위

제품/품목 분류는 단일 API에 의존하지 않는다.

### R1 — Exact identity

1. exact model
2. manufacturer + model (제조사 확보 시)
3. 한글/영문 표기 alias

R1 hit은 여전히 strict identity gate를 별도로 통과해야 한다.

### R2 — Official catalog

`조달청_물품목록정보서비스`

목적:

- 물품식별번호
- 물품분류번호
- 세부품명분류번호
- 공식 품명/세부품명

모델 자체가 목록에 없더라도 상위/관련 공식 품목을 찾는 Resolver로 사용한다.

### R3 — Procurement inferred classification

물품목록에서 직접 resolution이 안 되면 다음에서 품목 분류 후보를 찾는다.

- 입찰공고 구매대상 품목상세
- 사전규격 품목/규격
- 계약정보 품명
- 계약과정통합공개 연결정보

공식 classification code가 API 응답으로 확인되면 `OFFICIAL_CLASS_CODE_EXACT` 후보가 될 수 있다.

### R4 — Generic/spec inferred category

R1~R3가 충분하지 않아도 Research는 종료하지 않는다.

- 견적 제품명
- 견적/첨부 규격
- 일반 한글 품명
- 용도
- 핵심 기능/성능

으로 넓은 후보를 탐색한다.

이 단계의 결과는 기본적으로 `SPEC_SIMILAR_REFERENCE_ONLY`이며 strict price band에 들어갈 수 없다.

---

## 4. 규격 유사 후보 계약

### 4.1 최소 비교축

가능한 항목만 비교하며, 없는 항목을 추정해서 채우지 않는다.

의료재활 장비의 초기 비교축:

- 임상/재활 용도
- 대상 신체부위
- 착용형/고정형 등 장비 형태
- 구동/보조 방식
- 환자 적용 범위
- 핵심 운동/보행 기능
- 안전/지원 기능
- 구성품
- 설치 요구
- 보증/서비스 조건

### 4.2 유사도 결과

초기 label:

- `SPEC_SIMILAR_HIGH`
- `SPEC_SIMILAR_MEDIUM`
- `SPEC_SIMILAR_LOW`
- `SPEC_INSUFFICIENT`

`HIGH`라도 공식 code가 없으면:

```text
Alternative candidate = 표시 가능
Alternative price band = 금지
```

### 4.3 자동판정 금지

단순 문자열 포함만으로 `SPEC_SIMILAR_HIGH`를 만들지 않는다.

예:

```text
재활로봇 ↔ 상지재활로봇
재활로봇 ↔ 보행재활로봇
```

은 명칭 일부가 같아도 용도/형태가 다를 수 있으므로 규격축 확인 없이 같은 대체군으로 묶지 않는다.

---

## 5. ExoAtlet UAT acceptance

### UAT-E1 — exact search가 없어도 종료하지 않음

- `엑소아틀레트 - II` exact 결과 0건이어도 전체 Research는 성공 상태를 유지한다.
- `0건`과 API 실패를 구분한다.

### UAT-E2 — 품목군 fallback

최소 2개 이상의 bounded generic/category query가 실행되어야 한다.

검색어는 trace로 사용자/테스트 결과에서 확인 가능해야 한다.

### UAT-E3 — official resolver

물품목록 또는 procurement item detail에서 공식 세부품명/code가 발견되면 provenance와 함께 저장한다.

미발견 자체는 UAT 실패가 아니다.

### UAT-E4 — spec-similar alternatives

공식 code가 없어도 규격 근거가 있는 유사 제품을 후보로 표시할 수 있다.

반드시:

- similarity basis 표시
- 미확인 항목 표시
- 개별 참고가격이 있으면 source와 함께 표시
- aggregate price band에서는 제외

### UAT-E5 — procurement lifecycle linkage

관련 입찰 건이 발견되면 가능한 범위에서:

```text
사전규격
→ 입찰공고
→ 낙찰
→ 계약
```

을 `bid notice no`, `prespec no`, `contract no` 등 공공 식별자로 연결한다.

연결 실패/미존재는 명시하며 억지로 join하지 않는다.

### UAT-E6 — Budget Estimate

유사 입찰의 금액을 단가 참고치로 사용할 때는 Budget Estimate strict gate를 적용한다.

- 단일품목
- item list 완전성
- 수량 명확
- package/SET ambiguity 없음
- 금액 귀속 명확

조건 미충족이면 `Procurement Context`로만 표시한다.

### UAT-E7 — 가격영역 격리

최종 화면에서 다음이 섞이지 않아야 한다.

1. 동일제품 실제가격
2. 공식 동일분류 경쟁제품 실제가격
3. 규격 유사 후보 개별 참고가격
4. 입찰 예산 참고가격
5. 조달 Context

특히 3번은 **price band를 만들지 않는다.**

### UAT-E8 — 내부 구매 workflow 오인 방지

UI 문구는 나라장터 기록을 `타 기관 공공조달 사례`, `외부 조달 참고자료` 등으로 표현한다.

`우리 병원 입찰`, `발주 진행`, `내부 조달상태`처럼 오인 가능한 문구를 사용하지 않는다.

---

## 6. 공개 저장소 fixture 원칙

실제 견적서는 테스트 fixture로 커밋하지 않는다.

대신 다음을 synthetic fixture로 재현한다.

- exact model 없음
- generic category hit 있음
- official code hit/미hit 두 경로
- high spec similarity지만 code 없음
- 입찰→낙찰→계약 연결 성공/실패
- 다품목 총액 때문에 Budget Estimate 차단

실제 ExoAtlet 문서는 Production/승인 UAT에서만 사용한다.

---

## 7. 구현 순서 반영

```text
P0-a Research auth/readiness     ← live 3/3 PASS 확인
P0-b request budget
P1-a 물품목록 Category Resolver
P1-b procurement inferred fallback
P1-c spec-similar candidate (band 제외)
P2 Budget Estimate
P3 5영역 UI + lifecycle provenance
```

`조달청_나라장터 계약과정통합공개서비스`는 내부 발주 workflow가 아니라 **타 기관 procurement lifecycle join 보조 source**로 사용한다.
