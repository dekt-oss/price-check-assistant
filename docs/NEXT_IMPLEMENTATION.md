# 다음 구현 순서

기준: 2026-09-05 `main` (`37c9c29c0fa8eb1efd530dd18e7d895aa07ab1ed`).

현재 핵심 엔진은 기능 추가 단계보다 **실제 live 검증 + 실제 견적 UAT**가 우선인 상태다. 일반 CI와 synthetic fixture가 통과했다는 사실을 실제 병원/공급사 견적이나 외부 API의 운영 성공으로 해석하지 않는다.

## 현재 main 반영 완료

- G2B Shopping/납품 verified exact-model 검색
- G2B 계약정보 근거 조회
- G2B 계약정보 public provenance allow-list + canonical JSON + SHA-256 fingerprint
- A/B/C/D/X fail-closed 매칭 + 핵심 숫자·단위 규격충돌 차단
- 외부 가격조건 구조화
- 견적서 상업조건 추출
- 견적조건 ↔ 외부조건 `match/conflict/unknown` comparator
- quote comparability **candidate** gate
- 현재 session의 quote/evidence pair에 대한 명시적 `QUOTE_COMPARABLE` 승인 workflow
- evidence freshness
- 출처별 성공 N건 / 정상 0건 / 실패 상태 분리
- Excel `.xlsx/.xls` + text PDF 구조추출
- 스캔 PDF 로컬 OCR (`pypdfium2` + Tesseract `kor+eng`)
- 실제 image-only synthetic PDF → Tesseract → production parser E2E CI
- MFDS 품목/형명 exact identity, 경쟁장비, 업허가 업체, 공급사 우선순위
- UDI-DI known-value exact 조회
- Safety 수동 공식확인 경로와 상태계약
- Controlled UAT deterministic offline gate: 15개 중 12개 자동 PASS, 3개 live-required
- Streamlit 전체 페이지 startup smoke
- G2B/MFDS live workflow의 shared key fallback
  - source-specific → `DATA_GO_KR_MARKET_SERVICE_KEY` → legacy `DATA_GO_KR_SERVICE_KEY`

상세 상태는 `docs/V2_IMPLEMENTATION_STATUS.md`, live 실행법은 `docs/LIVE_UAT_RUNBOOK.md`를 기준으로 한다.

---

## P1. 실제 Live smoke

일반 GitHub CI와 분리한다. 외부 API workflow는 `workflow_dispatch` 수동 실행만 허용한다.

### 확인 대상

1. G2B Shopping live smoke
2. G2B verified mapping/Phase 0 live validation
3. MFDS 품목/모델 exact identity
4. MFDS 업체조회
5. UDI-DI known-value exact lookup
6. Production Streamlit 대표제품 검색
7. Production Streamlit text PDF / scan PDF 업로드

### 반드시 구분할 상태

- `성공 N건`
- `정상 0건`
- `실패`
- `미검증`

API 0건을 실패로 바꾸지 않고, 실패를 0건으로 숨기지도 않는다. GitHub Actions 성공 자체는 Production Streamlit 성공을 의미하지 않는다.

### 현재 미검증 경계

- 현재 shared key를 이용한 최신 G2B/MFDS workflow의 실제 live 호출
- Streamlit Community Cloud에서 Tesseract `kor+eng` 실제 실행
- 최신 main의 Production 브라우저 동작

Secret 값은 로그·artifact·문서에 기록하지 않는다.

---

## P2. 실제 견적 UAT — 최소 5건부터 시작

현재 가장 중요한 업무 검증이다. 실제 본원/공급사 원문은 Public repo에 커밋하지 않는다.

`pages/13_견적추출_UAT.py`에서 여러 견적을 올리고 담당자가 원문을 직접 대조한다. 원본과 수정된 정답값은 영구 저장하지 않고, 다운로드 결과에는 비식별 통계만 포함한다.

### 최소 표본

가능하면 서로 다른 업체/양식으로 최소 5건:

1. `.xlsx` 다품목 견적
2. `.xls` 또는 다른 Excel 양식
3. text-layer PDF
4. 스캔 PDF/OCR
5. 조건이 상세하거나 다페이지인 실제 견적

표본 수가 늘어나면 일반 전산제품·병원 비품·의료장비를 분리해 본다.

### 측정값

- extraction success/failure
- extraction strategy
- parser 처리시간
- 담당자 원문대조 시간
- expected / actual / matched item 수
- 품목 false positive(FP)
- 품목 false negative(FN)
- item precision / recall
- 제조사/모델/규격/수량/단위/단가/총액/VAT 필드 오류율
- OCR vs text PDF vs Excel 전략별 성능
- 실제 업무 재사용 가치

한 품목의 추가/누락 때문에 뒤 행 전체가 오류로 계산되지 않도록 UAT 비교는 순서보존 alignment를 사용한다. 이 alignment는 **UAT 측정용**이며 생산 제품 identity/가격판정 규칙을 변경하지 않는다.

### 개인정보/내부정보 경계

Public repo에 저장하지 않음:

- 실제 견적 원본
- 실제 파일명
- 제품/업체/모델의 실제 정답값
- 내부 구매단가
- 실제 견적 단가/총액
- 병원 내부정보

비식별 UAT JSON에는 케이스 ID, 추출전략, 개수·오류수·비율·시간만 남긴다.

---

## P3. 전체 구매검토 UAT

견적 parser 자체가 안정되면 end-to-end 업무 흐름을 검증한다.

```text
견적/제품 입력
→ 제품 identity
→ 공개 직접가격 Evidence
→ 견적조건 ↔ 외부조건 대조
→ candidate gate
→ 담당자 원문/조건 확인
→ 현재 session pair 명시적 승인
→ QUOTE_COMPARABLE
→ assess_prices
→ 현재 견적 위치
```

### 반드시 측정

- A/B/C/D/X 사람판정 일치
- 잘못된 직접비교 FP
- 비교 가능한데 보류되는 FN
- 조건 `match/conflict/unknown` 사람판정 일치
- candidate gate 통과/보류 사유
- 승인 취소/재승인 동작
- source URL / evidence ID / fingerprint 재검증 가능 여부
- 공개 직접가격 Evidence 확보율
- 수작업 대비 검토시간

### 수량 equality

현재 candidate gate의 수량 equality는 계속 유지한다.

Synthetic UAT-11에서 quantity mismatch로 알려진 comparison FN 1건이 존재하지만, **이 한 건만으로 규칙을 완화하지 않는다.** 실제 업무 UAT에서 비교 가능한 사례가 반복적으로 막히는지 확인한 뒤 별도 설계 변경으로 검토한다.

---

## P4. UAT 발견 결함 보정

실제 UAT에서 확인된 오류를 우선순위로 수정한다.

우선순위:

1. 잘못된 직접비교 FP
2. 잘못된 identity 확정
3. 가격/수량/단위 오추출
4. API failure/0건 혼동
5. OCR 누락/오인
6. 조건 comparator 오판
7. 반복되는 보수적 FN

정확도를 높인다는 이유로 fail-closed 계약을 임의 완화하지 않는다.

---

## P5. Source coverage 확대

실제 UAT에서 **가격근거 확보율이 업무 병목**이라는 것이 확인된 뒤 진행한다.

우선순위:

1. 제조사 공식 공개가격
2. 검증 가능한 공공계약
3. 신뢰 가능한 B2B/유통 source
4. 일반 웹은 후보 탐색 보조

금지:

- 검색결과 snippet 가격 자동채택
- 비공식 리셀러를 공식가격으로 승격
- 환율 환산값을 KRW 직접 관측가격으로 취급
- 문의가격 추정
- 모델군 가격을 exact 모델가격으로 사용
- 계약총액을 제품 단가로 환산

G2B mapping 숫자 자체를 성과목표로 삼지 않는다.

---

## 외부 계약 확보 후 구현

### Safety RED 자동조회

식약처 회수·판매중지정보의 공식 operation/request parameter를 확보한 뒤에만 구현한다.

- exact 모델/허가번호 matching
- hit 시 가격정보보다 우선하는 RED 경고
- 0건과 API 실패 분리
- `검색결과 없음 = 안전` 표현 금지
- 자동 구매중단 판단 금지

### 모델명 → UDI/상세 identity

공식 모델 검색 request contract가 확보되면 구현한다. 현재는 UDI-DI를 알고 있는 경우의 exact 조회만 자동화되어 있다.

---

## P6. 최종 single-screen UI

실제 UAT 결과를 반영한 뒤 진행한다.

```text
구매검토 1화면
├─ 직접 검색
└─ 견적서 업로드
      ↓
핵심판정
→ identity / Safety
→ 가격근거
→ 견적조건/비교
→ 경쟁장비/공급사
→ 상세 provenance
```

다품목 견적은 master-detail을 유지한다. 기존 개발/검증용 분리 페이지는 parity, AppTest, Production smoke를 통과한 뒤 사용자 navigation에서 정리한다.

---

## P7. 내부 이식

Public PoC의 업무효과가 실제 UAT에서 확인되고 내부 승인을 받은 뒤 진행한다.

- 본원 구매단가 Excel import부터 검토
- PostgreSQL에 내부 observation 별도 축적
- ERP 직접연계는 후순위
- 진료재료/간납단가는 내부 단가 활용 승인 이후 별도 확장

---

## 현재 우선순위 요약

```text
actual live smoke
→ 실제 견적 최소 5건 UAT
→ 전체 구매검토 UAT
→ 실제 발견 결함 보정
→ 필요 시 source coverage 확대
→ single-screen UI
→ 내부 이식 검토
```

현재 목표는 기능 개수를 늘리는 것이 아니라 **잘못된 직접비교를 하지 않으면서 실제 구매검토 시간을 줄이는지 증명하는 것**이다.
