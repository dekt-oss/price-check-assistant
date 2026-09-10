# 구매시장정보 DB 수집체계 구현명세서 v3

- 작성일: 2026-09-10
- Repository: `dekt-oss/price-check-assistant`
- 기준 `main`: `ba16650fddcd3785b1974804f6bd34a524d1dd42`
- 연계 기획: `docs/DB_COLLECTION_ARCHITECTURE_PLAN_V3.md`
- 구현원칙: **작은 PR + 명시적 Gate + main 회귀보호**

---

## 0. 구현 목표

이 명세서는 다음 사용자 체감을 만드는 것이 목적이다.

### 검색

```text
제품명/모델 입력
→ PostgreSQL에서 즉시 기존 시장가격·조달관측 조회
→ 가격분포/출처/거래일 표시
→ DB 부족 시에만 live Research
```

### 견적

```text
PDF/Excel/Image 업로드
→ 품목·모델 후보 추출
→ Product Identity 후보 조회
→ DB 가격 즉시 표시
→ 최신성이 부족할 때 live Research
```

OCR 또는 외부 API 일시 실패가 전체 업무를 중단시키지 않아야 한다.

---

# 1. 절대 유지해야 하는 기존 계약

구현 중 다음 계약을 변경하지 않는다.

1. API failure ≠ zero result.
2. 총액·예정가격·낙찰총액을 수량으로 나누어 제품단가를 만들지 않는다.
3. Research evidence를 direct price로 자동승격하지 않는다.
4. `QUOTE_COMPARABLE`은 명시적 비교조건 및 승인 없이 자동 부여하지 않는다.
5. 동일 세부품명번호 또는 동일 MFDS 품목분류만으로 동일제품으로 판정하지 않는다.
6. 동일제품·대체제품·동일분류 Research의 가격범위를 섞지 않는다.
7. 원천 raw provenance를 잃지 않는다.
8. Public PoC에는 병원 내부 비공개 구매데이터를 저장하지 않는다.
9. 변경차수 이전 record는 삭제하지 않고 superseded 상태로 보존한다.
10. 검증하지 못한 live behavior는 `미검증`으로 기록한다.

기존 `MatchGrade`, `EvidenceType`, `ComparisonScope`, `SourceType`, `configuration_fingerprint`, `assess_prices()` 계약은 가능한 한 재사용한다.

---

# 2. 사전 조건 — Step 0 / 코드 없음

본 구현을 시작하기 전에 아래 외부조건을 확인한다.

## 2.1 조달 물품목록 API

필수 확인:

- `getPrdctClsfcNoUnit10Info02` 활용승인
- 검색조건 없이 전체 10자리 세부품명 목록 조회 가능 여부
- `pageNo`, `numOfRows`, `totalCount` 실제 계약
- 운영계정 호출량

### Gate 0-A

다음 정보를 기록한다.

```text
operation
successful request params
max tested numOfRows
record count
elapsed time
resultCode/resultMsg
collected_at
```

전체 세부품명 목록을 안정적으로 가져오지 못하면 **Track B를 품명 부분일치로 대체 구현하지 않는다.**

## 2.2 운영 DB

호스팅 PostgreSQL을 준비한다.

필수 role:

```text
collector_writer
streamlit_reader
migration_admin
```

`streamlit_reader`에는 serving view/table SELECT만 허용한다.

### Gate 0-B

Production과 동일 네트워크 환경에서 read-only 연결 smoke를 통과한다.

## 2.3 G2B 운영계정 호출량

Pilot 30일 결과를 바탕으로 활용사례·트래픽 증설 필요성을 판단한다.

개발계정 제한을 무시한 병렬수집을 구현하지 않는다.

---

# 3. 데이터 모델 v3

현재 `models.py`의 `Product`, `CollectionRun`, `RawEvidence`, `PriceObservation`을 무조건 제거하지 않는다. Migration compatibility를 우선하여 단계적으로 전환한다.

## 3.1 Enum / domain additions

신규 enum 후보:

```python
class CollectionStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ZERO_RESULT = "ZERO_RESULT"
    AUTH_ERROR = "AUTH_ERROR"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    SOURCE_ERROR = "SOURCE_ERROR"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"

class ResolutionStatus(StrEnum):
    VERIFIED_OFFICIAL_ID = "VERIFIED_OFFICIAL_ID"
    VERIFIED_HUMAN = "VERIFIED_HUMAN"
    CANDIDATE = "CANDIDATE"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"
    GENERIC_CLASS_ONLY = "GENERIC_CLASS_ONLY"

class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
```

기존 enum과 중복되는 경우 새 enum을 만들기보다 기존 계약을 확장한다.

---

## 3.2 `collection_runs` 확장

추가 필드:

```text
source_operation
partition_key nullable
window_begin nullable
window_end nullable
page_count
request_count
new_count
updated_count
error_count
status
error_code nullable
error_message nullable
started_at
finished_at
```

`query_text`는 기존 호환을 위해 유지할 수 있으나 v3 Collector의 핵심키로 사용하지 않는다.

---

## 3.3 `collection_cursors`

```text
id PK
source_operation
partition_key
last_complete_window_end
last_complete_page nullable
last_run_id nullable
updated_at

UNIQUE(source_operation, partition_key)
```

`partition_key` 예:

```text
track-a:all
track-b:4110449801
track-c:mas
```

Cursor는 성공 완료된 window까지만 전진한다.

---

## 3.4 `raw_source_records`

기존 `raw_evidence`를 migration으로 진화시키거나 신규 테이블을 도입할 수 있다. 구현 시 기존 참조량을 먼저 확인한다.

권장 필드:

```text
id PK
run_id FK
source_name
source_operation
source_record_id nullable
stable_key nullable
source_url nullable
original_title nullable
payload_json JSONB
payload_hash char(64)
parser_version
fetched_at

UNIQUE(source_operation, payload_hash)
INDEX(source_operation, stable_key)
INDEX(fetched_at)
```

### Raw 저장 정책

- API 전체 응답 envelope를 무조건 저장하지 않는다.
- `public_provenance` allow-list를 적용한 record payload를 저장한다.
- canonical JSON을 기준으로 hash를 만든다.
- raw 삭제를 전제로 하지 않는다.

### FK

`price_observation.evidence/raw_id`가 NOT NULL이면 raw FK는 `RESTRICT`를 사용한다. `NOT NULL + ON DELETE SET NULL` 조합을 제거한다.

---

## 3.5 `pps_detail_classes`

```text
detail_code varchar(10) PK
korean_name
english_name nullable
description nullable
use_yn nullable
segment varchar(2)
collect_track nullable
collect_enabled bool
rationale nullable
source_raw_id nullable
collected_at
updated_at
```

별도 관리파일:

```text
data/pps_collect_tracks.csv
```

컬럼:

```text
detail_code_or_segment
scope_type
collect_track
enabled
rationale
reviewed_at
```

코드 전체를 코드에 하드코딩하지 않는다.

---

## 3.6 `delivery_lines`

Track A/B 정규화 공통 테이블.

```text
id PK
source_operation
request_no
change_order
line_no
pps_product_id nullable
detail_code nullable
product_name_raw
quantity nullable
unit nullable
unit_price nullable
total_amount nullable
transaction_date nullable
institution_code nullable
institution_name nullable
institution_bizno nullable
supplier_name nullable
supplier_bizno nullable
delivery_condition nullable
contract_type nullable
package_flag bool default false
is_final_source_flag nullable
record_status
superseded_by nullable FK delivery_lines.id
raw_id FK raw_source_records.id
normalizer_version
created_at
updated_at

UNIQUE(source_operation, request_no, change_order, line_no)
INDEX(pps_product_id, transaction_date)
INDEX(detail_code, transaction_date)
INDEX(request_no, line_no)
INDEX(record_status)
```

### stable key

Track B:

```text
(cntrctDlvrReqNo, cntrctDlvrReqChgOrd, prdctSno)
```

Track A는 operation의 실제 field contract를 live fixture로 고정한 후 동일 원칙을 사용한다.

---

## 3.7 `catalog_items`

```text
id PK
source_operation
shopping_contract_no
shopping_contract_seq
pps_product_id nullable
detail_code nullable
product_name_raw nullable
manufacturer_raw nullable
specification_raw nullable
contract_price nullable
vat_status nullable
delivery_condition nullable
spec_document_urls JSONB nullable
certification_list JSONB nullable
registered_at nullable
changed_at nullable
contract_begin_date nullable
contract_end_date nullable
raw_id FK
created_at
updated_at
```

변경이력을 잃지 않도록 stable key는 실제 operation별 key와 `changed_at` 계약을 확인해 확정한다.

---

## 3.8 `product_master`

제품 cluster 테이블.

```text
id PK
display_label
category_major nullable
category_middle nullable
category_small nullable
active_status nullable
created_at
updated_at
```

`canonical_model`을 제품 자연키로 사용하지 않는다.

---

## 3.9 `product_identities`

```text
id PK
product_master_id nullable FK
identity_system
identity_value
identity_kind
manufacturer_raw nullable
model_raw nullable
specification_raw nullable
source_raw_id nullable
resolution_status
created_at
updated_at

UNIQUE(identity_system, identity_value)
INDEX(product_master_id)
INDEX(resolution_status)
```

Identity System:

```text
PPS_PRODUCT_ID
MFDS_MODEL_SEQ
UDI_DI
MANUFACTURER_MODEL
```

Generic PPS 식별값은 `identity_kind=GENERIC_CLASS` 또는 `resolution_status=GENERIC_CLASS_ONLY`로 두고 product cluster 연결을 금지한다.

---

## 3.10 `product_aliases`

```text
id PK
identity_id FK
source
raw_name
normalized_value
alias_type
raw_id nullable
created_at

UNIQUE(identity_id, source, normalized_value)
```

alias type 예:

```text
PRODUCT_NAME
MODEL
MANUFACTURER
SPECIFICATION
```

---

## 3.11 `resolver_decisions`

자동·수동 결정을 감사 가능하게 저장한다.

```text
id PK
identity_id
from_status nullable
to_status
basis_kind
basis_value nullable
evidence_raw_id nullable
actor nullable
decided_at
note nullable
```

`VERIFIED_HUMAN`에는 `actor`, `decided_at`, 근거 ID가 필수다.

---

## 3.12 `price_observations` v3

기존 테이블을 확장한다.

추가/변경 후보:

```text
normalized_line_id nullable
product_master_id nullable
pps_product_id nullable
detail_code nullable
institution_name nullable
supplier_name nullable
package_flag bool
record_status
vat_status
delivery_condition
installation_condition
option_condition
warranty_condition
```

Unique 계약은 기존 `(evidence_id, product_id, derivation_version, evidence_type)`에서 제품 resolver 변경과 충돌하지 않도록 재검토한다.

권장 방향:

```text
UNIQUE(raw_id, derivation_version, evidence_type)
```

제품 연결은 파생 후 변경될 수 있으므로 product id를 uniqueness identity로 쓰지 않는다.

### observation 생성 규칙

- 명시 단가 필드가 있을 때만 생성
- `price > 0`
- 총액만 있을 경우 observation 생성 금지
- superseded line이면 `comparison_scope=EXCLUDE`
- generic identity는 observation 자체는 저장 가능하지만 product-level direct comparison에는 자동 사용 금지
- 기본 `comparison_scope=OBSERVED_ONLY`

---

# 4. Repository 계약

## 4.1 모든 ingest는 idempotent

기존 `get_or_create_*`의 SELECT → INSERT race를 제거한다.

PostgreSQL:

```sql
INSERT ... ON CONFLICT (...) DO NOTHING RETURNING id
```

필요하면 반환 0건 후 동일 key 재SELECT.

### 테스트

- 동일 raw record를 두 Session에서 경쟁 insert
- 예외 없음
- 최종 row 1개
- caller는 created true/false를 구분 가능

---

## 4.2 Transaction boundary

한 page/window 처리 단위:

```text
API page fetch
→ raw insert
→ normalize
→ commit
```

권장 기본은 page 단위 commit이다.

단, cursor는 **전체 window 성공 후** 전진한다.

페이지 중간 실패 시 이미 적재한 page는 idempotent하게 재실행한다.

---

# 5. Collector 공통 인터페이스

권장 protocol:

```python
@dataclass(frozen=True)
class CollectionPartition:
    source_operation: str
    partition_key: str
    window_begin: date | datetime
    window_end: date | datetime

@dataclass(frozen=True)
class CollectionPageResult:
    records: tuple[dict, ...]
    page_no: int
    total_count: int | None
    has_next: bool

class IncrementalCollector(Protocol):
    def fetch_page(self, partition: CollectionPartition, page_no: int) -> CollectionPageResult: ...
```

Collector는 ORM 모델을 직접 만들지 않는다.

```text
Collector → raw ingest → normalizer
```

를 분리한다.

---

# 6. 오류분류

`PublicDataPortalClient` 예외를 다음 상태로 매핑한다.

| 상태 | 예 |
|---|---|
| `AUTH_ERROR` | service key 미승인/인증 실패 |
| `INVALID_PARAMETER` | 필수 파라미터 누락, 기간창 위반 |
| `RATE_LIMIT` | 트래픽 제한 |
| `TRANSPORT_ERROR` | timeout/connect |
| `SOURCE_ERROR` | upstream 5xx/비정상 envelope |
| `ZERO_RESULT` | 정상 응답 + totalCount=0 |
| `PARTIAL_SUCCESS` | 일부 page 저장 후 window 미완료 |

**금지:** 예외 catch 후 빈 list 반환.

---

# 7. Track A 구현명세

## 대상

`G2BShoppingOperation.DELIVERY_REQUEST_DETAILS`

## 신규 파일 권장

```text
src/purchase_price/services/collection/common.py
src/purchase_price/services/collection/track_a_delivery.py
src/purchase_price/services/normalization/delivery_line.py
src/purchase_price/repositories/collection.py
src/purchase_price/repositories/delivery_lines.py
scripts/collect_g2b_track_a.py
```

## 동작

1. cursor 조회
2. 요청 window 결정
3. 최대 1개월 window 강제
4. `numOfRows`는 실측 가능한 최대값으로 설정; 임의 100행 상한 제거
5. 모든 page fetch
6. raw upsert
7. delivery line normalize/upsert
8. supersession reconcile
9. window 완료 기록
10. cursor 전진

## 운영 초기값

```text
daily schedule
lookback = 7 days
```

## Gate A

- 동일 7일 window 2회 → normalized 행수 증가 0
- ZERO_RESULT와 API failure 분리
- 변경차수 fixture `00→01`에서 active line 1개
- 기존 observation safety test 회귀 없음

---

# 8. Track B 구현명세

## 대상

`G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS`

현재 `fetch_specific_item_page()`는 `final_change_order_only="Y"` 기본값을 가진다. v3 collector에서는 **전 변경차수 보존**을 위해 final-only 필터를 제거하거나 명시적으로 전체 차수를 가져오는 검증된 요청계약을 사용한다.

## Partition

```text
partition_key = detail_code
window = detail_code × date range
```

## 입력 세부품명

`pps_detail_classes.collect_enabled=true`만 수집한다.

## 페이지 크기

현재 `num_of_rows=100` 기본을 v3 bulk collection에 그대로 사용하지 않는다. 실측·공식 계약에 맞춰 large page size를 별도 상수로 둔다.

예:

```python
G2B_BULK_PAGE_SIZE = 999
```

실제 API가 허용하는 값이 Gate 0에서 달라지면 그 값을 Source of Truth로 사용한다.

## 큰 코드 처리

1년 window가 999 page-size 1회로 끝나지 않아도 정상 pagination한다.

특정 코드의 volume이 과도하면:

```text
1년 → 분기 → 월
```

순으로 window를 자동 분할할 수 있다.

## 금지

- 8자리/4자리 prefix를 10자리 코드 대신 사용
- 광역 품명 substring으로 전체 대체
- final change-order only를 데이터 완결로 간주

## Golden Gate B

골든 코드:

```text
4110449801
4227250101
4227220901
4110630701
4321150301
4321210501
4321151501
```

live probe는 고정된 정확값보다 허용범위/최소근거와 API contract를 검증한다. 외부 데이터 증가로 건수가 바뀔 수 있으므로 historical reference count는 진단값이지 영구 unit test 상수로 두지 않는다.

필수:

- 코드 기반 요청 성공
- stable key 생성률 100% 또는 예외행 명시
- change order 보존
- `prdctIdntNo` 보존
- 명시 단가 그대로 보존

---

# 9. Track C 구현명세

## 대상 operation

- MAS 계약품목
- 3자단가
- 일반단가

현재 enum에 없는 operation은 실제 API 계약 검증 후 추가한다.

## 초기 backfill

`registered_at` 기준.

## 운영 증분

`changed_at` 기준.

## normalize 필드 최소집합

```text
shopping_contract_no
shopping_contract_seq
pps_product_id
detail_code
product_name
manufacturer
specification
contract_price
vat_status
delivery_condition
spec_document_urls
certification_list
registered_at
changed_at
```

규격서 URL은 저장하되 MVP에서는 다운로드하지 않는다.

## Gate C

- 같은 등록 row + 변경 row 중복 없음
- changed_at 증분이 cursor와 연동
- manufacturer/specification raw 손실 없음
- VAT 원문 손실 없음

---

# 10. 세부품명 Dictionary 구현명세

신규 collector:

```text
src/purchase_price/services/collection/pps_detail_class.py
scripts/collect_pps_detail_classes.py
```

## 동작

- 10자리 전체 목록 fetch
- `pps_detail_classes` upsert
- 신규 코드 / 명칭변경 기록
- `collect_track`은 별도 reviewed CSV에서 결정

## Gate

- 골든 7 코드가 모두 존재
- detail_code 길이=10 digit
- 동일 전체수집 2회 중복 없음

---

# 11. Resolver 구현명세

## 11.1 PPS Product ID

G2B row의 `prdctIdntNo`는 `PPS_PRODUCT_ID` identity로 저장한다.

동일 `prdctIdntNo`가 Track A/B/C에서 들어오면 identity row는 하나여야 한다.

## 11.2 Generic 감지

최소 heuristic:

- product identity name에 `수요기관규격`
- `기타물품포함`
- 제조사/모델 공식정보 부재 + generic marker

이면 `GENERIC_CLASS_ONLY` 후보.

Generic heuristic은 테스트와 evidence를 가져야 하며 generic을 실제 특정 모델 cluster로 연결하지 않는다.

## 11.3 자동 상태

```text
공식 identity exact → VERIFIED_OFFICIAL_ID
manufacturer alias + model exact, no explicit conflict → CANDIDATE
세부품명번호 only → UNRESOLVED 또는 GENERIC_CLASS_ONLY
model/spec explicit conflict → CONFLICT
```

## 11.4 Human approval

사용자 승인 UI가 생기기 전에는 `VERIFIED_HUMAN`을 생성하지 않는다.

향후 승인 시:

```text
actor
approved_at
source identities
supporting evidence
note
```

필수.

---

# 12. Supersession 구현명세

함수 후보:

```python
reconcile_delivery_line_supersession(session, request_no, line_no)
```

알고리즘:

1. 같은 `(source_operation, request_no, line_no)` rows 조회
2. change_order 정렬
3. 최고 유효차수를 ACTIVE
4. 이전 차수 SUPERSEDED
5. `superseded_by` 연결
6. 이전 line에 연결된 price observation을 EXCLUDE
7. 삭제 없음

### 주의

숫자 change order가 항상 integer인지 실제 응답으로 확인한다. string order가 있다면 원천 ordering contract를 별도 parser로 만든다.

### Test

- 00만 적재
- 00→01
- 01→00 역순 적재
- 00→02→01 out-of-order
- cancellation marker가 있는 경우

모든 순서에서 최종 active semantics가 동일해야 한다.

---

# 13. Price Observation Builder

신규 권장:

```text
src/purchase_price/services/evidence/build_observations.py
```

입력:

```text
DeliveryLine | CatalogItem
```

출력:

```text
PriceObservation
```

Evidence Type 예:

```text
Track A explicit delivery unit price
→ DELIVERY_ORDER_UNIT_PRICE

Track B explicit procurement delivery line unit price
→ DELIVERY_ORDER_UNIT_PRICE

Track B explicit contract line unit price
→ CONTRACT_UNIT_PRICE

Track C explicit shopping contract price
→ SHOPPING_CONTRACT_UNIT_PRICE
```

### Invariant tests

- total_amount only → observation 0
- `total / qty` 계산 코드 없음
- quantity=0/price≤0 → observation 0
- superseded → EXCLUDE
- unresolved product → observation 저장 가능, direct product band 사용 금지
- product identity conflict → EXCLUDE 또는 product link 없음

---

# 14. Serving / DB-first 조회

## 신규 service

```text
src/purchase_price/services/db_price_lookup.py
```

최초 검색키:

1. exact PPS Product ID
2. verified Product Master identity
3. normalized model/manufacturer alias candidate
4. detail class fallback는 **Research section만**

## 반환모델

```python
@dataclass(frozen=True)
class StoredMarketResult:
    observations: tuple[PriceEvidence, ...]
    product_identity_status: str
    last_transaction_date: date | None
    last_collected_at: date | None
    source_count: int
```

기존 `assess_prices()`가 받을 수 있는 evidence 형태로 어댑트한다.

## UI

DB 결과와 live 결과를 구분한다.

표시:

```text
저장된 시장가격 DB
- 최근 거래일
- 마지막 수집일
- 직접가격 관측 수
- 독립 출처/기관 수

최신 공개자료 추가 검색
```

## Feature Flag

초기:

```text
ENABLE_DB_FIRST_MARKET_LOOKUP=false
```

Staging/Production UAT 후 true.

flag false 시 기존 live flow가 완전히 동일하게 동작해야 한다.

---

# 15. Materialized View

초기 serving 최적화는 검색엔진 대신 PostgreSQL MV로 시작한다.

예:

```text
product_price_summary
```

Dimension:

```text
product_master_id
period_days
price_evidence_type
```

Metric:

```text
observation_count
source_count
institution_count
median_price
min_price
max_price
latest_transaction_date
latest_collected_at
```

**중요:** MV 계산 로직이 `assess_prices()`의 가격범위 계약과 달라지지 않도록 같은 filtering predicate를 공유한다.

---

# 16. Workflow / 운영

## 16.1 Scheduled workflow

권장 파일:

```text
.github/workflows/collect-g2b-daily.yml
```

초기에는 Track별 workflow를 분리해 장애영향을 격리해도 된다.

예:

```text
collect-g2b-track-a.yml
collect-g2b-track-b.yml
collect-g2b-track-c.yml
```

## 16.2 실행조건

- `schedule`
- `workflow_dispatch`

## 16.3 secrets

```text
DATABASE_URL
G2B service keys already used by current repository
```

secret 이름은 현재 Settings contract를 확인해 기존 이름을 재사용한다. 신규 임의 secret 이름을 먼저 만들지 않는다.

## 16.4 budget

각 collector는 요청예산을 가진다.

```text
MAX_REQUESTS_PER_RUN
MAX_RUNTIME_SECONDS
```

예산을 넘으면 `PARTIAL_SUCCESS`로 종료하고 cursor는 완결 window까지만 전진한다.

---

# 17. Collection Health

최소 admin/diagnostic surface:

| Source | Last Success | Complete Through | Status | Requests | New | Updated | Errors |
|---|---|---|---|---:|---:|---:|---:|

반드시 확인 가능한 항목:

- source별 마지막 성공
- cursor
- lag
- AUTH_ERROR
- invalid parameter
- rate limit
- partial window

`0건`을 초록색 성공처럼 보여서는 안 되며 `ZERO_RESULT`로 명시한다.

---

# 18. PR 실행계획

각 Step은 원칙적으로 하나의 PR이다. 이전 Step Gate가 실패하면 다음 구조 PR을 진행하지 않는다.

## PR-DB0 — Feasibility evidence / 계약검증

코드 변경은 최소화하거나 없음.

산출물:

```text
docs/DB_COLLECTION_FEASIBILITY_YYYYMMDD.md
```

포함:

- Unit10 전체목록 실제 결과
- Track A/B/C live request contract
- page size
- response time
- volume
- key approval state

**Gate:** Track B dictionary 확보 가능 여부 결정.

---

## PR-DB1 — Raw / Cursor / Normalize Foundation

예상 변경:

```text
src/purchase_price/models.py
src/purchase_price/domain.py
src/purchase_price/repositories/evidence.py
src/purchase_price/repositories/collection.py
src/purchase_price/repositories/delivery_lines.py
alembic/versions/0003_db_collection_foundation.py
tests/test_collection_repository.py
tests/test_db_collection_migration.py
```

작업:

- collection status
- cursor
- raw JSONB
- ON CONFLICT
- FK RESTRICT
- detail class
- delivery line
- catalog item

**Gate:** migration upgrade/downgrade test, concurrency/idempotency test.

---

## PR-DB2 — PPS Detail Class Dictionary

변경:

```text
src/purchase_price/services/collection/pps_detail_class.py
scripts/collect_pps_detail_classes.py
data/pps_collect_tracks.csv
tests/test_pps_detail_class_collection.py
```

**Gate:** 골든 7 코드 확인 + 재실행 idempotent.

---

## PR-DB3 — Track A

변경:

```text
src/purchase_price/services/collection/track_a_delivery.py
src/purchase_price/services/normalization/delivery_line.py
scripts/collect_g2b_track_a.py
.github/workflows/collect-g2b-track-a.yml
tests/test_track_a_collection.py
```

**Gate:** 7/30일 Pilot + 중복 0 + failure/zero 분리.

---

## PR-DB4 — Track B

변경:

```text
src/purchase_price/collectors/g2b_shopping.py
src/purchase_price/services/collection/track_b_specific_item.py
src/purchase_price/services/normalization/delivery_line.py
scripts/collect_g2b_track_b.py
.github/workflows/collect-g2b-track-b.yml
tests/test_track_b_collection.py
```

필수 수정:

- final-only 변경차수 filter 제거/재계약
- bulk page size
- code×window partition

**Gate:** 골든 7 코드 live probe + supersession.

---

## PR-DB5 — Track C

변경:

```text
src/purchase_price/collectors/g2b_shopping.py
src/purchase_price/services/collection/track_c_catalog.py
src/purchase_price/services/normalization/catalog_item.py
scripts/collect_g2b_track_c.py
.github/workflows/collect-g2b-track-c.yml
tests/test_track_c_collection.py
```

**Gate:** 등록/변경 증분 중복 0.

---

## PR-DB6 — Product Identity / Resolver

변경:

```text
src/purchase_price/models.py
src/purchase_price/services/resolve/*
src/purchase_price/repositories/identity.py
alembic/versions/0004_product_identity.py
tests/test_product_identity_resolution.py
```

**Gate:** generic / exact ID / conflict / candidate matrix.

---

## PR-DB7 — Observation Builder

변경:

```text
src/purchase_price/services/evidence/build_observations.py
src/purchase_price/repositories/observations.py
alembic/versions/0005_price_observation_v3.py
tests/test_observation_builder.py
```

**Gate:** 총액 파생 0, superseded direct band 0.

---

## PR-DB8 — DB-first Serving

변경:

```text
src/purchase_price/services/db_price_lookup.py
src/purchase_price/ui/market_research.py
src/purchase_price/ui/widgets.py
alembic/versions/0006_product_price_summary.py
tests/test_db_first_market_lookup.py
tests/test_market_first_ui_contract.py
```

**Gate:** feature flag off 기존 결과 무변경; flag on DB-only query P95 목표 충족.

---

## PR-DB9 — Ops / Freshness

변경:

```text
pages/<관리/상태 페이지 또는 기존 진단 surface>
src/purchase_price/services/collection/health.py
tests/test_collection_health.py
```

**Gate:** 깨진 key fixture에서 AUTH_ERROR가 ZERO_RESULT와 명확히 분리.

---

# 19. 테스트 전략

## 19.1 Unit

- stable key
- parser
- enum mapping
- supersession
- observation eligibility
- resolver state

## 19.2 Repository

실제 PostgreSQL을 사용하는 migration/integration test를 우선한다.

SQLite로 PostgreSQL `ON CONFLICT`, JSONB, partial index semantics를 대체검증하지 않는다.

## 19.3 Offline fixture

실제 응답 스키마를 비식별 fixture로 고정한다.

Raw fixture는 원천 필드명을 유지한다.

## 19.4 Live probe

live probe는 unit test와 분리한다.

검증:

- API contract
- 필수 파라미터
- 실제 응답필드
- 비정상 resultCode
- pagination

외부 데이터의 절대 건수는 영구 deterministic test로 사용하지 않는다.

## 19.5 Golden domain regression

기존 APC-30D / FLOW-C safety gate는 유지한다.

DB 수집이 추가되어도:

- same product
- related alternative
- classification Research
- contract/bid total

분리가 바뀌지 않아야 한다.

---

# 20. Pilot 결과 리포트 계약

30일 Pilot마다 artifact 또는 Markdown으로 다음을 남긴다.

```text
source_operation
partition_count
window_count
request_count
success_count
zero_result_count
error_count
raw_records
unique_stable_keys
normalized_lines
active_lines
superseded_lines
price_observations
generic_identity_count
resolved_identity_count
candidate_identity_count
unresolved_identity_count
raw_storage_bytes
elapsed_seconds
```

이 숫자가 없으면 1년 backfill 승인 판단을 하지 않는다.

---

# 21. 성능 목표

초기 MVP:

- DB direct lookup P95 < 5초
- 일반 제품 exact identity 조회는 목표 < 2초
- Streamlit 요청 중 bulk collection 금지
- collector job은 사용자 request와 분리
- materialized summary refresh는 batch job에서 수행

---

# 22. 보안 / Public-Private 경계

## Public

- 공개조달
- 공개 식약처
- 향후 승인된 공개 웹

## Private

- 본원 견적
- 계약단가
- 공급조건
- 구매량
- 부서별 수요

두 데이터는 같은 `source_type` 값으로만 구분하는 것으로 충분하지 않다.

최종 내부 전환 시:

```text
Public DB instance
Private hospital DB instance
```

를 분리한다.

Private DB 접속정보와 데이터는 public GitHub Actions/Community Cloud에 두지 않는다.

---

# 23. 이번 MVP에서 하지 말 것

1. 모든 나라장터 operation을 하나의 generic collector로 한 번에 구현.
2. 모든 품목을 문자열 검색으로 전수수집.
3. Product Master canonical model 자동생성.
4. generic PPS product id를 실제 모델 cluster로 연결.
5. AI similarity로 VERIFIED.
6. 입찰/계약 총액을 direct price로 저장.
7. superseded row 삭제.
8. 웹 크롤링 추가.
9. MFDS 전수수집 추가.
10. Elasticsearch/OpenSearch 도입.
11. 3년 backfill을 Pilot 없이 바로 실행.
12. DB-first flag를 Production에서 검증 없이 즉시 켬.

---

# 24. 개발 시작 순서

개발자는 다음 순서를 지킨다.

```text
0. latest main 복구
1. 본 기획/명세 확인
2. PR-DB0 API/DB Feasibility 확인
3. PR-DB1 foundation
4. PR-DB2 detail dictionary
5. PR-DB3 Track A
6. PR-DB4 Track B
7. PR-DB5 Track C
8. 30일 Pilot 리포트
9. Product Identity / Resolver
10. Observation Builder
11. DB-first Serving
12. Ops/Freshness
13. 1년 backfill 승인 판단
```

구현 편의상 순서를 변경해야 하면 PR 본문에 이유와 영향을 기록한다.

---

# 25. Definition of Done

DB 수집 MVP는 다음 조건을 모두 만족해야 완료다.

- Track A/B/C 중 승인된 Track이 정기 실행됨
- collector failure와 zero-result가 구분됨
- cursor 재개 가능
- 같은 window 재실행 중복 0
- 변경차수 supersession 작동
- PPS Product ID identity 중복 0
- generic 제품 자동 verified 0
- 총액 파생 단가 0
- 모든 displayed price가 raw source까지 역추적됨
- Streamlit이 DB를 read-only로 조회함
- DB 장애 시 live Research fallback 가능
- 기존 APC/FLOW safety regression 통과
- 30일 Pilot 리포트 존재
- Production에서 DB-only 골든 검색이 사용자 체감 가능한 속도로 동작

이 조건 이전에는 “시장가격 DB 구축 완료”로 표현하지 않는다.
