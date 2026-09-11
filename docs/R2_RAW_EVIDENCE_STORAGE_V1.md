# Cloudflare R2 Raw Evidence Storage v1

- 작성일: 2026-09-11
- Repository: `dekt-oss/price-check-assistant`
- 목적: PostgreSQL은 검색/정규화/가격판정용 Operational DB로 유지하고, 공개 원천 Raw Evidence와 향후 DB backup은 Cloudflare R2에 분리 보관한다.
- 상태: **Foundation implemented / live bucket smoke pending**

---

## 1. 결정

기존 DB Collection v3의 `raw_source_records.payload_json` 장기보관 방향을 다음과 같이 수정한다.

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
5. API key, Authorization header, deployment secret을 payload에 저장하지 않는다.
6. 전체 HTTP envelope를 무조건 저장하지 않고 기존 `public_provenance` allow-list를 적용한다.

이 문서는 DB Collection v3의 Raw payload 장기보관 위치에 한해 우선한다. 나머지 identity, supersession, observation 계약은 그대로 유지한다.

---

## 2. Bucket 권장 설정

### Bucket

```text
price-check-raw
```

권장값:

- Public access: **OFF**
- Storage class: **Standard**
- Custom domain: 사용하지 않음
- CORS: 사용하지 않음
- Collector token: 해당 bucket에만 `Object Read & Write`
- Streamlit Production: R2 credential을 기본적으로 주입하지 않음

Streamlit은 PostgreSQL의 serving data를 조회한다. Raw 원문 직접열람 기능이 필요해질 때 별도 read-only credential을 검토한다.

### Prefix

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

예:

```text
raw/v1/getSpcifyPrdlstPrcureInfoList/6a/91/6a91....json.gz
```

효과:

- 최근 7일 sliding window 재조회로 동일 record를 반복 수집해도 object key는 동일하다.
- JSON key 순서가 달라도 canonical JSON이 같으면 동일 hash가 된다.
- payload가 한 글자라도 달라지면 새 object가 생성되어 변경 이력이 보존된다.
- gzip은 `mtime=0`으로 생성하여 동일 canonical JSON은 동일 compressed bytes를 만든다.

Object metadata:

```text
sha256=<canonical-json-sha256>
schema=raw-v1
source-operation=<operation>
data-classification=public-provenance
```

---

## 4. PostgreSQL DB1 반영 계약

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

`payload_json`은 장기 source-of-truth로 사용하지 않는다. migration compatibility 때문에 기존 필드가 남더라도 신규 v3 collector는 R2 pointer를 기준으로 구현한다.

Raw object upload와 DB insert 순서:

```text
API record
→ allow-list
→ canonical JSON + SHA-256
→ R2 put/head
→ raw_source_records upsert
→ normalize
→ page commit
```

R2 upload 성공 후 DB transaction이 실패해 orphan object가 생겨도 허용한다. Content-addressed object이므로 재실행 시 같은 key를 재사용하며, 추후 orphan audit로 정리할 수 있다.

반대로 DB pointer를 먼저 commit하고 R2 upload를 나중에 수행하지 않는다.

---

## 5. 권한 경계

### Collector / GitHub Actions

필요 환경변수:

```text
R2_ACCOUNT_ID
R2_BUCKET_NAME
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_RAW_PREFIX=raw/v1
R2_BACKUP_PREFIX=db-backups/v1
```

`R2_ENDPOINT_URL`은 특수 endpoint를 쓰는 경우만 지정한다. 기본 endpoint는:

```text
https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
```

### Streamlit

기본 구성에서는 R2 secret을 넣지 않는다.

```text
Streamlit -> PostgreSQL streamlit_reader -> serving views/tables
```

원본 재확인 UI가 필요해질 경우 writer credential 재사용은 금지하고 별도 read-only token을 사용한다.

---

## 6. Bucket lock / lifecycle 권고

Pilot 권장:

```text
raw/v1/        최소 180일 Bucket Lock
smoke/v1/      Lock 없음
db-backups/v1/ 초기 Lock 없음
```

Raw prefix는 content-addressed immutable 데이터이므로 overwrite/delete가 정상 운영경로가 아니다. 180일 lock은 실수 삭제 방지용이다.

`db-backups/v1/`은 실제 backup job이 구현된 후 retention을 별도 결정한다. 예: 일일 backup 35일 보관. Raw와 backup의 retention을 같은 rule로 묶지 않는다.

Bucket lock을 설정하기 전에 반드시 `smoke/v1/`이 lock 대상에서 제외되어 write/head/delete smoke가 정상 동작하는지 확인한다.

---

## 7. 코드

R2 adapter:

```text
src/purchase_price/storage/r2.py
```

주요 계약:

- `R2RawEvidenceStore.from_settings()`
- `put_public_json()`
- `get_public_json()`
- `probe_read_access()`
- `probe_write_access()`

연결 probe:

```bash
python -m purchase_price.scripts.probe_r2_storage
python -m purchase_price.scripts.probe_r2_storage --write-smoke
```

`--write-smoke`는 `smoke/v1/`에 작은 객체를 생성하고 HEAD 확인 후 즉시 삭제한다.

---

## 8. Live Gate

R2 foundation을 Production-ready로 판정하려면 실제 bucket에서 아래를 확인한다.

```text
[ ] private bucket 생성
[ ] bucket-scoped Object Read & Write token 생성
[ ] read probe SUCCESS
[ ] write/head/delete smoke SUCCESS
[ ] raw/v1 sample upload SUCCESS
[ ] 동일 payload 재업로드 시 created=false
[ ] sample get + SHA-256 검증 SUCCESS
[ ] Streamlit 환경에 writer token이 없는지 확인
[ ] raw/v1 bucket lock 설정 후 재검증
```

실제 Cloudflare credential이 없는 CI에서는 위 항목을 성공했다고 간주하지 않는다.

---

## 9. 비용 메모

2026-09-11 기준 Cloudflare R2 Standard의 무료 포함량은 월 10 GB-month, Class A 100만 요청, Class B 1,000만 요청이며 egress는 무료다. 가격/무료구간은 운영 전에 Cloudflare 공식 문서를 다시 확인한다.

본 Pilot의 초기 Raw Evidence 예상량은 무료 저장구간 안에 머물 가능성이 높지만, 비용보다 G2B API 호출 quota가 먼저 병목이 될 가능성이 높다.

---

## 10. 다음 단계

R2 live Gate 이후 DB1 migration에서 다음을 구현한다.

1. `raw_source_records`에 R2 pointer/byte-size 필드 반영
2. raw ingest repository와 `R2RawEvidenceStore` 연결
3. page transaction 전에 R2 write
4. collector service account와 Streamlit read-only DB account 분리
5. raw byte-size 실측을 기반으로 30일 storage growth report 생성
6. PostgreSQL backup job은 DB 안정화 후 `db-backups/v1/`로 별도 구현
