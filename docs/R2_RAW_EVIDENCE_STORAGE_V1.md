# Cloudflare R2 Raw Evidence Storage v1

- 작성일: 2026-09-11
- Repository: `dekt-oss/price-check-assistant`
- 목적: PostgreSQL은 검색/정규화/가격판정용 Operational DB로 유지하고, 공개 원천 Raw Evidence와 향후 DB backup은 Cloudflare R2에 분리 보관한다.
- 상태: **Live R2 read/write + G2B→R2 vertical slice PASSED / zero-cost guard·bucket lock pending**

---

## 1. 결정

DB Collection v3의 Raw Evidence 장기보관은 다음 구조를 사용한다.

```text
G2B / MFDS / public source
        │
        ├─ public provenance allow-list
        │          ↓
        │      Cloudflare R2
        │      raw/v1/...
        │
        └─ normalize / resolve
                   ↓
              PostgreSQL
              - source operation
              - stable key
              - payload hash
              - R2 object key
              - normalized delivery/catalog rows
              - price observations
              - product identity
              - cursor / run state
```

원칙:

1. **R2는 PostgreSQL 대체 DB가 아니다.**
2. PostgreSQL은 query, FK, unique, upsert, supersession, cursor, serving을 담당한다.
3. R2는 공개 Raw Evidence의 저비용 장기보관 및 재처리 원본을 담당한다.
4. Public PoC에서 병원 내부 비공개 견적·구매데이터는 R2에 저장하지 않는다.
5. API key, Authorization header, deployment secret을 raw payload에 저장하지 않는다.
6. content-addressed 저장으로 동일 payload 재수집 중복을 억제한다.

---

## 2. Bucket / 권한

권장 bucket은 프로젝트 전용 private Standard bucket이다.

```text
price-check-raw
```

권장값:

- Public access: **OFF**
- Storage class: **Standard**
- Custom domain: 사용하지 않음
- CORS: 사용하지 않음
- Collector token: 해당 bucket에만 `Object Read & Write`
- Streamlit Production: R2 writer credential을 기본적으로 주입하지 않음

Prefix:

```text
raw/v1/
db-backups/v1/
smoke/v1/
```

- `raw/v1/`: 공개 API 원본
- `db-backups/v1/`: 향후 PostgreSQL dump/Parquet backup
- `smoke/v1/`: 연결 검증용 임시 객체. probe 종료 시 삭제

---

## 3. Object key 계약

Raw object는 수집시각이 아니라 canonical payload SHA-256으로 주소를 만든다.

```text
raw/v1/<source_operation>/<sha[0:2]>/<sha[2:4]>/<sha256>.json.gz
```

효과:

- sliding-window 재조회로 동일 record를 반복 수집해도 object key는 동일하다.
- JSON key 순서가 달라도 canonical JSON이 같으면 동일 hash가 된다.
- payload가 바뀌면 새 object가 생성되어 변경 이력이 보존된다.
- gzip은 `mtime=0`으로 생성하여 동일 canonical JSON은 동일 compressed bytes를 만든다.

Object metadata:

```text
sha256=<canonical-json-sha256>
schema=raw-v1
source-operation=<operation>
data-classification=public-provenance
```

---

## 4. 실제 Live 검증 결과

### 4.1 R2 storage smoke

2026-09-11 실제 GitHub Actions에서 프로젝트 전용 R2 credential로 검증했다.

검증 경로:

```text
GitHub Secrets
→ R2 인증
→ bucket list
→ smoke object PUT
→ HEAD
→ DELETE
→ deterministic raw JSON upload
→ GET
→ gzip 해제
→ SHA-256 검증
→ 동일 payload 재업로드
```

결과:

- 설정 인식: **SUCCESS**
- bucket list: **SUCCESS**
- `put → head → delete`: **SUCCESS**
- raw sample upload/get/hash: **SUCCESS**
- 동일 static payload 재실행: `created=false` 확인

사용자 배포 Secret 이름은 다음을 표준으로 사용한다.

```text
R2_ACCOUNT_ID
R2_BUCKET
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

`R2_BUCKET_NAME`은 코드의 이전 호환 alias로만 남길 수 있으며 신규 운영설정에는 요구하지 않는다.

### 4.2 실제 G2B → R2 세로절단

GitHub Actions:

```text
workflow: G2B Catalog and Lifecycle Live Validation
run: 34555382527
job: 103126860717
result: SUCCESS
```

실제 경로:

```text
G2B live API
getPrdctIndvAtrbInfoList02
product_id = 24888744
        ↓
원본 JSON 수신
        ↓
canonical JSON + SHA-256
        ↓
gzip
        ↓
R2 raw/v1/...json.gz PUT
        ↓
R2 GET
        ↓
해제 + SHA-256 + JSON 동일성 검증
        ↓
동일 payload 재저장
        ↓
created=false 확인
```

실측 결과:

```text
status: SUCCESS
source: G2B_CATALOG
operation: getPrdctIndvAtrbInfoList02
product_id: 24888744
roundtrip_equal: true
first_created: true
duplicate_created: false
uncompressed_bytes: 3640
stored_bytes: 601
```

압축률 기준으로 원본 3,640 bytes가 601 bytes로 저장되어 약 83.5% 감소했다. 이 수치는 단일 catalog 응답 실측이며 전체 데이터셋 평균으로 일반화하지 않는다.

실제 object key:

```text
raw/v1/getPrdctIndvAtrbInfoList02/e1/12/e11268b9461b4112285843de4d2d0d2dcdf41127420756089a885dfe5582b08c.json.gz
```

세로절단 종료 후 PR에서 R2 Secret을 소비하던 임시 workflow hook은 제거했다. live evidence는 Actions run에 남기고, 일반 PR 코드가 writer secret을 소비하지 않도록 원복한다.

---

## 5. PostgreSQL DB1 반영 계약

DB1 구현 시 `raw_source_records`는 raw body 자체보다 R2 pointer/index 역할을 맡는다.

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
payload_hash char(64)
r2_bucket
r2_object_key
payload_bytes
stored_bytes
parser_version
fetched_at

UNIQUE(source_operation, payload_hash)
INDEX(source_operation, stable_key)
INDEX(fetched_at)
```

Raw object upload와 DB insert 순서는 다음으로 고정한다.

```text
API record
→ public provenance allow-list
→ canonical JSON + SHA-256
→ R2 put/head
→ raw_source_records upsert
→ normalize
→ page commit
```

R2 upload 성공 후 DB transaction이 실패해 orphan object가 생기는 것은 허용한다. content-addressed object이므로 재실행 시 같은 key를 재사용할 수 있다. 반대로 DB pointer를 먼저 commit하고 R2 upload를 나중에 수행하지 않는다.

---

## 6. Bucket lock / lifecycle

Pilot 권장 후보:

```text
raw/v1/        최소 180일 Bucket Lock
smoke/v1/      Lock 없음
db-backups/v1/ 초기 Lock 없음
```

다만 lock은 아직 적용·재검증하지 않았다. retention 확정 전 Production-ready로 간주하지 않는다.

---

## 7. Zero-cost 운영 원칙

사용자 운영 원칙은 **월 비용 0원**이다.

따라서 R2 무료범위를 넘어 자동 과금되는 상황을 막기 위해 애플리케이션 차원의 quota guard가 필요하다. 구체 임계치는 별도 구현에서 확정한다.

예시 정책 후보:

```text
8 GB   경고
9 GB   신규 대량 backfill 중단
9.5 GB raw 신규 적재 중단 또는 수동 승인 필요
```

위 임계치는 아직 구현되지 않은 후보값이며 확정 정책이 아니다.

---

## 8. Live Gate 상태

```text
[x] private project bucket 생성
[x] bucket credential로 실제 접근 성공
[x] read probe SUCCESS
[x] write/head/delete smoke SUCCESS
[x] raw/v1 sample upload SUCCESS
[x] 동일 payload 재업로드 시 created=false
[x] sample get + SHA-256 검증 SUCCESS
[x] 실제 G2B → R2 vertical slice SUCCESS
[ ] Streamlit 환경에 writer token이 없는지 별도 확인
[ ] raw/v1 bucket lock 적용 후 재검증
[ ] zero-cost quota guard 구현
```

R2 데이터 경로 자체는 **검증 완료**다. 남은 항목은 운영 안전장치다.

---

## 9. 다음 단계

DB1 전에 다음을 처리한다.

1. zero-cost quota guard 임계치 확정·구현
2. `raw/v1/` retention / Bucket Lock 확정
3. `raw_source_records`에 R2 pointer/byte-size 필드 반영
4. raw ingest repository와 `R2RawEvidenceStore` 연결
5. collector writer와 Streamlit read-only DB account 분리
6. 실제 수집으로 30일 storage growth를 측정하여 용량 예측 갱신
