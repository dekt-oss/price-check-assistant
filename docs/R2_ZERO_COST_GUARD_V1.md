# R2 Zero-Cost Storage Guard v1

- 작성일: 2026-09-11
- 대상: `price-check-assistant` 전용 Cloudflare R2 bucket
- 목적: R2 Standard의 10 GB-month 무료 저장구간을 넘지 않도록 애플리케이션 write를 fail-closed 한다.

## 정책

```text
8.0 GB  warning threshold
9.0 GB  hard write stop
10.0 GB Cloudflare free-storage boundary
```

기본값은 1 GB reserve를 둔다. `R2_ZERO_COST_HARD_LIMIT_GB`는 Pydantic validation으로 9.0보다 크게 설정할 수 없다.

## 동작

collector process에서 첫 신규 object를 쓰기 전에 dedicated bucket 전체를 `ListObjectsV2`로 pagination하여 server-reported `Size`를 합산한다. 이후 같은 process에서는 이 baseline에 실제로 새로 생성한 object bytes를 누적한다. 매 record마다 전체 bucket을 다시 scan하지 않는다.

```text
collector 시작
→ 첫 신규 payload
→ content-addressed key HEAD
→ 이미 존재하면 재사용(created=false)
→ 신규 object이면 bucket usage exact scan 1회
→ baseline usage 확보
→ current + new > 9 GB 이면 R2QuotaExceededError
→ 아니면 PUT + run-local new-bytes 누적
→ 이후 신규 object는 baseline + run-local bytes로 즉시 gate
```

따라서 동일 payload 재수집은 추가 저장용량을 요구하지 않는다. 신규 object만 quota gate를 통과한다.

`quota_status(refresh=True)`를 호출하면 bucket을 다시 정확히 scan하고 run-local delta를 재설정한다.

## 전제 및 한계

1. 이 Cloudflare account가 `price-check-assistant` 전용이라는 운영전제를 둔다. 같은 account의 다른 R2 bucket은 동일 무료 저장 allowance를 소비하므로 별도 bucket이 추가되면 account-level 사용량을 별도로 합산해야 한다.
2. R2 object API에는 atomic account-wide storage quota transaction이 없다. 여러 writer가 완전히 동시에 실행될 경우 baseline 이후 외부 write를 즉시 알 수 없다. 1 GB reserve는 이 위험을 흡수하기 위한 보수적 margin이며, 운영 collector는 single-writer schedule을 기본으로 한다.
3. 이 guard는 **저장용량 10 GB-month 경계**를 보호한다. Class A/B request 무료한도까지 포함한 완전한 비용 hard cap은 별도 request-budget telemetry로 관리한다.
4. 현재 프로젝트의 예상 API 호출량은 R2 request 무료한도보다 data.go.kr 호출 quota가 먼저 제약이 될 가능성이 높다.

## 설정

사용자가 추가 Secret을 만들 필요는 없다. 기본값이 코드에 적용된다.

```text
R2_ZERO_COST_WARN_LIMIT_GB=8.0
R2_ZERO_COST_HARD_LIMIT_GB=9.0
```

필요하면 한도를 더 낮출 수 있지만 9.0 GB보다 높일 수 없다.

## 검증

Offline tests는 다음을 강제한다.

- bucket 전체 object byte 합산
- 8 GB warning 상태
- projected usage가 hard limit를 넘으면 PUT 전에 예외
- blocked write에서 put count 증가 없음
- 동일 content-addressed payload는 hard limit에 도달해도 기존 object 재사용
- 9 GB 초과 configuration 거부
- 대량 ingest 경로에서 매 object마다 full bucket scan하지 않음

실제 R2 read/list/write/head/delete와 G2B→R2 vertical slice는 별도 live 검증에서 이미 성공했다.
