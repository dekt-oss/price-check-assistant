# F1 — 나라장터쇼핑몰 품목정보 Collector

## 목적

`조달청_나라장터쇼핑몰 품목정보 서비스`를 첫 실제 공공조달 가격 Source로 연결한다.

F1의 완료 기준은 **검증된 나라장터 세부품명으로 실제 조달이력을 수집하고, 원문 Evidence를 보존하며, 제품 동일성 확인 전에는 가격범위에 혼입하지 않는 수집 경로**다.

## 공식 서비스 계약

- REST, JSON+XML
- Base URL: `https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService`
- 개발/운영 자동승인
- 개발계정 기본 트래픽 1,000건
- 주요 operation
  - `getMASCntrctPrdctInfoList`
  - `getUcntrctPrdctInfoList`
  - `getThptyUcntrctPrdctInfoList`
  - `getDlvrReqInfoList`
  - `getDlvrReqDtlInfoList`
  - `getShoppingMallPrdctInfoList`
  - `getVntrPrdctOrderDealDtlsInfoList`
  - `getSpcifyPrdlstPrcureInfoList`
  - `getSpcifyPrdlstPrcureTotList`

현재 end-to-end로 live 검증한 operation은 `getSpcifyPrdlstPrcureInfoList`다. 다른 operation은 이름만 식별되어 있으며 실제 필드/검색계약을 추정해서 사용하지 않는다.

## 2026-09-03 Live 검증 완료

GitHub Actions repository secret `DATA_GO_KR_SERVICE_KEY`를 사용해 실제 API 호출을 검증했다. Secret 값은 로그나 저장소에 노출하지 않는다.

### 인증/통신

- Secret 주입 확인
- API host 연결 확인
- Encoding/Decoding 서비스키를 한 번만 정규화하도록 공통 client 보강
- HTTP 4xx뿐 아니라 HTTP 200 안의 `OpenAPI_ServiceResponse` 오류 envelope도 실패 처리
- 서비스키/요청 URL을 오류 로그에 노출하지 않는 sanitized error 처리
- httpx가 INFO 레벨에서 남기는 `HTTP Request: GET <url>` 로그의 `serviceKey=` 값을 마스킹하는 필터를
  client import 시점에 설치하고, `httpx`/`httpcore` logger를 명시 설정이 없으면 WARNING으로 유지

### 특정품목조달내역 실응답

`getSpcifyPrdlstPrcureInfoList`에서 다음 파라미터 조합이 실제 정상 응답(`resultCode=00`)을 반환함을 확인했다.

- `pageNo`
- `numOfRows`
- `inqryDiv`
- `inqryBgnDate`
- `inqryEndDate`
- `inqryPrdctDiv`
- `fnlCntrctDlvrReqChgOrdYn`
- `dtilPrdctClsfcNoNm`

검증 fixture는 `tests/fixtures/g2b_shopping/specific_item_live_20260715.json`에 서비스키와 불필요 식별필드를 제거한 형태로 보존한다.

실응답에서 확인한 주요 필드:

- `prdctIdntNo`: 물품식별번호
- `prdctIdntNoNm`: 물품식별명/제품 식별 텍스트
- `prdctUprc`: 단가
- `prdctQty`: 수량
- `prdctUnit`: 단위
- `prdctAmt`: 금액
- `corpNm`: 업체명
- `cntrctDlvrReqNo`: 계약/납품요구 번호
- `cntrctDlvrDivNm`: 계약/납품요구 구분
- `cntrctDlvrReqDate`: 계약/납품요구 일자
- `uprcCntrctNo`: 단가계약번호
- `dminsttNm`: 수요기관
- `dlvryCndtnNm`: 납품조건

실제 검증 레코드에서는 `cntrctDlvrDivNm=납품요구`, `prdctUprc=450000`, `prdctQty=1`, `prdctAmt=450000`이 확인되었으며 parser는 이를 `DELIVERY_ORDER_UNIT_PRICE`로 분류한다.

## Phase 0 source-hit smoke

동일 조회구간 `2026-07-14 ~ 2026-08-13`에서 대표 검색어를 실제 호출했다.

| 세부품명 검색어 | resultCode | totalCount | 판단 |
| --- | --- | ---: | --- |
| 인큐베이터 | 00 | 0 | 이 검색어로는 hit 없음. 제품 부재로 해석 금지 |
| 심전도기 | 00 | 0 | 이 검색어로는 hit 없음. 제품 부재로 해석 금지 |
| 노트북컴퓨터 | 00 | 1,021 | 다수 제조사/모델이 `prdctIdntNoNm`에 포함됨 |
| 인공호흡기 | 00 | 9 | 의료장비도 표준 세부품명 기반 source-hit 확인 |

`인공호흡기` 결과에는 `인공호흡기, 조선기기, CSI-2000, 운반형`과 같이 모델이 포함된 물품식별명이 실제 반환됐다.

**중요:** `totalCount=0`은 해당 제품이 나라장터에 없다는 의미가 아니다. `dtilPrdctClsfcNoNm`은 나라장터 표준 세부품명과의 정합성이 중요하므로, 표준명/분류가 검증되지 않은 품목을 임의의 유사어로 자동 재검색하지 않는다.

## G2B 제품 매핑 Registry

`data/g2b_product_mappings.csv`에서 Phase 0 20개 benchmark의 매핑 상태를 관리한다.

현재 `verified`는 2개다.

| benchmark 모델 | 검증된 G2B 세부품명 | 세부품명번호 | live source-hit |
| --- | --- | --- | ---: |
| Sophie | 인공호흡기 | 4227220901 | 9 |
| NT960XJG-K72AG | 노트북컴퓨터 | 4321150301 | 1,021 |

나머지는 `unverified`이며 자동 검색에 사용하지 않는다. 특히 TN500과 MAC5는 임시 검색어가 0건이었기 때문에 표준 세부품명 확인 전까지 fail-closed 상태로 둔다.

`resolve_verified_g2b_mapping()`은 다음 규칙을 따른다.

1. 모델명이 있으면 정규화된 정확 모델키로 먼저 찾는다.
2. 모델명이 없을 때만 제품명 정확키를 사용한다.
3. `verified`이고 세부품명이 있는 단일 매핑만 반환한다.
4. 미검증·중복·모호한 매핑은 자동 추정하지 않고 실패한다.

## 모델 후보 로컬 필터

서버측 모델명 검색 파라미터는 아직 검증되지 않았다. 따라서 검증된 세부품명으로 조달이력을 받은 뒤 `prdctIdntNoNm`에서 모델 토큰을 로컬로 좁힌다.

예:

```text
NT960XJG-K72AG
→ verified mapping: 노트북컴퓨터
→ 나라장터 조달이력 수집
→ prdctIdntNoNm 안에서 정규화된 NT960XJG-K72AG 토큰 후보 추출
```

이 단계는 **후보 축소일 뿐 동일제품 판정이 아니다.** 결과는 계속 `MatchGrade.X`이며 F3에서 제조사·모델·사양·옵션 동일성을 확인하기 전에는 A/B/C/D로 승격하지 않는다.

## Fail-closed 가격 규칙

- `금액`/`prdctAmt`만으로 단가를 만들지 않는다.
- 특정품목 `단가`/`prdctUprc`는 `cntrctDlvrDivNm`의 계약/납품 의미가 확인될 때만 직접가격 EvidenceType으로 승격한다.
- F3 제품 매칭 전에는 모든 조달가격을 `MatchGrade.X`로 유지한다.
- 따라서 실제 단가가 수집되어도 동일제품 여부가 검증되기 전에는 참고가격대 계산에 들어가지 않는다.

## 페이지네이션과 Raw evidence

`totalCount`와 **실제 반환된 행 수**를 기준으로 페이지를 끝까지 수집한다. 요청한 `numOfRows`가 아니라
누적 수신 건수로 완료를 판단하므로, 서버가 페이지 크기를 요청보다 작게 잘라도 조기 종료되지 않는다.

- `max_pages` 안전상한을 둔다.
- 안전상한 때문에 결과가 잘릴 경우 일부 결과를 정상으로 반환하지 않고 실패한다.
- `totalCount`에 못 미쳤는데 빈 페이지가 오면 안전상한까지 반복하지 않고 즉시 실패한다.
- API 각 원문 record를 정규화 전에 `raw_evidence`에 저장한다.
- source + canonical payload SHA-256으로 중복 방지한다.
- 같은 원문 재수집 시 새 evidence를 만들지 않는다.
- parser version과 source record id를 보존한다.
- 이후 parser/matcher 변경 시 원문에서 재처리할 수 있다.

## CI / Live 검증 분리

일반 `CI`는 외부 API나 Secret에 의존하지 않는다.

- Ruff
- pytest
- fixture 기반 parser/ingestion/idempotency/mapping/pagination 검사

실제 API는 `.github/workflows/g2b-live-smoke.yml`과 `.github/workflows/g2b-ground-truth-capture.yml`의
수동 `workflow_dispatch`에서만 호출한다. push 이벤트로 live 호출을 시작하는 workflow는 두지 않는다. 개발계정 호출량과 외부 API 일시 장애가 일반 PR 품질게이트에 영향을 주지 않도록 분리한다.

2026-09-03 현재 일반 CI: **31 tests passed**.

## 아직 확정하지 않은 것

다음은 실제 근거 없이 추정하지 않는다.

- `getShoppingMallPrdctInfoList`의 필수 검색 파라미터 조합
- `getMASCntrctPrdctInfoList`의 실제 camelCase 응답 alias
- `getDlvrReqDtlInfoList`의 실제 camelCase 응답 alias
- 모델명/제조사명을 서버측에서 직접 검색할 수 있는 최적 파라미터
- `inqryDiv=1`, `inqryPrdctDiv=2` 코드값의 업무적 명칭/의미(동작은 live 검증됨)
- 나머지 18개 benchmark의 G2B 표준 세부품명/번호

## F1 완료조건

- [x] GitHub Secret을 통한 실제 API 인증/호출 검증
- [x] 특정품목조달내역 live fixture 확보
- [x] 실제 camelCase 핵심 필드 alias 확정
- [x] 특정품목 검색 파라미터 contract 1종 확정
- [x] raw evidence DB 저장 경로
- [x] 동일 fixture 반복수집 dedupe 테스트
- [x] 서비스키 없는 일반 CI fixture 테스트
- [x] representative benchmark live source-hit smoke
- [x] pagination + 최대 페이지 안전한 중단조건
- [x] verified G2B mapping registry + fail-closed resolver
- [x] 모델 토큰 로컬 후보 축소

## 후속 범위

F1 핵심 수집 경로는 위 조건으로 닫을 수 있다. 다음은 별도 후속 작업으로 관리한다.

1. Phase 0/F3: 나머지 benchmark의 표준 세부품명/번호 검증 확대
2. F3: `prdctIdntNoNm` 구조 분석 후 제조사·모델·사양 동일성 판정과 A/B/C/D/X 승격
3. F1.1: MAS/쇼핑몰 등록/납품요구 상세 operation의 별도 live fixture와 필드 계약 확보
4. 추가 Source: 제조사 공개가격·공공계약 등 나라장터 외 가격 Evidence 확장
