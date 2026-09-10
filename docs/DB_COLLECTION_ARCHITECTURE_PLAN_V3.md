# 구매시장정보 DB 수집체계 전환 기획서 v3

- 작성일: 2026-09-10
- Repository: `dekt-oss/price-check-assistant`
- 기준 `main`: `ba16650fddcd3785b1974804f6bd34a524d1dd42`
- 성격: 아키텍처·수집전략 확정안
- 상태: **Conditional Go — Feasibility Gate 통과 후 구현 확대**

---

## 1. 목적

현재 시스템은 사용자가 품목을 검색하거나 견적서를 업로드한 시점에 나라장터·식약처·공개자료를 실시간 조회하는 구조다.

v3의 목표는 시스템의 중심을 다음과 같이 전환하는 것이다.

```text
현재
사용자 입력 → 실시간 외부검색 → 제품 식별 → 가격/조달/안전정보

v3
외부 원천 → 지속 수집 → Raw/Normalize/Resolve/Evidence DB → 사용자 즉시 조회
                                               └→ 부족한 경우에만 live Research
```

핵심 원칙은 다음과 같다.

> **DB가 본체이고, 실시간 검색과 견적 OCR은 보완 수단이다.**

견적 OCR이 실패해도 사용자는 품명·모델 일부를 직접 입력하여 동일 DB를 조회할 수 있어야 한다.

---

## 2. 범위

### 2.1 1차 대상

- 의료장비
- 의료기구
- 의료비품
- 공기구비품
- 전산비품

### 2.2 조건부 대상

- 소프트웨어
- 의료장비 유지보수
- 장비 관련 서비스 계약

가격구조가 제품구매와 다른 라이선스·유지보수는 별도 Evidence Type 또는 별도 하위도메인으로 관리한다.

### 2.3 MVP 제외

- 진료재료·진료소모품·간납품목
- 웹 판매가 크롤링
- 입찰·낙찰·사전규격·계약 lifecycle 전수 DB화
- 규격서/HWP/PDF 첨부문서 다운로드·텍스트화
- MFDS 전수 열거
- 전문 검색엔진
- 병원 내부 비공개 구매데이터
- 5년 backfill
- AI 기반 자동 VERIFIED 승격

---

## 3. 리뷰 반영 결정

2026-09-10 아키텍처 리뷰의 핵심 결론을 다음과 같이 반영한다.

| 리뷰 제안 | 결정 | v3 반영 |
|---|---|---|
| 날짜 중심 전수수집 폐기 | 수용 | Track A/B/C 분리 |
| 변경차수·supersession 처리 | 수용 | 거래 record 상태로 별도 관리 |
| Product Master를 공식 식별번호 중심으로 | 수용 | `product_identity` 중심 |
| 텍스트 유사도 자동 VERIFIED 금지 | 수용 | 최대 `CANDIDATE` |
| `GENERIC_CLASS_ONLY` 추가 | 수용 | resolver 상태에 포함 |
| `SUPERSEDED`를 resolver 상태에 추가 | **수정 수용** | 제품식별 상태가 아니라 `record_status`로 분리 |
| 호스팅 Postgres + 배치 Collector + Streamlit read-only | 수용 | 배포 전제조건으로 상향 |
| `ON CONFLICT` idempotency | 수용 | P0 데이터계약 |
| Web 가격 MVP 포함 | 거절 | P2 이후 별도 검토 |
| 입찰·낙찰 lifecycle 즉시 적재 | 보류 | P2 |

---

## 4. 수집전략: 3-Track 구조

나라장터 API는 operation마다 조회 계약이 다르므로 하나의 범용 날짜 수집기로 추상화하지 않는다.

### Track A — 날짜 전용 납품요구상세

대상 operation:

- `getDlvrReqDtlInfoList`

특성:

- 검색어 없이 날짜만으로 조회 가능
- 단가계약 납품요구 line 수집
- 물품식별번호, 단가, 수량, 단위, 옵션구분, 기관·업체 식별정보 활용 가능
- 1개월 이하 기간창을 기본 계약으로 사용

역할:

> 의료비품·전산·소모성 비품 등 반복 거래의 대량 가격관측 기반

운영:

```text
초기: 월 단위 backfill
운영: 매일 최근 7일 sliding window 재조회
```

변경·지연등록을 흡수하기 위해 최근 구간을 반복 조회하며 stable key 기준 upsert 한다.

---

### Track B — 세부품명번호 × 기간 특정품목조달내역

대상 operation:

- `getSpcifyPrdlstPrcureInfoList`

특성:

- 날짜만으로 조회 불가
- **10자리 세부품명번호 또는 품명 검색조건이 필수**
- 병원 고가장비의 총액계약·납품요구 line 확보에 가장 중요한 원천
- 등록/변경일시가 없어 지연등록·변경차수 처리가 필수

수집축:

```text
10자리 세부품명번호 × 기간
```

따라서 Track B 실행 전에 조달 물품목록의 10자리 세부품명 사전을 확보해야 한다.

초기 대상 segment는 다음을 후보로 한다.

- 42: 의료기기·의료용품 계열
- 41: 실험·계측 계열
- 43: 전산·통신 계열
- 44: 사무기기·비품 계열
- 23/27: 공구·기계 계열
- 46: 안전 계열
- 39: 전기 계열

정확한 segment allow-list는 Pilot 결과로 확정한다.

**금지:** `기`, `의료` 같은 광역 부분일치 문자열로 전 산업 데이터를 긁어 Track B를 대체하지 않는다.

---

### Track C — 카탈로그 등록/변경 증분

대상:

- MAS 계약품목
- 3자단가 계약품목
- 일반단가 계약품목

역할:

- 제조사명
- 물품식별번호
- 규격명
- 계약단가
- VAT 구분
- 납기·납품조건
- 규격서 URL
- 인증정보
- 등록일/변경일

등을 Product Identity와 가격 원천으로 보강한다.

운영:

```text
초기: 등록일 기준 소급
운영: 변경일(chgDt) 기준 일일 증분
```

카탈로그 계약단가는 실제 특정 병원 납품단가와 동일 의미가 아니므로 별도 Evidence Type으로 유지한다.

---

## 5. 식약처(MFDS) 전략

식약처는 MVP에서 가격원천이 아니라 제품식별·규제·안전 원천으로 사용한다.

### MVP

- G2B에서 새 공식 제품 식별자가 발견되었을 때 on-demand 조회
- 제조/수입업체
- 허가/인증/신고정보
- 모델정보
- UDI-DI
- 회수·판매중지·안전성

### 원칙

- 같은 식약처 품목분류 = 동일제품 아님
- 같은 사용목적 = 동일제품 아님
- 모델 또는 공식 식별근거가 없으면 최대 `CANDIDATE`
- MFDS 전수수집 가능성은 별도 Feasibility Gate에서 확인 후 확장

---

## 6. 데이터 계층

```text
Collector
   ↓
Raw Source Record
   ↓
Normalize
   ↓
Delivery Line / Catalog Item
   ↓
Product Identity / Resolver
   ↓
Price Observation
   ↓
Serving Summary
```

각 단계의 책임을 섞지 않는다.

### Collector

- 외부 원천 호출
- pagination
- request budget
- 오류상태 분류
- cursor/window 관리
- 판단하지 않음

### Raw

- allow-list된 원천 payload 보존
- append-only
- lineage와 parser version 보존

### Normalize

- 원천 필드를 안정적 정규화 row로 변환
- 가격 숫자·수량·단위·날짜·변경차수 구조화
- 제품 동일성 판단 금지

### Resolve

- 공식 identity 연결
- alias 생성
- generic/class-only 분리
- 가격판정 금지

### Evidence

- 단가 근거가 명확한 row만 `price_observation` 생성
- 계약·입찰 총액을 나누어 단가 생성 금지

### Serving

- DB 검색
- 최근가격 분포
- freshness
- source lineage
- 부족한 경우 live Research

---

## 7. Product Master 설계 원칙

### 7.1 텍스트 중심 Master 금지

`manufacturer + product_name + model` 텍스트를 자연키로 사용하지 않는다.

### 7.2 공식 Identity 중심

```text
product_master            # 제품 cluster / 표시용 라벨
product_identity          # 공식·준공식 식별자
product_alias             # 원천별 명칭·모델 표기
resolver_decision         # 결합/보류/충돌 의사결정 이력
```

`product_identity.identity_system` 후보:

- `PPS_PRODUCT_ID`
- `MFDS_MODEL_SEQ`
- `UDI_DI`
- `MANUFACTURER_MODEL`

### 7.3 Resolver 상태

```text
VERIFIED_OFFICIAL_ID
VERIFIED_HUMAN
CANDIDATE
UNRESOLVED
CONFLICT
GENERIC_CLASS_ONLY
```

자동 `VERIFIED_OFFICIAL_ID`는 **공식 식별번호 동일성**에 의해서만 가능하다.

제조사 alias + 모델 exact 등은 `CANDIDATE`까지 허용한다.

### 7.4 거래 record 상태 분리

제품식별 상태와 변경차수 상태를 섞지 않는다.

```text
record_status:
ACTIVE
SUPERSEDED
CANCELLED
```

예:

```text
resolution_status = VERIFIED_OFFICIAL_ID
record_status = SUPERSEDED
```

가 동시에 가능해야 한다.

---

## 8. 가격 Observation 원칙

가격은 제품당 대표값 1개가 아니라 **관측 1건 = row 1개**로 저장한다.

주요 필드:

```text
price
quantity
unit
total_amount
transaction_date
institution
supplier
vat_status
delivery_condition
installation_condition
option_condition
warranty_condition
package_flag
evidence_type
comparison_scope
match_grade
source_record_id
raw_id
```

### 직접가격 후보

- 납품요구 명시 단가
- 특정품목 계약/납품 line의 명시 단가
- 쇼핑몰 계약단가

단, 서로 의미가 다르므로 Evidence Type은 분리한다.

### Research-only

- 입찰 총액
- 낙찰 총액
- 계약 총액
- 예정가격
- 사전규격 예산
- 다품목 일괄금액

**금지:** `총액 ÷ 수량`으로 제품단가 생성.

---

## 9. 변경차수 / supersession

Track A/B에서 동일 거래가 변경차수 `00 → 01 → 02`로 갱신될 수 있다.

정규화 line 자연키 예:

```text
(source_op, request_no, change_order, line_no)
```

같은 `(source_op, request_no, line_no)`에서 더 높은 change order가 등장하면:

- 이전 row 삭제 금지
- 이전 row `record_status=SUPERSEDED`
- `superseded_by` 연결
- 이전 row에서 파생된 observation은 `comparison_scope=EXCLUDE`
- 사유 저장

수집기는 최종차수만 필터링하지 않고 변경이력을 보존하는 방향을 기본으로 한다.

---

## 10. Raw / lineage / idempotency

### Raw

기존 `raw_evidence` 골격을 v3에 맞게 확장하거나 `raw_source_record`로 재정의한다.

권장:

- allow-list JSONB
- `source_op`
- `source_record_id`
- `stable_key`
- `payload_hash`
- `parser_version`
- `run_id`
- `fetched_at`

### Idempotency

SELECT 후 INSERT 방식에 의존하지 않는다.

```text
INSERT ... ON CONFLICT ... DO NOTHING/UPDATE
```

을 사용한다.

동일 기간을 반복 수집해도 정규화 row와 observation 수가 부풀지 않아야 한다.

### Lineage

```text
화면 가격
→ price_observation
→ normalized line
→ raw_source_record
→ collection_run
→ 원천 operation / 조회 window / source_record_id
```

를 역추적 가능하게 한다.

---

## 11. 수집 실행 상태

`0건`과 장애를 분리한다.

```text
RUNNING
SUCCESS
ZERO_RESULT
AUTH_ERROR
INVALID_PARAMETER
RATE_LIMIT
TRANSPORT_ERROR
SOURCE_ERROR
PARTIAL_SUCCESS
```

Collector는 실패한 window/partition을 cursor에 기록하고 재실행할 수 있어야 한다.

---

## 12. 배포구조

Streamlit Community Cloud 자체에 Collector와 DB를 종속시키지 않는다.

MVP 권장:

```text
GitHub Actions scheduled workflow
        ↓
Collector
        ↓
Hosted PostgreSQL
        ↑
Streamlit Production (read-only DB role)
```

### 원칙

- Collector DB role: write 허용
- Streamlit Production role: read-only
- Public PoC DB와 향후 병원 내부 Private DB는 **인스턴스 수준 분리**
- 공개 서비스에는 내부견적·계약단가 저장 금지
- DB 미구성/장애 시 현재 live Research로 graceful fallback

---

## 13. Backfill 단계

### Pilot 0 — Contract Verification

- 골든 세부품명 코드 7개
- Track A 최근 7일
- Track B 최근 30일
- Track C 최근 7일

확인:

- 요청 파라미터
- 기간창 제한
- pagination
- 실제 필드
- stable ID
- 응답시간

### Pilot 1 — 30일

- 대상 segment
- 30일 전 수집

측정:

- API 호출 수
- raw record 수
- unique stable key 수
- 변경차수 비율
- duplicate 비율
- observation 생성률
- generic 비율
- unresolved 비율
- DB 저장량

### Pilot 2 — 1년

30일 결과가 합격했을 때만 수행.

추가 측정:

- 지연등록 폭
- 12개월 가격 관측 증가량
- segment별 효율
- Product Identity 연결률

### Pilot 3 — 3년

1년 결과가 합격하고 DB 비용·수집시간이 합리적일 때만 수행.

### 5년

3년 대비 실질 관측 증가가 충분할 때만 검토한다.

---

## 14. Golden Collection Set

초기 골든 세부품명 코드는 리뷰 실측에 사용한 7개를 기준으로 한다.

```text
4110449801  이산화탄소배양기
4227250101  가스마취기
4227220901  인공호흡기
4110630701  유전자증폭기
4321150301  노트북컴퓨터
4321210501  레이저프린터
4321151501  워크스테이션
```

이 코드는 수집기 correctness를 검증하기 위한 회귀 anchor이며, 전체 대상 범위를 의미하지 않는다.

---

## 15. 성공지표

### 수집 안정성

- 동일 window 2회 실행 시 normalized row 중복증가 = 0
- 실패 후 cursor 재개 가능
- API 실패와 ZERO_RESULT 완전 분리
- source lineage 보존률 100%

### 데이터 품질

- 직접가격 observation 중 총액 파생단가 = 0
- superseded observation이 직접가격 band에 포함되는 비율 = 0
- generic identity가 product cluster로 자동승격되는 비율 = 0
- 공식 ID 불일치 제품의 VERIFIED 자동승격 = 0

### 업무효과

- DB만으로 응답 가능한 검색 비율
- 골든 제품 최근 12개월 직접가격 관측 수
- 검색 P95 응답시간
- 실시간 외부 API 호출 없이 결과가 표시되는 검색 비율
- 가격근거의 최근성(freshness)

---

## 16. Go / Stop Gate

### Go

다음을 만족하면 1년 이상 backfill을 확대한다.

- Track A/B/C API 계약 검증
- stable key 확정
- idempotent 재수집 성공
- 변경차수 처리 성공
- 가격 Observation 생성률이 유의미함
- DB 비용/용량 예측 가능

### Stop / Re-design

다음 중 하나면 해당 Track 확대를 중단한다.

- 대상 API가 운영계정에서도 충분한 호출량을 확보하지 못함
- 세부품명 전체 목록 확보 실패
- generic 비율이 과도해 제품수준 가격정보 가치가 낮음
- 직접가격 Observation 생성률이 지나치게 낮음
- 반복 수집 시 stable key를 만들 수 없음
- 동일 거래 중복·변경차수 오염을 통제하지 못함

---

## 17. P2 확장 방향

MVP 안정화 후 순서대로 검토한다.

1. 계약 물품세부
2. 입찰공고 구매대상 품목상세
3. 낙찰
4. 사전규격
5. MFDS 전수/증분 전략
6. 공식 제조사·총판 웹 가격
7. 규격서 첨부문서 분석
8. 병원 내부 Private Price Layer
9. 진료재료·간납품목

---

## 18. 비목표 / 금지사항

- API 성공을 데이터 완결성으로 간주하지 않는다.
- 검색 0건과 API 장애를 동일 취급하지 않는다.
- 세부품명번호가 같다는 이유로 동일제품으로 간주하지 않는다.
- 식약처 품목분류가 같다는 이유로 동일제품으로 간주하지 않는다.
- 텍스트 유사도·AI 판단만으로 VERIFIED 처리하지 않는다.
- 입찰·계약 총액을 나눠 단가를 만들지 않는다.
- 변경차수 과거 row를 삭제하지 않는다.
- Public PoC DB에 병원 내부 비공개 자료를 저장하지 않는다.
- Web 가격을 조달 납품가격과 같은 가격 band에 자동 혼합하지 않는다.

---

## 19. 최종 아키텍처

```text
PPS Detail Class Dictionary
            │
            ├──────────────┐
            │              │
 Track A: Date       Track B: Code × Date       Track C: Catalog Change
            │              │                     │
            └──────────────┼─────────────────────┘
                           ↓
                   Raw Source Record
                           ↓
             Delivery Line / Catalog Item
                           ↓
                   Product Identity
                           ↓
                     Resolver
                           ↓
                   Price Observation
                           ↓
              Product Price Summary / View
                           ↓
                 PostgreSQL Serving DB
                           ↓
           ┌───────────────┴───────────────┐
           ↓                               ↓
       직접 검색                       견적 업로드
                                           ↓
                                   OCR / Excel Parser
                                           ↓
                                     DB 제품 조회

DB 부족 시 → 기존 live G2B/MFDS Research
```

본 v3의 핵심은 **수집량을 늘리는 것 자체가 아니라, 공개조달 데이터를 재사용 가능한 시장가격 관측 DB로 만드는 것**이다.
